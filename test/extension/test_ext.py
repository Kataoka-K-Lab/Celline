from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from celline.functions._base import CellineFunction

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable

    from celline import Project


class TestExtension(CellineFunction):
    def __init__(
        self,
        then: Optional[Callable[[str], None]] = None,
        catch: Optional[Callable[[subprocess.CalledProcessError], None]] = None,
    ):
        super().__init__(then, catch)

    def call(self, project: Project):
        return super().call(project)
