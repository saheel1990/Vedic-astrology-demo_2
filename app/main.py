# app/main.py

# ---- Prefer real KP engine; fall back to stub if import fails ----
try:
    from app.astrology.engine import (
        compute_natal,
        compute_vimshottari_dasha_for_birth,
        current_transits,
        subdivide_vimshottari,
        ENGINE_VERSION,
        jd_from_datetime,
        compute_csl_for_houses,     # NEW
        planet_significators,       # NEW
    )
except Exception:
    from app.astrology.engine_stub import (
        compute_natal,
        compute_vimshottari_dasha_for_birth,
        current_transits,
        subdivide_vimshottari,
        ENGINE_VERSION,
    )
    from datetime import datetime as _DT
    def jd_from_datetime(dt: _DT) -> float:
        return dt.timestamp() / 86400.0 + 2440587.5
    # Stub: fallbacks for debug routes
    def compute_csl_for_houses(n): return {str(i): "venus" for i in range(1,13)}
    def planet_significators(n): return {}


from fastapi import FastAPI, Request, HTTPException, status, Form
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import calendar
import importlib, traceback, os

# ---- Rules / phrasing / analytics ----
from app.astrology.rules import RuleLibrary
from app.services.phrasing import phrase_prediction
from app.analytics.tracker import record_event_with_ga, query_summary

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")

app = FastAPI(title="Vedic Astrology — Production Demo")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ---- Load rules once ----
rule_lib = RuleLibrary.load_default()

# =========================
# Models
# =========================

class BirthPayload(BaseModel):
    name: Optional[str] = None
    dob: str
    # Provide either utc_iso OR (local_iso + tz)
    utc_iso: Optional[str] = None
    local_iso: Optional[str] = None
    tz: Optional[str] = None
    latitude: float
    longitude: float
    tone: Optional[str] = "Friendly"

# in EventPayload (replace your existing class)
class EventPayload(BaseModel):
    name: Optional[str] = None
    dob: str
    utc_iso: Optional[str] = None
    local_iso: Optional[str] = None
    tz: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    question: str  # "marriage" | "child" | "promotion" | "travel"
    tone: Optional[str] = "Friendly"

    # NEW: selection controls
    direction: Optional[str] = "future"   # "future" | "past" | "nearest"
    anchor_iso: Optional[str] = None      # ISO date to center search around (UTC or with offset)


# =========================
# Helpers
# =========================

def normalize_utc_iso(payload) -> str:
    """
    Return a UTC ISO string using either:
      - payload.utc_iso (already has offset), or
      - payload.local_iso + payload.tz
    """
    if getattr(payload, "utc_iso", None):
        return payload.utc_iso

    if getattr(payload, "local_iso", None):
        tzname = getattr(payload, "tz", None) or "UTC"
        dt_local = datetime.fromisoformat(payload.local_iso)
        # If the local string had no tzinfo, apply tz; else respect provided offset
        if dt_local.tzinfo is None:
            try:
                dt_local = dt_local.replace(tzinfo=ZoneInfo(tzname))
            except Exception:
                raise HTTPException(status_code=400, detail=f"Unknown timezone: {tzname}")
        return dt_local.astimezone(timezone.utc).isoformat()

    raise HTTPException(status_code=400, detail="Provide either utc_iso or (local_iso + tz)")

# KP-flavoured preferences
QUESTION_FOCUS = {
    "marriage":  ["venus","jupiter","moon"],
    "child":     ["jupiter","venus","moon"],
    "promotion": ["saturn","jupiter","mercury","sun","mars"],
    "travel":    ["rahu","jupiter","mercury","moon"],
}

# Minimum plausible ages (years) per question
AGE_MIN = {
    "marriage": 18.0,
    "child":    20.0,
    "promotion":21.0,
    "travel":   12.0,
}

def age_years_at_jd(birth_jd: float, jd: float) -> float:
    return max(0.0, (jd - birth_jd) / 365.2425)

