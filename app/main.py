# app/main.py
# ---- Load real KP engine first; fall back to stub if it fails ----
try:
    from app.astrology.engine import (
        compute_natal,
        compute_vimshottari_dasha_for_birth,
        current_transits,
        subdivide_vimshottari,
        ENGINE_VERSION,
        jd_from_datetime,
    )
except Exception as _engine_err:
    from app.astrology.engine_stub import (
        compute_natal,
        compute_vimshottari_dasha_for_birth,
        current_transits,
        subdivide_vimshottari,
        ENGINE_VERSION,
    )
    from datetime import datetime
    def jd_from_datetime(dt: datetime) -> float:
        return dt.timestamp() / 86400.0 + 2440587.5


from fastapi import FastAPI, Request, HTTPException, status, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import calendar
import os


# ---- Rules & phrasing / analytics ----
from app.astrology.rules import RuleLibrary
from app.services.phrasing import phrase_prediction
from app.analytics.tracker import record_event_with_ga, query_summary


# --------------------------- App setup ---------------------------

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")

app = FastAPI(title="Vedic Astrology — Production Demo")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Load rules once
rule_lib = RuleLibrary.load_default()


# --------------------------- Models ---------------------------

class BirthPayload(BaseModel):
    name: Optional[str] = None
    dob: str
    utc_iso: str
    latitude: float
    longitude: float
    tone: Optional[str] = "Friendly"


class EventPayload(BaseModel):
    name: Optional[str] = None
    dob: str
    # EITHER provide utc_iso, OR provide local_iso + tz
    utc_iso: Optional[str] = None
    local_iso: Optional[str] = None
    tz: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    question: str
    tone: Optional[str] = "Friendly"



QUESTION_FOCUS: Dict[str, List[str]] = {
    "marriage":  ["venus", "jupiter", "moon"],
    "child":     ["jupiter", "venus", "moon"],
    "promotion": ["saturn", "jupiter", "mercury", "sun", "mars"],
    "travel":    ["rahu", "jupiter", "mercury", "moon"],
}


# --------------------------- Helpers ---------------------------

def _month_year_from_iso(iso_str: str):
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.year, dt.month

def age_years_at_jd(birth_jd: float, jd: float) -> float:
    return max(0.0, (jd - birth_jd) / 365.2425)

AGE_MIN = {
    "marriage": 15.0,
    "child":    15.0,
    "promotion":18.0,
    "travel":   1.0,  # can be earlier; tweak as you like
}

def age_years_at_jd(birth_jd: float, jd: float) -> float:
    return max(0.0, (jd - birth_jd) / 365.2425)


# --------------------------- Routes ---------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # Serve the v3 UI (with question dropdown + event button)
    return templates.TemplateResponse("index_v3.html", {"request": request})


@app.get("/health")
def health():
    """
    Health check showing which engine is actually active.
    - engine: version string from ENGINE_VERSION
    - module: where compute_natal is being imported from
    """
    return {
        "ok": True,
        "engine": ENGINE_VERSION,
        "module": compute_natal.__module__,
    }

@app.get("/debug/nakshatra")
def debug_nakshatra(utc_iso: str, lat: float = 0.0, lon: float = 0.0):
    """
    Debug endpoint: show Moon longitude, nakshatra, and dasha balance for a given birth datetime.
    Example:
      /debug/nakshatra?utc_iso=1990-04-20T05:25:00+00:00&lat=16.7&lon=74.25
    """
    try:
        birth = type("B", (), {"utc_iso": utc_iso, "latitude": lat, "longitude": lon})()
        natal = compute_natal(birth)
        jd = jd_from_datetime(natal.utc_birth_dt)

        # Moon longitude
        moon_lon = natal.planet_longitudes["moon"]

        # Nakshatra details
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

        # Current maha lord from Moon nakshatra
        lord = VIM_SEQUENCE[idx % 9]
        balance = VIM_DURATIONS_YEARS[lord] * (1.0 - frac)

        return {
            "moon_longitude": round(moon_lon, 4),
            "nakshatra_index": idx,
            "nakshatra_name": nname,
            "nakshatra_fraction": round(frac, 4),
            "maha_dasha_lord": lord,
            "remaining_years_in_dasha": round(balance, 2),
            "engine": ENGINE_VERSION,
            "module": compute_natal.__module__,
        }
    except Exception as e:
        return {"error": str(e)}
