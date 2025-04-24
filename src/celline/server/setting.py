from __future__ import annotations
from typing import Optional
from enum import Enum

from celline.decorators import classproperty


class ServerSystem:
    class JobType(Enum):
        """An enumeration that specifies the type of job system to use."""

        MultiThreading = 1
        PBS = 2

    job_system: JobType = JobType.MultiThreading
    cluster_server_name: Optional[str] = None

    @classmethod
    def useMultiThreading(cls):
        cls.job_system = ServerSystem.JobType.MultiThreading
        cls.cluster_server_name = None

    @classmethod
    def usePBS(cls, cluster_server_name: str):
        cls.job_system = ServerSystem.JobType.PBS
        cls.cluster_server_name = cluster_server_name
