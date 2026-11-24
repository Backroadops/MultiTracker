import os
import logging
import asyncio
from datetime import datetime, timezone
log = logging.getLogger('uvicorn.error')
_lock = asyncio.Lock()
_provider_retry = {}
import time
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="MultiTracker API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["https://backroadops.github.io"], allow_methods=["GET"], allow_headers=["*"])
_cache = {"at": 0.0, "data": []}

@app.get("/health")
def health():
    return {"ok": True, "sources": {"adsb": "enabled", "ais": "not_configured", "transit": "not_configured"}}

@app.get("/vehicles")
async def vehicles(lat: float = Query(59.33, ge=-90, le=90), lon: float = Query(18.06, ge=-180, le=180), radius: int = Query(100, ge=1, le=250)):
    key = (round(lat, 1), round(lon, 1), radius)
    if time.monotonic() - _cache["at"] < 60 and _cache.get("key") == key:
        return _cache["data"]
    async with _lock:
        return await fetch_aircraft(lat, lon, radius, key)

async def fetch_aircraft(lat, lon, radius, key):
    if time.monotonic() - _cache["at"] < 60 and _cache.get("key") == key:
        return _cache["data"]
    payload = None
    source = None
    async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers={"User-Agent": "MultiTracker/0.2"}) as client:
        for name, url in [
            ("adsb.lol", f"https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{radius}"),
            ("airplanes.live", f"https://api.airplanes.live/v2/point/{lat}/{lon}/{radius}")
        ]:
            if time.monotonic() < _provider_retry.get(name, 0):
                continue
            try:
                response = await client.get(url)
                response.raise_for_status()
                candidate = response.json()
                if not isinstance(candidate.get("ac"), list):
                    raise ValueError("Invalid aircraft payload")
                payload, source = candidate, name
                log.info("Aircraft provider %s returned %d records", name, len(candidate["ac"]))
                break
            except (httpx.HTTPError, ValueError, AttributeError) as exc:
                log.warning("Aircraft provider %s failed: %s", name, exc)
                _provider_retry[name] = time.monotonic() + 60
    if payload is None:
        raise HTTPException(status_code=503, detail="Aircraft providers unavailable; retry later")
    result = []
    for a in payload.get("ac", []):
        if not isinstance(a.get("lat"), (int, float)) or not isinstance(a.get("lon"), (int, float)):
            continue
        result.append({
            "id": str(a.get("hex", "")),
            "type": "helicopter" if a.get("category") == "A7" else "aircraft",
            "label": (a.get("flight") or a.get("r") or a.get("hex") or "Aircraft").strip(),
            "latitude": a["lat"], "longitude": a["lon"],
            "speed_kmh": round(a["gs"] * 1.852, 1) if isinstance(a.get("gs"), (int, float)) else None,
            "heading": a.get("track"),
            "altitude_m": round(a["alt_baro"] * 0.3048) if isinstance(a.get("alt_baro"), (int, float)) else None,
            "source": source,
            "timestamp": datetime.fromtimestamp(time.time() - max(0, a.get("seen_pos", 0) or 0), timezone.utc).isoformat() if isinstance(a.get("seen_pos"), (int, float)) else None,
        })
    _cache.update({"at": time.monotonic(), "key": key, "data": result})
    return result
