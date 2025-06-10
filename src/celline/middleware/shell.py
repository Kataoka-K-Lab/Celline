from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable
from enum import Enum
from subprocess import PIPE, Popen
from typing import Final, List, Optional

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
            self._then_fn: Callable[[str], None] | None = None
            self._catch_fn: Callable[[str], None] | None = None
            self._job_id: str | None = None
            self._finished = False
            self._returncode: int | None = None
            self._output: bytes | None = None
            self._error: bytes | None = None
            self._callback_executed = False
            self._pbs_checked = False
            # PBSジョブのID取得は後で非同期で実行

        @property
        def job_id(self):
            return self._job_id

        @property
        def callback_executed(self):
            return self._callback_executed

        def _pbs_initial_check(self):
            """Performs an initial check for PBS job type."""
            if self._pbs_checked:
                return
                
            # qsubプロセスが終了しているかチェック
            if self.process.poll() is None:
                # まだ実行中の場合は待機
                return
                
            self._pbs_checked = True
            stdout, stderr = self.process.communicate()
            
            if self.process.returncode == 0:
                match = re.search(r"(\d+)\..*", stdout.decode("utf-8"))
                if match:
                    self._job_id = match.group(1)
                else:
                    rich.print(f"[bold yellow]Warning: Could not extract job ID from qsub output: {stdout.decode('utf-8')}[/]")
                    self._finished = True
                    self._returncode = 1
                    self._error = b"Failed to extract PBS job ID"
            else:
                rich.print(f"[bold red]PBS qsub failed with return code {self.process.returncode}[/]")
                rich.print(f"[bold red]stdout: {stdout.decode('utf-8')}[/]")
                rich.print(f"[bold red]stderr: {stderr.decode('utf-8')}[/]")
                self._finished = True
                self._returncode = self.process.returncode
                self._error = stderr
                if self._catch_fn:
                    self._catch_fn(stderr.decode("utf-8"))

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
            output: bytes | None,
            error: bytes | None,
            finished: bool,
        ):
            self._returncode = returncode
            self._output = output
            self._error = error
            self._finished = finished
            self._execute_callback()

    DEFAULT_SHELL: Final[str | None] = os.environ.get("SHELL")
    _job_queue: Final = queue.Queue()
    _watcher_started = False

    @classmethod
    def execute(cls, bash_path: str, job_system: ServerSystem.JobType) -> Shell._Job:
        """Executes the given bash file in the shell using the specified job system."""
        if cls.DEFAULT_SHELL is None:
            raise ConnectionError("The default shell is unknown.")

        # PBS実行前のバリデーション
        if job_system == ServerSystem.JobType.PBS:
            if ServerSystem.cluster_server_name is None or ServerSystem.cluster_server_name.strip() == "":
                raise ValueError("PBS job system requires cluster_server_name to be set. Use ServerSystem.usePBS(cluster_name) first.")

            # 生成されたスクリプトのPBSディレクティブをチェック
            try:
                with open(bash_path) as f:
                    script_content = f.read()
                    if "#PBS -l nodes=1:ppn=1:" in script_content and script_content.count("#PBS -l nodes=1:ppn=1:") > 0:
                        lines = script_content.split("\n")
                        for line in lines:
                            if line.startswith("#PBS -l nodes=1:ppn=1:") and line.endswith(":"):
                                raise ValueError(f"Invalid PBS directive found: '{line}'. cluster_server_name appears to be empty.")
            except FileNotFoundError:
                raise FileNotFoundError(f"Script file not found: {bash_path}")

        if job_system == ServerSystem.JobType.MultiThreading:
            bash_path = f"bash {bash_path}"
        else:
            qsub_command = f"qsub {bash_path}"
            bash_path = qsub_command
            
        process = Popen(
            bash_path,
            shell=True,
            stdout=PIPE,
            stderr=PIPE,
            executable=cls.DEFAULT_SHELL,
        )
        
        job = cls._Job(process, job_system)
        
        # PBS job の初期チェック
        if job_system == ServerSystem.JobType.PBS and process.poll() is not None:
            job._pbs_initial_check()
        
        cls._job_queue.put(job)
        
        if not cls._watcher_started:
            watcher_thread = threading.Thread(target=cls._watch_jobs)
            watcher_thread.daemon = False  # Make it non-daemon to keep process alive
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
            elif not any(t.is_alive() for t in threading.enumerate()[2:]):
                break  # Ends watching when all jobs are finished.
            time.sleep(0.5)

    @classmethod
    def _watch_job(cls, job: Shell._Job):
        """Watches a single job and executes its callback function when it finishes."""
        while not job.callback_executed and not job._finished:
            if job.job_system == ServerSystem.JobType.PBS:
                cls._handle_pbs_job(job)
            else:
                cls._handle_generic_job(job)
            
            # Exit early if job is finished to prevent infinite loop
            if job._finished:
                break
                
            time.sleep(0.5)

    @classmethod
    def _handle_pbs_job(cls, job: Shell._Job):
        """Handles watching a PBS job, checking its status and executing its callback function when it finishes."""
        # すでに完了しているかエラーが発生している場合は監視を終了
        if job._finished:
            return

        # PBS初期チェックを実行
        if not job._pbs_checked:
            job._pbs_initial_check()
            if job._finished:
                return
            
        # ジョブIDがまだ取得できていない場合はしばらく待機
        if job.job_id is None:
            if job._pbs_checked:
                rich.print("[bold red]PBS job ID is None after checking. Job submission likely failed.[/]")
                job.set_job_state(returncode=1, output=None, error=b"PBS job ID is None", finished=True)
            return

        with subprocess.Popen(
            "qstat",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            executable=cls.DEFAULT_SHELL,
        ) as p:
            stdout, stderr = p.communicate()

        if p.returncode != 0:
            rich.print(f"[bold yellow]qstat command failed with return code {p.returncode}[/]")
            rich.print(f"[bold yellow]stderr: {stderr.decode('utf-8')}[/]")
            # qstatが失敗した場合、ジョブが完了したと仮定
            job.set_job_state(returncode=0, output=stdout, error=None, finished=True)
            return

        job_status = False
        try:
            data = stdout.decode().split("\n")
            data_rows = data[2:-1]  # 先頭のヘッダと末尾の空行を除く

            if len(data_rows) == 0:
                # ジョブがもうqstatに表示されないので完了とみなす
                job.set_job_state(returncode=0, output=stdout, error=None, finished=True)
                return

            header = ["Job ID", "Name", "User", "Time Use", "S", "Queue"]
            data_rows = [row.split() for row in data_rows if len(row.split()) >= len(header)]

            if len(data_rows) == 0:
                job.set_job_state(returncode=0, output=stdout, error=None, finished=True)
                return

            data_dict = {header[i]: [row[i] for row in data_rows] for i in range(len(header))}
            status_df = pl.DataFrame(data_dict)
            filtered_df = status_df.filter(pl.col("Job ID").str.contains(job.job_id))
            if filtered_df.shape[0] > 0:
                status_values = filtered_df.get_column("S")
                # R (Running) または Q (Queued) の場合はまだ実行中
                if any(status in ["R", "Q"] for status in status_values):
                    job_status = True

        except Exception as e:
            rich.print(f"[bold red]Error parsing qstat output: {e}[/]")
            rich.print(f"[bold red]qstat stdout: {stdout.decode('utf-8')}[/]")
            job.set_job_state(returncode=1, output=None, error=str(e).encode(), finished=True)
            return

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
                    f"[bold red]Shell Error--------------------------\n{err.decode('utf-8')}[/]\n{out.decode('utf-8')}\n[bold red]-------------------------------------[/]",
                )
            job.set_job_state(
                returncode=job.process.returncode,
                output=out,
                error=err,
                finished=True,
            )
