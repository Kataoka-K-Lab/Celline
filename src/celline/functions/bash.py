import os
import subprocess
from typing import TYPE_CHECKING, Callable, List, Optional

from celline.functions._base import CellineFunction

if TYPE_CHECKING:
    from celline import Project


class Promise:
    def __init__(self, command: str) -> None:
        self._is_done: bool = False
        self._result: Optional[str] = None
        self._error: Optional[str] = None
        self._callbacks: List[Callable[[str], None]] = []
        self._error_callbacks: List[Callable[[str], None]] = []
        self._command: str = command

    def execute(self) -> "Promise":
        try:
            result: bytes = subprocess.check_output(
                self._command,
                shell=True,
                stderr=subprocess.STDOUT,
                executable=os.environ.get("SHELL"),
            )
            self.resolve(result.decode())
        except subprocess.CalledProcessError as e:
            self.catch_error(e.output.decode())
        return self

    def resolve(self, result: str) -> "Promise":
        self._is_done = True
        self._result = result
        for callback in self._callbacks:
            callback(result)
        return self

    def then(self, callback: Callable[[str], None]) -> "Promise":
        self._callbacks.append(callback)
        return self

    def catch_error(self, error: str) -> "Promise":
        self._error = error
        for error_callback in self._error_callbacks:
            error_callback(error)
        return self

    def error(self, callback: Callable[[str], None]) -> "Promise":
        self._error_callbacks.append(callback)
        return self

    def is_done(self) -> bool:
        return self._is_done


class Bash(CellineFunction):
    def __init__(
        self,
        cmd: str,
        then: Optional[Callable[[str], None]],
        catch: Optional[Callable[[str], None]],
    ) -> None:
        self.cmd = cmd
        self.then = then
        self.catch = catch

    def call(self, project: "Project"):
        Promise(self.cmd).then(
            lambda out: self.then(out) if self.then is not None else print("")
        ).error(
            lambda err: self.catch(err) if self.catch is not None else print("")
        ).execute()
        return project
