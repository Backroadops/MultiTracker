import os
import math
from collections import OrderedDict
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

app = FastAPI(title="MultiTracker API", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["https://backroadops.github.io"], allow_methods=["GET"], allow_headers=["*"])
_cache = OrderedDict()
_token = {"value": None, "until": 0}

@app.get("/health")
def health():
    return {"ok": True, "sources": {"adsb": "enabled", "ais": "not_configured", "transit": "not_configured"}}

@app.get("/vehicles")
async def vehicles(lat: float = Query(59.33, ge=-90, le=90), lon: float = Query(18.06, ge=-180, le=180), radius: int = Query(100, ge=1, le=250)):
    key = (round(lat, 1), round(lon, 1), radius)
    if key in _cache and time.monotonic() - _cache[key][0] < 180:
        return _cache[key][1]
    async with _lock:
        return await fetch_aircraft(lat, lon, radius, key)

async def fetch_aircraft(lat, lon, radius, key):
    if key in _cache and time.monotonic() - _cache[key][0] < 180:
        return _cache[key][1]
    lat, lon, radius = key
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
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 0
                retry = exc.response.headers.get("Retry-After", "") if isinstance(exc, httpx.HTTPStatusError) else ""
                _provider_retry[name] = time.monotonic() + max(int(retry) if retry.isdigit() else 0, 3600 if status in (403, 429) else 120)
        if payload is None and time.monotonic() >= _provider_retry.get("opensky", 0):
            try:
                result = await opensky(client, lat, lon, radius)
                return remember(key, result)
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                log.warning("OpenSky failed: %s", exc)
                _provider_retry["opensky"] = time.monotonic() + 900
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
    return remember(key, result)

def remember(key, result):
    _cache[key] = (time.monotonic(), result)
    _cache.move_to_end(key)
    while len(_cache) > 128:
        _cache.popitem(last=False)
    return result

async def opensky(client, lat, lon, radius):
    # Radius is nautical miles, as in the ADS-B point APIs.
    delta = radius / 60
    dx = min(180, delta / max(0.01, math.cos(math.radians(lat))))
    headers = {}
    cid, secret = os.getenv("OPENSKY_CLIENT_ID"), os.getenv("OPENSKY_CLIENT_SECRET")
    log.info("OpenSky credentials configured: client_id=%s client_secret=%s", bool(cid), bool(secret))
    if cid and secret:
        if time.monotonic() >= _token["until"]:
            r = await client.post("https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token", data={"grant_type":"client_credentials","client_id":cid,"client_secret":secret})
            r.raise_for_status()
            log.info("OpenSky OAuth token request succeeded: HTTP %s", r.status_code)
            t = r.json()
            _token.update(value=t["access_token"], until=time.monotonic()+max(0,int(t.get("expires_in",300))-30))
        headers["Authorization"] = "Bearer " + _token["value"]
    r = await client.get("https://opensky-network.org/api/states/all", headers=headers, params={"lamin":max(-90,lat-delta),"lamax":min(90,lat+delta),"lomin":max(-180,lon-dx),"lomax":min(180,lon+dx)})
    log.info("OpenSky states response: HTTP %s, authenticated=%s, retry_after=%s", r.status_code, bool(headers), r.headers.get("Retry-After", "not supplied"))
    r.raise_for_status()
    result = []
    for a in r.json().get("states") or []:
        if len(a)<17 or a[5] is None or a[6] is None or a[3] is None:
            continue
        if time.time()-a[3]>180:
            continue
        result.append({"id":a[0],"label":(a[1] or a[0]).strip(),"type":"helicopter" if len(a)>17 and a[17]==8 else "aircraft","latitude":a[6],"longitude":a[5],"speed_kmh":round(a[9]*3.6,1) if a[9] is not None else None,"heading":a[10],"altitude_m":a[7],"timestamp":datetime.fromtimestamp(a[3],timezone.utc).isoformat(),"source":"OpenSky"})
    log.info("OpenSky returned %d recent positions",len(result))
    return result
