"""百度客户端解析单元测试（真实接口结构与 Mock 结构差异的回归保护）。"""
import pytest

from app.api.baidu_client import _scalar, BaiduClient


def test_scalar_normalization():
    assert _scalar(1481) == 1481
    assert _scalar({"text": "25分钟", "value": 1481}) == 1481
    assert _scalar([{"text": "25分钟", "value": 1481}]) == 1481
    assert _scalar(None) is None


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    """返回真实 routematrix 结构的伪会话。"""

    def __init__(self, payload):
        self._payload = payload

    async def get(self, url, params=None, timeout=None):
        return _FakeResp(self._payload)


@pytest.mark.asyncio
async def test_route_matrix_parses_real_format():
    """真实接口：result 是元素数组，duration/distance 为 {text,value} 对象。"""
    payload = {
        "status": 0,
        "result": [
            {"distance": {"text": "1.7公里", "value": 1731}, "duration": {"text": "25分钟", "value": 1481}},
            {"distance": {"text": "614米", "value": 614}, "duration": {"text": "9分钟", "value": 524}},
        ],
    }
    client = BaiduClient("fake-ak", _FakeSession(payload))
    out = await client.route_matrix_walking([(25.05, 102.71)], [(25.06, 102.72), (25.05, 102.71)])
    assert out["elements"][0]["duration"] == 1481
    assert out["elements"][0]["distance"] == 1731
    assert out["elements"][1]["duration"] == 524
    assert out["elements"][1]["status"] == 0


@pytest.mark.asyncio
async def test_route_matrix_parses_wrapped_format():
    """兼容 {"result": {"elements": [...]}} 的包装结构。"""
    payload = {
        "status": 0,
        "result": {"elements": [{"duration": {"value": 60}, "distance": {"value": 100}}]},
    }
    client = BaiduClient("fake-ak", _FakeSession(payload))
    out = await client.route_matrix_walking([(25.05, 102.71)], [(25.06, 102.72)])
    assert out["elements"][0]["duration"] == 60
