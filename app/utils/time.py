"""레이턴시 측정 유틸리티"""

import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime


@dataclass
class LatencyRecord:
    """measure_latency() 블록의 실행 시간 결과"""

    elapsed_sec: float = 0.0


@contextmanager
def measure_latency():
    """
    블록 실행 시간을 측정하는 context manager.

    Usage:
        with measure_latency() as rec:
            do_something()
        logger.info("elapsed=%.3fs", rec.elapsed_sec)
    """
    record = LatencyRecord()
    start = time.perf_counter()
    try:
        yield record
    finally:
        record.elapsed_sec = time.perf_counter() - start


def task_elapsed_sec(created_at: datetime, completed_at: datetime) -> float:
    """TaskData.created_at → completed_at 차이를 초 단위로 반환."""
    return (completed_at - created_at).total_seconds()
