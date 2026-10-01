"""限流与重试单元测试（30% 工程优化评分项）。"""
import asyncio
import time

import pytest

from app.api.rate_limiter import TokenBucket, with_retry


@pytest.mark.asyncio
async def test_token_bucket_limits_rate():
    bucket = TokenBucket(rate=10, capacity=10)
    # 前 10 次无需等待
    waits = [await bucket.acquire() for _ in range(10)]
    assert all(w == 0 for w in waits)
    # 第 11 次需要等待
    wait = await bucket.acquire()
    assert wait > 0


@pytest.mark.asyncio
async def test_token_bucket_refills():
    bucket = TokenBucket(rate=100, capacity=1)
    await bucket.acquire()
    t0 = time.monotonic()
    wait = await bucket.acquire()
    assert wait > 0.005  # 按 100/s 补充
    await asyncio.sleep(wait + 0.02)
    assert await bucket.acquire() == 0


@pytest.mark.asyncio
async def test_with_retry_succeeds_after_failures():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("temporary")
        return "ok"

    result = await with_retry(flaky, retries=4, base_delay=0.01)
    assert result == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_with_retry_exhausts():
    calls = {"n": 0}

    async def always_fail():
        calls["n"] += 1
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await with_retry(always_fail, retries=3, base_delay=0.01)
    assert calls["n"] == 3
