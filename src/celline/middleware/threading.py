from __future__ import annotations

import queue
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from functools import partial
from typing import Any, Dict, Final, List, Optional, Union

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from celline.middleware.shell import Shell
from celline.server import ServerSystem


class ThreadObservable:
    """## ThreadObservable class handles multiple shell scripts execution using threads.

    Attributes:
        `ObservableShell`: NamedTuple representing a shell script to be observed.

    Note:
        If you are calling this class from Jupyter Notebook, remember to call the `watch` function
        to ensure all the scripts get executed.

    """

    progress_tasks: dict[str, TaskID] = {}

    class ObservableShell:
        """## Observable shell which used in thread observable"""

        script_path: str
        then: Callable[[str], None]
        catch: Callable[[str], None]
        job: Shell._Job | None = None

        def __init__(
            self,
            script_path: str,
            then: Callable[[str], Any | None],
            catch: Callable[[str], Any | None],
        ):
            self.script_path = script_path
            self.then = then
            self.catch = catch
            self.job = None

    _jobs: int = 1
    wait_for_complete: bool = True
    __running_jobs: dict[str, ObservableShell] = {}
    __queue: queue.Queue = queue.Queue()
    __lock: threading.Lock = threading.Lock()

    @classmethod
    def set_jobs(cls, njobs: int):
        """#### Set numbre of jobs"""
        ThreadObservable._jobs = njobs
        return cls

    @classmethod
    @property
    def njobs(cls) -> int:
        """#### Numbre of jobs"""
        return cls._jobs

    logging = True
    progress: Progress
    shell_ctrl: list[str] | list[ObservableShell] | None = None

    @classmethod
    def call_shell(
        cls,
        shell_ctrl: list[str] | list[ObservableShell],
        proc_name: str | None = None,
        logging=True,
    ):
        """#### Execute shell scripts using threads.

        Args:
            `shell_ctrl<Union[List[str], List[ObservableShell]]>`: List of shell scripts or observable shell objects to be executed.\n
            `job_type<Shell.JobType -optional>`: Type of job execution (single-threaded or multi-threaded). Defaults to Shell.JobType.MultiThreading.

        """
        cls.logging = logging
        if proc_name is None:
            proc_name = "Shell progress"
        cls.progress = Progress(
            SpinnerColumn(),
            "[bold blue]{task.fields[icon]}",
            TextColumn(f"[bold blue]{proc_name}", justify="left"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.1f}%",
            TimeRemainingColumn(),
            TimeElapsedColumn(),
            "[progress.elapsed] [bold yellow]{task.fields[status]}",
        )
        cls.shell_ctrl = shell_ctrl
        job_type = ServerSystem.job_system

        def handler(
            _hased_id: str,
            defaultcall: Callable[[str], None] | None = None,
            arg: str | None = None,
        ):
            with cls.__lock:
                if _hased_id in cls.__running_jobs:
                    cls.__running_jobs.pop(_hased_id)
            if defaultcall is not None and arg is not None:
                defaultcall(arg)

        for shell in shell_ctrl:
            hashedid = str(uuid.uuid4())
            if isinstance(shell, str):
                with cls.__lock:
                    cls.__running_jobs[hashedid] = ThreadObservable.ObservableShell(
                        shell,
                        lambda _, h_id=hashedid: handler(h_id),
                        lambda _, h_id=hashedid: handler(h_id),
                    )
                    cls.__queue.put(hashedid)
            # 'then'と'catch'が存在することを確認する
            elif hasattr(shell, "then") and hasattr(shell, "catch"):
                with cls.__lock:
                    cls.__running_jobs[hashedid] = ThreadObservable.ObservableShell(
                        shell.script_path,
                        lambda out, h_id=hashedid, s=shell: handler(
                            h_id,
                            s.then,
                            out,
                        ),
                        lambda err, h_id=hashedid, s=shell: handler(
                            h_id,
                            s.catch,
                            err,
                        ),
                    )
                    cls.__queue.put(hashedid)
            else:
                raise ValueError(
                    "'shell' object must have 'then' and 'catch' attributes",
                )
        cls.progress_tasks["all_tasks"] = cls.progress.add_task(
            "run",
            total=len(shell_ctrl) * 100,
            status="Running Jobs",
            icon="🚀",
        )

        def get_first():
            with cls.__lock:
                if cls.__queue.empty():
                    return None
                first_key = cls.__queue.get()
                first_value = cls.__running_jobs[first_key]
                return first_value

        def thenHandler(output: str, script: ThreadObservable.ObservableShell):
            print(f"[DEBUG] thenHandler called for script: {script.script_path}")
            script.then(output)
            next_script = get_first()
            if next_script is not None:
                Shell.execute(next_script.script_path, job_type).then(
                    partial(thenHandler, script=next_script),
                ).catch(lambda reason: catchHandler(reason, next_script))

        def catchHandler(reason: str, script: ThreadObservable.ObservableShell):
            print(f"[DEBUG] catchHandler called for script: {script.script_path}, reason: {reason}")
            script.catch(reason)
            next_script = get_first()
            if next_script is not None:
                Shell.execute(next_script.script_path, job_type).then(
                    partial(thenHandler, script=next_script),
                ).catch(lambda reason: catchHandler(reason, next_script))

        # 最初のnjobs個のスクリプトを実行
        for i in range(min(ThreadObservable._jobs, len(cls.__running_jobs))):
            script = get_first()
            if script is not None:
                print(f"[DEBUG] Starting job {i+1}: {script.script_path}")
                script.job = Shell.execute(script.script_path, job_type)
                print(f"[DEBUG] Job created, finished: {script.job._finished}, callback_executed: {script.job.callback_executed}")
                
                script.job.then(partial(thenHandler, script=script)).catch(
                    partial(catchHandler, script=script),
                )
                print(f"[DEBUG] Callbacks set, finished: {script.job._finished}, callback_executed: {script.job.callback_executed}")
                
                if script.job._finished:
                    print(f"[DEBUG] Job {i+1} is already finished!")
        cls.watch()
        return cls

    @classmethod
    def watch(cls):
        if cls.shell_ctrl is not None:
            total_tasks = len(cls.shell_ctrl)

            def __proc():
                try:
                    # total_tasks = len(cls.progress_tasks) - 1  # "all_tasks" を除く
                    while not cls.__queue.empty() or cls.__running_jobs:
                        completed_tasks = total_tasks - len(cls.__running_jobs)
                        # print(completed_tasks)
                        cls.progress.update(
                            cls.progress_tasks["all_tasks"],
                            completed=completed_tasks * 100,
                        )
                        time.sleep(0.1)
                    cls.progress.update(
                        cls.progress_tasks["all_tasks"],
                        completed=(total_tasks + 1) * 100,
                        icon="✅",
                        status="Done",
                    )
                except KeyboardInterrupt:
                    cls.progress.update(
                        cls.progress_tasks["all_tasks"],
                        completed=(total_tasks + 1) * 100,
                        icon="❌",
                        status="Interrupted",
                    )
                    print(
                        "\nKeyboard interrupt received. Attempting to terminate running jobs.",
                    )

                    for hashed_id, observable_shell in cls.__running_jobs.items():
                        script = observable_shell.script_path
                        job = cls.__running_jobs.get(hashed_id, None)
                        if job:
                            # if the job is running under PBS system
                            if job.job is not None:
                                if job.job.job_system == ServerSystem.JobType.PBS and job.job.job_id:
                                    with subprocess.Popen(
                                        f"qdel {job.job.job_id}",
                                        shell=True,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                    ) as p:
                                        p.wait()
                                    print(f"├─ Terminating PBS job: {job.job.job_id}")
                                else:
                                    # if the job is not under PBS, we simply terminate it
                                    job.job.process.terminate()
                                    print(f"├─ Terminating shell script: {script}")

                    print("└─ Exit.")
                time.sleep(0.1)

            if cls.logging:
                with cls.progress:
                    __proc()
            else:
                __proc()
        return cls