# House rulers (sidereal) by sign
RULERS = {
    "Aries":"mars","Taurus":"venus","Gemini":"mercury","Cancer":"moon","Leo":"sun",
    "Virgo":"mercury","Libra":"venus","Scorpio":"mars","Sagittarius":"jupiter",
    "Capricorn":"saturn","Aquarius":"saturn","Pisces":"jupiter"
}

# Houses of interest per question
QUESTION_HOUSES = {
    "marriage":  ["7","2","11"],
    "child":     ["5","2","9"],
    "promotion": ["10","11","2","6"],
    "travel":    ["9","12","3"],
}

def natal_house_sign(natal, house_no: str) -> Optional[str]:
    return natal.house_map.get(house_no)

def house_lord(natal, house_no: str) -> Optional[str]:
    sign = natal_house_sign(natal, house_no)
    return RULERS.get(sign) if sign else None

def angle_diff(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)

def planet_lon(natal, name: str) -> Optional[float]:
    return natal.planet_longitudes.get(name)

def soft_aspect_score(a_deg: float, b_deg: float, orb: float = 6.0) -> float:
    """
    Light heuristic: give a small bonus if near 0/60/90/120/180.
    Returns 0..1.
    """
    targets = [0, 60, 90, 120, 180]
    best = 0.0
    for g in targets:
        d = abs(((a_deg - b_deg) - g + 360.0) % 360.0)
        d = min(d, 360.0 - d)
        if d <= orb:
            best = max(best, 1.0 - d/orb)
    return best

def score_subperiod(natal, sub, question: str) -> float:
    """
    KP-flavoured DBA scoring:
      - Use planet significators (star-lord, own, sign-lord weights).
      - For the subperiod's lord (and optionally its parent/maha) aggregate support
        for the target houses, subtract opposing houses.
      - Still keep a tiny preference for deeper periods.
    """
    TARGETS = {
        "marriage":  (["7","2","11"], ["1","6","10"]),
        "child":     (["5","2","11","9"], ["1","4","10"]),
        "promotion": (["10","11","2","6"], ["12","8"]),   # include 6 for service
        "travel":    (["12","9","3"], ["4","2"]),         # residence vs travel tensions
    }
    pos, neg = TARGETS.get((question or "").lower(), (["7","2","11"], ["1","6","10"]))

    sig = planet_significators(natal)

    # Consider the sub-lord; add small contributions from its parent and maha if present
    l_sub = sub["lord"].lower()
    l_par = (sub.get("parent") or "").lower()
    # try to find maha parent if present in our list (we can pass it in via subdivider, but here we keep it simple)

    def planet_score(pl: str, k: float) -> float:
        m = sig.get(pl, {})
        pos_s = sum(m.get(h, 0.0) for h in pos)
        neg_s = sum(m.get(h, 0.0) for h in neg)
        return k * (pos_s - 0.8 * neg_s)  # penalize negatives mildly

    score = 0.0
    score += planet_score(l_sub, 1.0)
    if l_par:
        score += planet_score(l_par, 0.4)

    # Tiny edge for deeper period
    score += {"pratyantara": 0.25, "antara": 0.12, "maha": 0.0}.get(sub["level"], 0.0)
    return score


# =========================
# Pages
# =========================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # Use your latest template (ensure this exists)
    # Fallback to index.html if you haven’t created index_v3.html
    tpl = "index_v3.html" if os.path.exists("app/templates/index_v3.html") else "index.html"
    return templates.TemplateResponse(tpl, {"request": request})

# =========================
# Health & debug
# =========================

@app.get("/health")
def health():
    """
    Health check showing which engine is active.
    """
    return {"ok": True, "engine": ENGINE_VERSION, "module": compute_natal.__module__}

@app.get("/debug/engine_import")
def debug_engine_import():
    try:
        mod = importlib.import_module("app.astrology.engine")
        return {"ok": True, "engine": getattr(mod, "ENGINE_VERSION", "unknown")}
    except Exception:
        return {"ok": False, "error": traceback.format_exc()}

