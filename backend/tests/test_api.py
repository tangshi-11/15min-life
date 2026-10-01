"""FastAPI 端点测试（演示模式）。"""
from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_inspect_with_address():
    with TestClient(app) as client:
        r = client.post("/api/inspect", json={"address": "翠湖"})
        assert r.status_code == 200
        data = r.json()
        assert data["center"]["lat"] > 0
        assert data["isochrone"]["polygon"] is not None
        assert data["isochrone"]["grid"]["n"] > 0
        assert "coverage" in data and "overall" in data["coverage"]
        assert "blind_spots" in data
        assert "pois" in data


def test_inspect_with_center_coords():
    with TestClient(app) as client:
        r = client.post("/api/inspect", json={"center": {"lat": 25.0406, "lng": 102.7146}})
        assert r.status_code == 200
        data = r.json()
        assert abs(data["center"]["lat"] - 25.0406) < 1e-6


def test_inspect_missing_params():
    with TestClient(app) as client:
        r = client.post("/api/inspect", json={})
        assert r.status_code == 400
