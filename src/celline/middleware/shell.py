from __future__ import annotations
import os
import re
import time
import queue
import threading
import subprocess
from subprocess import Popen, PIPE
from typing import Optional, Callable, Final, List
from enum import Enum
import polars as pl
import rich

from celline.server.setting import ServerSystem


class Shell:
    """## Represents a shell environment, allowing commands to be executed either via multithreading or a PBS job system."""

    class _Job:
        """A class that represents a job to be executed in the shell."""

        def __init__(self, process: Popen, job_system: ServerSystem.JobType):
            """Initializes the job with the given process and job system."""
            self.process = process
            self.job_system = job_system
            self._then_fn: Optional[Callable[[str], None]] = None
            self._catch_fn: Optional[Callable[[str], None]] = None
            self._job_id: Optional[str] = None
            self._finished = False
            self._returncode: Optional[int] = None
            self._output: Optional[bytes] = None
            self._error: Optional[bytes] = None
            self._callback_executed = False
            if self.job_system == ServerSystem.JobType.PBS:
                self._pbs_initial_check()

        @property
        def job_id(self):
            return self._job_id

        @property
        def callback_executed(self):
            return self._callback_executed

        def _pbs_initial_check(self):
            """Performs an initial check for PBS job type."""
            stdout, _ = self.process.communicate()
            if self.process.returncode == 0:
                match = re.search(r"(\d+)\..*", stdout.decode("utf-8"))
                if match:
                    self._job_id = match.group(1)
            else:
                if self._catch_fn:
                    self._catch_fn(stdout.decode("utf-8"))

        def then(self, callback: Callable[[str], None]) -> Shell._Job:
            """Sets a callback function to be executed when the job finishes successfully."""
            self._then_fn = callback
            if self._finished:
                self._execute_callback()
            return self

        def catch(self, reason: Callable[[str], None]) -> Shell._Job:
            """Sets a callback function to be executed when the job fails."""
            self._catch_fn = reason
            if self._finished:
                self._execute_callback()
            return self

        def _execute_callback(self):
            """Executes the appropriate callback function based on the job's return code."""
            if self._callback_executed:
                return
            if self._returncode == 0 and self._then_fn:
                self._then_fn(self._output.decode("utf-8") if self._output else "")
            elif self._catch_fn:
                self._catch_fn(self._error.decode("utf-8") if self._error else "")
            self._callback_executed = True

        def set_job_state(
            self,
            returncode: int,
            output: Optional[bytes],
            error: Optional[bytes],
            finished: bool,
        ):
            self._returncode = returncode
            self._output = output
            self._error = error
            self._finished = finished
            self._execute_callback()

    DEFAULT_SHELL: Final[Optional[str]] = os.environ.get("SHELL")
    _job_queue: Final = queue.Queue()
    _watcher_started = False

    @classmethod
    def execute(cls, bash_path: str, job_system: ServerSystem.JobType) -> Shell._Job:
        """Executes the given bash file in the shell using the specified job system."""
        if cls.DEFAULT_SHELL is None:
            raise ConnectionError("The default shell is unknown.")
        rc_file = "~/.bashrc" if "bash" in cls.DEFAULT_SHELL else "~/.zshrc"
        bash_path = (
            f"bash {bash_path}"
            if job_system == ServerSystem.JobType.MultiThreading
            else f"source {rc_file} && qsub {bash_path}"
        )
        process = Popen(
            bash_path,
            shell=True,
            stdout=PIPE,
            stderr=PIPE,
            executable=cls.DEFAULT_SHELL,
        )
        job = cls._Job(process, job_system)
        cls._job_queue.put(job)
        if not cls._watcher_started:
            watcher_thread = threading.Thread(target=cls._watch_jobs)
            watcher_thread.daemon = True  # Here we set daemon
            watcher_thread.start()
            cls._watcher_started = True
        return job

    @classmethod
    def _watch_jobs(cls):
        """Watches all jobs in the queue and creates a new thread for each one."""
        while True:
            if not cls._job_queue.empty():
                job = cls._job_queue.get()
                threading.Thread(target=cls._watch_job, args=(job,)).start()
            else:
                if not any(t.is_alive() for t in threading.enumerate()[2:]):
                    break  # Ends watching when all jobs are finished.
            time.sleep(0.5)

    @classmethod
    def _watch_job(cls, job: Shell._Job):
        """Watches a single job and executes its callback function when it finishes."""
        while not job.callback_executed:
            if job.job_system == ServerSystem.JobType.PBS:
                cls._handle_pbs_job(job)
            else:
                cls._handle_generic_job(job)
            time.sleep(0.5)

    @classmethod
    def _handle_pbs_job(cls, job: Shell._Job):
        """Handles watching a PBS job, checking its status and executing its callback function when it finishes."""
        with subprocess.Popen(
            "qstat",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            executable=cls.DEFAULT_SHELL,
        ) as p:
            stdout, _ = p.communicate()
        job_status = False
        if job.job_id is not None:
            data = stdout.decode().split("\n")
            data_rows = data[2:-1]  # 先頭のヘッダと末尾の空行を除く
            header = ["Job ID", "Name", "User", "Time Use", "S", "Queue"]
            data_rows = [row.split() for row in data_rows]
            data_dict = {
                header[i]: [row[i] for row in data_rows] for i in range(len(header))
            }
            status_df = pl.DataFrame(data_dict)
            filtered_df = status_df.filter(pl.col("Job ID").str.contains(job.job_id))
            if filtered_df.shape[0] > 0:
                if filtered_df.get_column("S").str.contains("[RQ]").sum() > 0:
                    job_status = True
        if not job_status:
            job.set_job_state(returncode=0, output=stdout, error=None, finished=True)

    @classmethod
    def _handle_generic_job(cls, job: Shell._Job):
        """Handles watching a generic job, checking its status and executing its callback function when it finishes."""
        if job.process.poll() is not None:
            out, err = job.process.communicate()
            if job.process.returncode == 1:
                # on error
                rich.print(
                    f"[bold red]Shell Error--------------------------\n{err.decode('utf-8')}[/]\n{out.decode('utf-8')}\n[bold red]-------------------------------------[/]"
                )
            job.set_job_state(
                returncode=job.process.returncode, output=out, error=err, finished=True
            )