@app.get("/debug/dasha")
def debug_dasha(utc_iso: str, lat: float, lon: float, levels: int = 2, limit: int = 12):
    birth = type("B", (), {"utc_iso": utc_iso, "latitude": lat, "longitude": lon})()
    from app.astrology.engine import compute_natal, compute_vimshottari_dasha_for_birth, jd_from_datetime, subdivide_vimshottari
    natal = compute_natal(birth)
    jd = jd_from_datetime(natal.utc_birth_dt)
    dasha = compute_vimshottari_dasha_for_birth(jd)
    subs = subdivide_vimshottari(dasha, levels=levels)
    rows = [
        {
            "level": s["level"],
            "lord": s["lord"],
            "start": s["start_iso"],
            "end": s["end_iso"],
        }
        for s in subs[:max(1, limit)]
    ]
    return {"engine": ENGINE_VERSION, "rows": rows}


@app.get("/debug/engine")
def debug_engine():
    return {
        "compute_natal_module": compute_natal.__module__,
        "current_transits_module": current_transits.__module__,
        "subdivider": subdivide_vimshottari.__module__,
    }


@app.get("/debug/rules")
def debug_rules():
    return {
        "count": len(rule_lib.rules),
        "first": [
            {"id": r.id, "theme": r.theme, "trigger": r.trigger, "message": r.message}
            for r in rule_lib.rules[:5]
        ],
    }

from zoneinfo import ZoneInfo

def ensure_utc_iso(b):
    if b.utc_iso:
        return b.utc_iso
    if b.local_iso:
        tzname = b.tz or "UTC"
        dt_local = datetime.fromisoformat(b.local_iso)
        if dt_local.tzinfo is None:
            dt_local = dt_local.replace(tzinfo=ZoneInfo(tzname))
        else:
            # if user provided offset, ignore tz field
            pass
        return dt_local.astimezone(timezone.utc).isoformat()
    raise ValueError("Provide either utc_iso or (local_iso + tz)")

# inside predict_event:
b.utc_iso = ensure_utc_iso(b)


