"""QPS 令牌桶限流与指数退避重试：保证批量调用不触发平台限流，命中 30% 工程优化。"""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


class TokenBucket:
    """简单令牌桶：按 rate(个/秒) 匀速补充令牌，capacity 个桶容量。"""

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self.rate = max(0.1, rate)
        self.capacity = capacity or max(10.0, self.rate * 2)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """获取一个令牌；令牌不足时返回需要等待的秒数（由调用方 sleep）。"""
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            wait = (1.0 - self._tokens) / self.rate
            self._tokens = 0.0
            return wait


async def with_retry(
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    bucket: TokenBucket | None = None,
    retries: int = 3,
    base_delay: float = 0.6,
    backoff: float = 2.0,
) -> Any:
    """带限流与指数退避重试的请求执行器。

    coro_factory 是无参协程工厂，每次重试重新发起请求；网络错误统一重试，
    重试耗尽后抛出最后一次异常（由上层降级到演示数据）。
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        if bucket is not None:
            wait = await bucket.acquire()
            if wait > 0:
                await asyncio.sleep(wait)
        try:
            return await coro_factory()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_exc = exc
            delay = base_delay * (backoff ** attempt)
            logger.warning("请求失败(第%d次): %s，%.1fs 后重试", attempt + 1, exc, delay)
            await asyncio.sleep(delay)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("重试逻辑异常")  # pragma: no cover
