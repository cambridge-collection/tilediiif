import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator


@dataclass
class CapacityLock:
    """A lock that limits concurrent access to a resource, where each accessor
    uses variable-size fraction of the resource's capacity.

    For example, (and the use case in this module) CapacityLock can prevent too
    many concurrent threads consuming all available disk space. The CapacityLock
    is created with the available disk space as the total_capacity. Each thread
    calling acquire() specifies the amount of space it needs. Concurrent
    acquire() calls can proceed, so long as they wouldn't cause the
    total_capacity—and thus disk space—to be exceeded.
    """

    total_capacity: int
    _used_capacity: int = field(default=0)
    _condition: threading.Condition = field(default_factory=threading.Condition)

    def __post_init__(self) -> None:
        if self.total_capacity <= 0:
            raise ValueError("total_capacity must be > 0")

    @property
    def used_capacity(self) -> int:
        return self._used_capacity

    @contextmanager
    def acquire(self, capacity: int) -> Generator[None, None, None]:
        if capacity < 1:
            raise ValueError(f"capacity must be > 0 {capacity=}")
        with self._condition:
            # Always allow a single request to enter, even if it requests more
            # capacity than the limit, otherwise we'll deadlock. Our
            # responsibility is to prevent concurrent requests overflowing the
            # capacity, not to protect a resource from a single oversized
            # interaction — applications can check and handle this.
            while (
                self._used_capacity > 0
                and self._used_capacity + capacity > self.total_capacity
            ):
                self._condition.wait()
            self._used_capacity += capacity
            assert self._used_capacity > 0
        try:
            yield
        finally:
            with self._condition:
                self._used_capacity -= capacity
                assert self._used_capacity >= 0
                # Our cleared capacity could allow multiple acquire calls to
                # proceed.
                self._condition.notify_all()
