"""Wiring smoke test -- exercises the FastAPI route against a fake snapshot,
without ever touching the real Nubra API (no credentials in CI/dev boxes)."""

import types
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.app import app, poller
from backend.metrics import normalize_chain
from tests.test_metrics import make_option, make_wrapper

client = TestClient(app)  # not used as a context manager -> lifespan (real login) never runs


def _seed_fake_snapshot():
    wrapper = make_wrapper(
        ce=[make_option(ref_id=1, strike_price=2580000, last_traded_price=8200)],
        pe=[make_option(ref_id=2, strike_price=2500000, last_traded_price=7600, delta=-0.20)],
    )
    normalized = normalize_chain(wrapper)
    poller._snapshot = normalized
    poller._last_updated = datetime.now(timezone.utc)
    poller._last_error = None


def test_scan_returns_503_before_first_poll():
    poller._snapshot = None
    response = client.get("/api/scan")
    assert response.status_code == 503


def test_scan_returns_ranked_rows_once_seeded():
    _seed_fake_snapshot()
    response = client.get("/api/scan")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["asset"] == "NIFTY"
    assert len(data["rows"]) == 2
    assert data["top_call"]["ref_id"] == 1
    assert data["top_put"]["ref_id"] == 2


def test_scan_filters_by_side():
    _seed_fake_snapshot()
    response = client.get("/api/scan", params={"side": "CE"})
    data = response.json()
    assert all(r["type"] == "CE" for r in data["rows"])
