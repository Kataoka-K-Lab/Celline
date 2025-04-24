from typing import List
import math


def split_jobs(
    max_job_size: int, nthread: int, each_job_size: List[int] = []
) -> List[int]:
    """
    Generate job size array which splitted into nthread from max_job_size.
    return: job size array
    """
    target_size = math.ceil(max_job_size / nthread)
    each_job_size.append(target_size)
    if nthread != 1:
        return split_jobs(max_job_size - target_size, nthread - 1, each_job_size)
    else:
        return each_job_size
