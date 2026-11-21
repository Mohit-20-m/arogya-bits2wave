"""Real hospitals near a patient, from OpenStreetMap (Overpass API), with real road travel times (OSRM).

* Queried by THIS server (never by the browser), only with a map location - no patient data leaves the system.
* Public Overpass servers are often busy: several mirrors are tried and results are cached for 7 days.
* OpenStreetMap rarely records medical specialities, so each place gets a CATEGORY guessed from its name and tags;
  the app says so ("category from the name - call before going"). Places that cannot help with an oral lesion
  (Ayurveda, homeopathy, eye, veterinary...) are left out.
"""
from __future__ import annotations

import asyncio
import json
import math
import re

import httpx

from ..config import get_settings
from ..observability import log

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
OSRM_URL = "https://router.project-osrm.org"
USER_AGENT = "Arogya-oral-screening/1.0 (health-worker referral map)"
CACHE_S = 7 * 24 * 3600

# category -> (label, how well it fits an oral pre-cancer referral: higher is better)
CATEGORIES = {
    "dental_college": ("Dental college / oral medicine", 100),
    "cancer_centre": ("Cancer centre", 95),
    "medical_college": ("Medical college hospital", 85),
    "government_hospital": ("Government hospital", 70),
    "dentist": ("Dental clinic", 55),
    "hospital": ("Hospital", 45),
    "clinic": ("Clinic", 20),
    "primary_care": ("Primary health centre", 15),
}
_EXCLUDE = re.compile(r"ayurved|homoeo|homeo|unani|siddha|naturopath|veterinar|animal|eye|nethra|netra|optical|"
                      r"maternity|nursing home for women|physiotherap|psychiatr|de-?addiction|hostel|"
                      r"nursing college|college of nursing|school|pharmacy|medical store|laborator|\blab\b|"
                      r"diagnostic|scan centre|scanning|blood bank|x-?ray", re.I)


def _categorize(tags: dict) -> str | None:
    name = (tags.get("name") or "").lower()
    amenity = tags.get("amenity") or tags.get("healthcare") or ""
    spec = (tags.get("healthcare:speciality") or "").lower()
    if _EXCLUDE.search(name) or re.search(r"ayurveda|homeopathy|ophthalmology|veterinary", spec):
        return None
    if re.search(r"dental (college|science)|institute of dental|oral (medicine|surgery|and maxillofacial)", name) \
            or "oral_surgery" in spec or "maxillofacial" in spec:
        return "dental_college"
    if re.search(r"cancer|oncolog|tumou?r", name) or "oncology" in spec:
        return "cancer_centre"
    if re.search(r"medical college|medical sciences|institute of medical|teaching hospital", name):
        return "medical_college"
    if amenity == "dentist" or "dental" in name or "dentist" in spec:
        return "dentist"
    if re.search(r"primary health|\bphc\b|sub ?cent|community health|\bchc\b", name):
        return "primary_care"
    gov = (tags.get("operator:type") or "").lower() in ("government", "public") or \
        re.search(r"government|govt|district hospital|taluk hospital|general hospital|wenlock", name)
    if amenity == "hospital":
        return "government_hospital" if gov else "hospital"
    if amenity == "clinic":
        return "clinic"
    return None


def _address(tags: dict) -> str | None:
    if tags.get("addr:full"):
        return tags["addr:full"]
    parts = [tags.get(k) for k in ("addr:housenumber", "addr:street", "addr:suburb", "addr:city", "addr:postcode")]
    return ", ".join(p for p in parts if p) or None


def haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


async def _redis():
    import redis.asyncio as aredis

    return aredis.from_url(get_settings().redis_url, socket_timeout=2)


async def _cache_get(key: str):
    try:
        r = await _redis()
        v = await r.get(key)
        await r.aclose()
        return json.loads(v) if v else None
    except Exception:  # noqa: BLE001 - cache is optional
        return None


async def _cache_set(key: str, value) -> None:
    try:
        r = await _redis()
        await r.set(key, json.dumps(value), ex=CACHE_S)
        await r.aclose()
    except Exception:  # noqa: BLE001
        pass