@app.post("/api/v1/predict_event")
def predict_event(b: EventPayload, request: Request):
    try:
        natal = compute_natal(b)
        birth_jd = jd_from_datetime(natal.utc_birth_dt)
        dasha = compute_vimshottari_dasha_for_birth(birth_jd)

        subs = subdivide_vimshottari(dasha, levels=3)  # maha+antara+pratyantara
        now_iso = datetime.now(timezone.utc).isoformat()
        focus = [x.lower() for x in QUESTION_FOCUS.get(b.question, [])]
        min_age = AGE_MIN.get(b.question, 16.0)

        # future-only
        future = [s for s in subs if s["end_iso"] > now_iso]

        # enforce age floor at start_jd
        aged = [s for s in future if age_years_at_jd(birth_jd, s["start_jd"]) >= min_age]

        # 1) prefer focused pratyantara, 2) focused antara, 3) any pratyantara, 4) any antara, 5) next maha above age floor
        def pick(cands, wanted_focus=True, level=None):
            pool = [c for c in cands if (level is None or c["level"] == level)]
            if wanted_focus and focus:
                pool = [c for c in pool if c["lord"].lower() in focus]
            return min(pool, key=lambda x: x["start_jd"]) if pool else None

        chosen = (
            pick(aged, True, "pratyantara") or
            pick(aged, True, "antara") or
            pick(aged, False, "pratyantara") or
            pick(aged, False, "antara") or
            pick([c for c in aged if c["level"] == "maha"], False, None)
        )
        if not chosen:
            # absolute fallback: earliest future subperiod if age filters exclude everything
            chosen = min(future, key=lambda x: x["start_jd"])

        # format
        def _ym(iso):
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.year, dt.month
        ys, ms = _ym(chosen["start_iso"])
        ye, me = _ym(chosen["end_iso"])
        lord = chosen["lord"].title()
        labels = {"marriage":"marriage","child":"childbirth","promotion":"promotion","travel":"foreign travel"}
        qtxt = labels.get(b.question, "event")
        summary = f"Likely window for {qtxt}: {calendar.month_name[ms]} {ys} – {calendar.month_name[me]} {ye} (sub-period lord: {lord})."

        record_event_with_ga("event_prediction", {"q": b.question, "ip": request.client.host, "lord": lord, "min_age": min_age})

        return {
            "question": b.question,
            "window_start": chosen["start_iso"],
            "window_end": chosen["end_iso"],
            "likely_month_year": {"from":{"year":ys,"month":ms}, "to":{"year":ye,"month":me}},
            "level": chosen["level"],
            "dasha_lord": lord,
            "summary": summary
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/v1/predict_event")
def predict_event(b: EventPayload, request: Request):
    """
    Return a tight month–year window using Vimshottari sub-periods:
    prefer next future pratyantara/antara whose lord matches the question focus.
    """
    try:
        natal = compute_natal(b)
        jd = jd_from_datetime(natal.utc_birth_dt)
        dasha = compute_vimshottari_dasha_for_birth(jd)

        subs = subdivide_vimshottari(dasha, levels=3)  # maha + antara + pratyantara
        now_iso = datetime.now(timezone.utc).isoformat()
        focus = [x.lower() for x in QUESTION_FOCUS.get(b.question, [])]

        future_praty = [s for s in subs if s["level"] == "pratyantara" and s["end_iso"] > now_iso]
        future_antara = [s for s in subs if s["level"] == "antara"      and s["end_iso"] > now_iso]

        def pick(cands, want_focus=True):
            if want_focus and focus:
                filt = [x for x in cands if x["lord"].lower() in focus]
                if filt:
                    return min(filt, key=lambda x: x["start_jd"])
            return min(cands, key=lambda x: x["start_jd"]) if cands else None

        chosen = (
            pick(future_praty, True) or
            pick(future_antara, True) or
            pick(future_praty, False) or
            pick(future_antara, False)
        )
        if not chosen:
            # fallback: next/first maha
            maha_only = [s for s in subs if s["level"] == "maha"]
            chosen = min(maha_only, key=lambda x: x["start_jd"])

        ys, ms = _month_year_from_iso(chosen["start_iso"])
        ye, me = _month_year_from_iso(chosen["end_iso"])
        lord = chosen["lord"].title()

        qtxt = {
            "marriage":  "marriage",
            "child":     "childbirth",
            "promotion": "promotion",
            "travel":    "foreign travel",
        }.get(b.question, "event")

        summary = (
            f"Likely window for {qtxt}: "
            f"{calendar.month_name[ms]} {ys} – {calendar.month_name[me]} {ye} "
            f"(sub-period lord: {lord})."
        )

        record_event_with_ga("event_prediction", {"q": b.question, "ip": request.client.host, "lord": lord})

        return {
            "question": b.question,
            "window_start": chosen["start_iso"],
            "window_end": chosen["end_iso"],
            "likely_month_year": {
                "from": {"year": ys, "month": ms},
                "to":   {"year": ye, "month": me}
            },
            "level": chosen["level"],
            "dasha_lord": lord,
            "summary": summary
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

import importlib, traceback

@app.get("/debug/engine_import")
def debug_engine_import():
    try:
        mod = importlib.import_module("app.astrology.engine")
        return {"ok": True, "engine": getattr(mod, "ENGINE_VERSION", "unknown")}
    except Exception:
        return {"ok": False, "error": traceback.format_exc()}


# --------------------------- Admin (analytics) ---------------------------

@app.get("/admin/analytics", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "authed": False, "data": None}
    )

@app.post("/admin/analytics", response_class=HTMLResponse)
def admin_dashboard_post(request: Request, password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    summary = query_summary()
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "authed": True, "data": summary}
    )