@app.get("/debug/nakshatra")
def debug_nakshatra(utc_iso: str, lat: float = 0.0, lon: float = 0.0):
    """
    Example:
      /debug/nakshatra?utc_iso=1990-04-20T05:25:00+00:00&lat=16.7&lon=74.25
    """
    try:
        birth = type("B", (), {"utc_iso": utc_iso, "latitude": lat, "longitude": lon})()
        natal = compute_natal(birth)
        jd = jd_from_datetime(natal.utc_birth_dt)

        moon_lon = natal.planet_longitudes["moon"]
        span = 360.0 / 27.0
        idx = int(moon_lon // span)
        frac = (moon_lon - idx * span) / span
        nakshatras = [
            "Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra","Punarvasu",
            "Pushya","Ashlesha","Magha","Purva Phalguni","Uttara Phalguni","Hasta",
            "Chitra","Swati","Vishakha","Anuradha","Jyeshtha","Mula","Purva Ashadha",
            "Uttara Ashadha","Shravana","Dhanishta","Shatabhisha","Purva Bhadrapada",
            "Uttara Bhadrapada","Revati"
        ]
        nname = nakshatras[idx % 27]
        lord_seq = ["ketu","venus","sun","moon","mars","rahu","jupiter","saturn","mercury"]
        vims_years = {"ketu":7,"venus":20,"sun":6,"moon":10,"mars":7,"rahu":18,"jupiter":16,"saturn":19,"mercury":17}
        maha_lord = lord_seq[idx % 9]
        balance_years = vims_years[maha_lord] * (1.0 - frac)

        return {
            "moon_longitude": round(moon_lon, 4),
            "nakshatra_index": idx,
            "nakshatra_name": nname,
            "nakshatra_fraction": round(frac, 4),
            "maha_dasha_lord": maha_lord,
            "remaining_years_in_dasha": round(balance_years, 2),
            "engine": ENGINE_VERSION,
            "module": compute_natal.__module__,
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/debug/dasha")
def debug_dasha(utc_iso: str, lat: float, lon: float, levels: int = 2, limit: int = 12):
    birth = type("B", (), {"utc_iso": utc_iso, "latitude": lat, "longitude": lon})()
    natal = compute_natal(birth)
    jd = jd_from_datetime(natal.utc_birth_dt)
    dasha = compute_vimshottari_dasha_for_birth(jd)
    subs = subdivide_vimshottari(dasha, levels=levels)
    rows = [
        {"level": s["level"], "lord": s["lord"], "start": s["start_iso"], "end": s["end_iso"]}
        for s in subs[:max(1, limit)]
    ]
    return {"engine": ENGINE_VERSION, "rows": rows}

@app.get("/debug/calc")
def debug_calc(utc_iso: str, lat: float, lon: float, levels: int = 3, limit: int = 60, csv: bool = False):
    """
    /debug/calc?utc_iso=1990-04-20T05:25:00+00:00&lat=16.7&lon=74.25&levels=3&limit=30
    """
    try:
        birth = type("B", (), {"utc_iso": utc_iso, "latitude": lat, "longitude": lon})()
        natal = compute_natal(birth)
        jd = jd_from_datetime(natal.utc_birth_dt)
        dasha = compute_vimshottari_dasha_for_birth(jd)
        subs = subdivide_vimshottari(dasha, levels=levels)

        moon_lon = natal.planet_longitudes["moon"]
        span = 360.0 / 27.0
        nidx = int(moon_lon // span)
        nfrac = (moon_lon - nidx * span) / span
        nakshatras = [
            "Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra","Punarvasu",
            "Pushya","Ashlesha","Magha","Purva Phalguni","Uttara Phalguni","Hasta",
            "Chitra","Swati","Vishakha","Anuradha","Jyeshtha","Mula","Purva Ashadha",
            "Uttara Ashadha","Shravana","Dhanishta","Shatabhisha","Purva Bhadrapada",
            "Uttara Bhadrapada","Revati"
        ]
        nname = nakshatras[nidx % 27]
        lord_seq = ["ketu","venus","sun","moon","mars","rahu","jupiter","saturn","mercury"]
        vims_years = {"ketu":7,"venus":20,"sun":6,"moon":10,"mars":7,"rahu":18,"jupiter":16,"saturn":19,"mercury":17}
        maha_lord = lord_seq[nidx % 9]
        balance_years = vims_years[maha_lord] * (1.0 - nfrac)

        rows = [{"level": s["level"], "lord": s["lord"], "start": s["start_iso"], "end": s["end_iso"]}
                for s in subs[:max(1, limit)]]

        if csv:
            out = []
            out.append("moon_longitude,nakshatra_index,nakshatra_name,nakshatra_fraction,maha_dasha_lord,remaining_years")
            out.append(f'{round(moon_lon,4)},{nidx},{nname},{round(nfrac,4)},{maha_lord},{round(balance_years,2)}')
            out.append("")
            out.append("level,lord,start,end")
            for r in rows:
                out.append(f'{r["level"]},{r["lord"]},{r["start"]},{r["end"]}')
            return PlainTextResponse("\n".join(out))
        else:
            return {
                "engine": ENGINE_VERSION,
                "moon_longitude": round(moon_lon, 4),
                "nakshatra_index": nidx,
                "nakshatra_name": nname,
                "nakshatra_fraction": round(nfrac, 4),
                "maha_dasha_lord": maha_lord,
                "remaining_years_in_dasha": round(balance_years, 2),
                "rows": rows
            }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/debug/csl")
def debug_csl(utc_iso: str, lat: float, lon: float):
    birth = type("B", (), {"utc_iso": utc_iso, "latitude": lat, "longitude": lon})()
    natal = compute_natal(birth)
    csl = compute_csl_for_houses(natal)
    return {
        "engine": ENGINE_VERSION,
        "cusps_deg": [round(x, 4) for x in natal.house_cusps_deg],
        "csl": csl,
    }

@app.get("/debug/significators")
def debug_significators(utc_iso: str, lat: float, lon: float):
    birth = type("B", (), {"utc_iso": utc_iso, "latitude": lat, "longitude": lon})()
    natal = compute_natal(birth)
    sig = planet_significators(natal)
    # Show top 5 houses per planet for readability
    view = {}
    for p, fmap in sig.items():
        top = sorted(fmap.items(), key=lambda kv: -kv[1])[:5]
        view[p] = [{"house": h, "w": round(w, 2)} for h, w in top]
    return {"engine": ENGINE_VERSION, "top": view}


# =========================
# Core APIs
# =========================

@app.post("/api/v1/predict")
def predict(b: BirthPayload, request: Request):
    # Normalize time to UTC inside the request
    b.utc_iso = normalize_utc_iso(b)

    natal = compute_natal(b)
    jd = jd_from_datetime(natal.utc_birth_dt)
    dasha = compute_vimshottari_dasha_for_birth(jd)
    transits = current_transits(natal)

    fired = []
    for r in rule_lib.rules:
        if transits.active.get(r.trigger, False):
            r.date_from = dasha.window_from
            r.date_to = dasha.window_to
            fired.append(r)
    if not fired and rule_lib.rules:
        fd = rule_lib.rules[0]
        fd.date_from = dasha.window_from
        fd.date_to = dasha.window_to
        fired = [fd]

    phrased = [phrase_prediction(r, natal=natal, dasha=dasha, transits=transits, tone=b.tone) for r in fired]
    today = phrased[0]["message"] if phrased else "A calm day. Focus on basics."
    week = phrased[1]["message"] if len(phrased) > 1 else today
    key_dates = [{"from": r.date_from, "to": r.date_to, "theme": r.theme} for r in fired]
    record_event_with_ga("prediction_requested", {"tone": b.tone, "ip": request.client.host, "themes": [r.theme for r in fired]})
    return {"today": today, "week": week, "key_dates": key_dates, "dasha": {"maha": dasha.maha, "antara": dasha.antara}}

@app.post("/api/v1/predict_event")
def predict_event(b: EventPayload, request: Request):
    try:
        # Normalize time to UTC
        b.utc_iso = normalize_utc_iso(b)

        # Build natal & dasha
        natal = compute_natal(b)
        birth_jd = jd_from_datetime(natal.utc_birth_dt)
        dasha = compute_vimshottari_dasha_for_birth(birth_jd)
        subs = subdivide_vimshottari(dasha, levels=3)  # maha+antara+pratyantara

        # Anchor/date logic
        if b.anchor_iso:
            anchor_dt = datetime.fromisoformat(b.anchor_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
        else:
            anchor_dt = datetime.now(timezone.utc)
        anchor_iso = anchor_dt.isoformat()
        anchor_jd = jd_from_datetime(anchor_dt)
        direction = (b.direction or "future").lower()

        # Age floor
        min_age = AGE_MIN.get(b.question, 16.0)

        # Filter by direction
        if direction == "future":
            pool = [s for s in subs if s["end_iso"] > anchor_iso]
        elif direction == "past":
            pool = [s for s in subs if s["start_iso"] <= anchor_iso]
        else:  # "nearest"
            pool = subs[:]  # both sides

        # Apply age floor at start_jd (still fine for past validations)
        pool = [s for s in pool if age_years_at_jd(birth_jd, s["start_jd"]) >= min_age]

        if not pool:
            # last resort: drop age floor if nothing matches
            pool = [s for s in subs if (direction != "future" or s["end_iso"] > anchor_iso)]
            if not pool:
                pool = subs

        # Rank by KP score, then closeness to anchor (days)
        def days_from_anchor(sub):
            return abs(sub["start_jd"] - anchor_jd)

        ranked = sorted(
            pool,
            key=lambda s: (
                -score_subperiod(natal, s, b.question),
                days_from_anchor(s),
                s["start_jd"]
            )
        )

        # For a strict "past" request, prefer latest before anchor among top scored
        if direction == "past":
            # take best score among top 10, then latest by start_jd
            top_score = score_subperiod(natal, ranked[0], b.question) if ranked else -1e9
            close = [s for s in ranked if abs(score_subperiod(natal, s, b.question) - top_score) < 1e-6]
            chosen = max(close, key=lambda x: x["start_jd"]) if close else (ranked[0] if ranked else subs[0])
        else:
            chosen = ranked[0] if ranked else subs[0]

        # Format response
        def _ym(iso):
            dt = datetime.fromisoformat(iso.replace("Z","+00:00"))
            return dt.year, dt.month
        ys, ms = _ym(chosen["start_iso"])
        ye, me = _ym(chosen["end_iso"])
        lord = chosen["lord"].title()

        labels = {"marriage":"marriage","child":"childbirth","promotion":"promotion","travel":"foreign travel"}
        qtxt = labels.get(b.question, "event")
        summary = f"Likely window for {qtxt}: {calendar.month_name[ms]} {ys} – {calendar.month_name[me]} {ye} (sub-period lord: {lord})."

        record_event_with_ga("event_prediction", {
            "q": b.question, "dir": direction, "ip": request.client.host,
            "lord": lord, "min_age": min_age, "anchor": anchor_iso
        })

        return {
            "question": b.question,
            "window_start": chosen["start_iso"],
            "window_end": chosen["end_iso"],
            "likely_month_year": {"from":{"year":ys,"month":ms}, "to":{"year":ye,"month":me}},
            "level": chosen["level"],
            "dasha_lord": lord,
            "summary": summary
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# =========================
# Admin analytics
# =========================

@app.get("/admin/analytics", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "authed": False, "data": None})

@app.post("/admin/analytics", response_class=HTMLResponse)
def admin_dashboard_post(request: Request, password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    summary = query_summary()
    return templates.TemplateResponse("dashboard.html", {"request": request, "authed": True, "data": summary})