async def places_near(lat: float, lon: float, radius_km: int = 60) -> list[dict]:
    """Real health facilities around a point (cached per ~5 km grid cell)."""
    key = f"nearby:v2:{round(lat, 2)}:{round(lon, 2)}:{radius_km}"
    cached = await _cache_get(key)
    if cached is not None:
        return cached
    q = (f'[out:json][timeout:45];(nwr["amenity"~"^(hospital|clinic|dentist)$"](around:{radius_km * 1000},{lat},{lon});'
         f'nwr["healthcare"~"^(hospital|dentist)$"](around:{radius_km * 1000},{lat},{lon}););out center tags 800;')
    data = None

    async def ask(h, url):
        try:
            resp = await h.post(url, data={"data": q})
            if resp.status_code == 200:
                return resp.json()
            log.warning("overpass_busy", url=url, status=resp.status_code)
        except Exception as e:  # noqa: BLE001
            log.warning("overpass_failed", url=url, error=str(e)[:120])
        return None

    # ask every mirror at once and keep the first good answer (public servers are often busy)
    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": USER_AGENT}) as h:
        tasks = [asyncio.create_task(ask(h, u)) for u in OVERPASS_MIRRORS]
        for done in asyncio.as_completed(tasks):
            data = await done
            if data is not None:
                break
        for t in tasks:
            t.cancel()
    if data is None:
        raise RuntimeError("OpenStreetMap servers are busy - please try again in a minute")
    out, seen = [], set()
    for e in data.get("elements", []):
        tags = e.get("tags") or {}
        if not tags.get("name"):
            continue
        cat = _categorize(tags)
        if cat is None:
            continue
        plat = e.get("lat") or (e.get("center") or {}).get("lat")
        plon = e.get("lon") or (e.get("center") or {}).get("lon")
        if plat is None or plon is None:
            continue
        dedupe = (tags["name"].strip().lower(), round(plat, 3), round(plon, 3))
        if dedupe in seen:
            continue
        seen.add(dedupe)
        out.append({"osmId": f"{e['type']}/{e['id']}", "name": tags["name"].strip(), "lat": plat, "lon": plon,
                    "category": cat, "categoryLabel": CATEGORIES[cat][0], "fit": CATEGORIES[cat][1],
                    "address": _address(tags),
                    "phone": tags.get("phone") or tags.get("contact:phone"),
                    "openingHours": tags.get("opening_hours"),
                    "emergency": tags.get("emergency") == "yes",
                    "operator": tags.get("operator"),
                    "government": cat == "government_hospital" or (tags.get("operator:type") or "") in
                    ("government", "public")})
    await _cache_set(key, out)
    return out


async def travel_times(lat: float, lon: float, places: list[dict]) -> dict[str, dict]:
    """Road distance (km) and driving time (min) from the patient to each place, one OSRM 'table' request.
    Falls back to a straight-line estimate (marked estimated) when OSRM is unavailable."""
    result: dict[str, dict] = {}
    missing = []
    for p in places:
        c = await _cache_get(f"osrm:v1:{round(lat, 3)}:{round(lon, 3)}:{p['osmId']}")
        if c:
            result[p["osmId"]] = c
        else:
            missing.append(p)
    for i in range(0, len(missing), 80):                      # public OSRM: keep requests small
        chunk = missing[i:i + 80]
        coords = ";".join([f"{lon},{lat}"] + [f"{p['lon']},{p['lat']}" for p in chunk])
        url = f"{OSRM_URL}/table/v1/driving/{coords}?sources=0&annotations=duration,distance"
        try:
            async with httpx.AsyncClient(timeout=25, headers={"User-Agent": USER_AGENT}) as h:
                d = (await h.get(url)).json()
            for j, p in enumerate(chunk, start=1):
                dur, dist = d["durations"][0][j], d["distances"][0][j]
                if dur is None:
                    continue
                v = {"minutes": round(dur / 60), "km": round(dist / 1000, 1), "estimated": False}
                result[p["osmId"]] = v
                await _cache_set(f"osrm:v1:{round(lat, 3)}:{round(lon, 3)}:{p['osmId']}", v)
        except Exception as e:  # noqa: BLE001
            log.warning("osrm_failed", error=str(e)[:120])
    for p in places:
        if p["osmId"] not in result:
            km = haversine_km(lat, lon, p["lat"], p["lon"]) * 1.35
            result[p["osmId"]] = {"minutes": round(km / 30 * 60), "km": round(km, 1), "estimated": True}
    return result


async def route_line(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> list[list[float]] | None:
    """Road route for drawing on the map ([[lat, lon], ...])."""
    key = f"route:v1:{round(a_lat, 3)}:{round(a_lon, 3)}:{round(b_lat, 4)}:{round(b_lon, 4)}"
    cached = await _cache_get(key)
    if cached:
        return cached
    url = f"{OSRM_URL}/route/v1/driving/{a_lon},{a_lat};{b_lon},{b_lat}?overview=full&geometries=geojson"
    try:
        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": USER_AGENT}) as h:
            d = (await h.get(url)).json()
        line = [[c[1], c[0]] for c in d["routes"][0]["geometry"]["coordinates"]]
        await _cache_set(key, line)
        return line
    except Exception as e:  # noqa: BLE001
        log.warning("osrm_route_failed", error=str(e)[:120])
        return None
