import random
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from typing import Generator

import pytest

from tilediiif.awslambda.capacitylock import CapacityLock


@pytest.fixture
def executor() -> Generator[ThreadPoolExecutor, None, None]:
    executor = ThreadPoolExecutor(max_workers=10)
    yield executor
    shutdown_thread = Thread(target=lambda: executor.shutdown(wait=True))
    shutdown_thread.start()
    shutdown_thread.join(timeout=0.1)
    if shutdown_thread.is_alive():
        raise RuntimeError("executor failed to shutdown")


def test_single_oversize_acquire_can_proceed():
    cl = CapacityLock(10)
    with cl.acquire(15):
        pass


def test_concurrent_oversize_requests_dont_exceed_capacity(
    executor: ThreadPoolExecutor,
):
    cl = CapacityLock(10)

    def use_capacity(capacity: int) -> int:
        with cl.acquire(capacity):
            used_capacity1 = cl.used_capacity
            time.sleep(0.1)
            return max(used_capacity1, cl.used_capacity)

    assert all(c == 15 for c in executor.map(use_capacity, [15 for _ in range(3)]))


def test_concurrent_requests_dont_exceed_capacity(executor: ThreadPoolExecutor):
    rng = random.Random("fixedseed")
    cl = CapacityLock(30)

    def use_capacity(capacity: int) -> int:
        with cl.acquire(capacity):
            used_capacity1 = cl.used_capacity
            time.sleep(0.05)
            return max(used_capacity1, cl.used_capacity)

    capacities = [rng.randint(1, 20) for _ in range(18)]
    assert all(c <= 30 for c in executor.map(use_capacity, capacities))
