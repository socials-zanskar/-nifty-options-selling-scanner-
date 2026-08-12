import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import config, nubra_client
from backend.metrics import build_scan
from backend.poller import ChainPoller

poller = ChainPoller(config.DEFAULT_INSTRUMENT, config.POLL_INTERVAL_SEC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Blocking on purpose: login (incl. any OTP prompt) must finish before
    # the server starts accepting requests.
    nubra_client.get_market_data()
    poller.start()
    yield
    poller.stop()


app = FastAPI(lifespan=lifespan)


@app.get("/api/scan")
def api_scan(
    side: str = Query(config.DEFAULT_FILTERS["side"]),
    delta_min: float = Query(config.DEFAULT_FILTERS["delta_min"]),
    delta_max: float = Query(config.DEFAULT_FILTERS["delta_max"]),
    min_oi: int = Query(config.DEFAULT_FILTERS["min_oi"]),
    min_volume: int = Query(config.DEFAULT_FILTERS["min_volume"]),
    expiry: str = Query(""),
):
    if expiry:
        poller.set_expiry(expiry)

    snapshot, last_updated, last_error = poller.get_snapshot()
    if snapshot is None:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": last_error or "No data yet -- still fetching first snapshot."},
        )

    filters = {
        "side": side.upper(),
        "delta_min": delta_min,
        "delta_max": delta_max,
        "min_oi": min_oi,
        "min_volume": min_volume,
    }
    result = build_scan(snapshot, filters)
    result["status"] = "ok"
    result["last_updated"] = last_updated.isoformat() if last_updated else None
    result["last_error"] = last_error
    return result


class NoCacheStaticFiles(StaticFiles):
    """Serve the dashboard's HTML/CSS/JS with caching disabled.

    Without this the browser holds on to an old app.js/style.css after an edit
    and silently keeps rendering the previous version -- a bad surprise to hit
    while presenting. These are a few KB served from localhost, so there's
    nothing to gain from caching them anyway.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response


_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/", NoCacheStaticFiles(directory=_frontend_dir, html=True), name="frontend")
