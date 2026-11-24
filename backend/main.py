import os
import time
from fastapi import FastAPI, Query
import httpx

app = FastAPI(title="MultiTracker API", version="0.1.0")
_cache = {"at": 0.0, "data": []}

@app.get("/health")
def health():
    return {"ok": True, "sources": {"adsb": "enabled", "ais": "not_configured", "transit": "not_configured"}}

@app.get("/vehicles")
async def vehicles(lat: float = Query(59.33, ge=-90, le=90), lon: float = Query(18.06, ge=-180, le=180), radius: int = Query(100, ge=1, le=250)):
    key = (round(lat, 1), round(lon, 1), radius)
    if time.monotonic() - _cache["at"] < 60 and _cache.get("key") == key:
        return _cache["data"]
    url = f"https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{radius}"
    try:
        async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "MultiTracker/0.1"}) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return _cache["data"] if _cache.get("key") == key else []
    result = []
    for a in payload.get("ac", []):
        if not isinstance(a.get("lat"), (int, float)) or not isinstance(a.get("lon"), (int, float)):
            continue
        result.append({
            "id": str(a.get("hex", "")),
            "type": "helicopter" if str(a.get("t", "")).upper().startswith(("H", "EC", "R44")) else "aircraft",
            "label": (a.get("flight") or a.get("r") or a.get("hex") or "Aircraft").strip(),
            "latitude": a["lat"], "longitude": a["lon"],
            "speed_kmh": round(a.get("gs", 0) * 1.852, 1),
            "heading": a.get("track"),
            "altitude_m": round(a["alt_baro"] * 0.3048) if isinstance(a.get("alt_baro"), (int, float)) else None,
            "source": "adsb.lol",
        })
    _cache.update({"at": time.monotonic(), "key": key, "data": result})
    return result
