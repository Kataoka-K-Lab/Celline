from __future__ import annotations

from enum import Enum
from typing import Optional

from celline.decorators import classproperty


class ServerSystem:
    class JobType(Enum):
        """An enumeration that specifies the type of job system to use."""

        MultiThreading = 1
        PBS = 2

    job_system: JobType = JobType.MultiThreading
    cluster_server_name: str | None = None

    @classmethod
    def useMultiThreading(cls):
        cls.job_system = ServerSystem.JobType.MultiThreading
        cls.cluster_server_name = None

    @classmethod
    def usePBS(cls, cluster_server_name: str):
        if cluster_server_name is None or cluster_server_name.strip() == "":
            raise ValueError("cluster_server_name cannot be None or empty")
        cls.job_system = ServerSystem.JobType.PBS
        cls.cluster_server_name = cluster_server_name.strip()

    @classmethod
    def is_pbs_configured(cls) -> bool:
        """Check if PBS is properly configured."""
        return cls.job_system == ServerSystem.JobType.PBS and cls.cluster_server_name is not None and cls.cluster_server_name.strip() != ""

    @classmethod
    def get_status(cls) -> str:
        """Get current configuration status."""
        if cls.job_system == ServerSystem.JobType.PBS:
            if cls.is_pbs_configured():
                return f"PBS (cluster: {cls.cluster_server_name})"
            return "PBS (not configured - cluster_server_name is empty)"
        return "MultiThreading"
