# app/main.py
# top of app/main.py
try:
    from app.astrology.engine import subdivide_vimshottari
except ImportError:
    from app.astrology.engine_stub import subdivide_vimshottari  # use stub if real engine not present

from fastapi import FastAPI, Request, HTTPException, status, Form
from datetime import datetime, timezone
import calendar
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.astrology.engine import subdivide_vimshottari
import os

# Rules (Excel/CSV loader)
from app.astrology.rules import RuleLibrary

# ⬇️ FORCE the app to use the STUB engine only
from app.astrology.engine_stub import (
    compute_natal,
    compute_vimshottari_dasha_for_birth,
    current_transits,
    ENGINE_VERSION,  # for /health visibility
)

# Simple helper we previously imported from engine
def jd_from_datetime(dt: datetime) -> float:
    return dt.timestamp() / 86400.0 + 2440587.5

from app.services.phrasing import phrase_prediction
from app.analytics.tracker import record_event_with_ga, query_summary

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")

app = FastAPI(title="Vedic Astrology — Production Demo")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Load rules once on startup
rule_lib = RuleLibrary.load_default()

class BirthPayload(BaseModel):
    name: Optional[str] = None
    dob: str
    utc_iso: str
    latitude: float
    longitude: float
    tone: Optional[str] = "Friendly"

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index_v3.html", {"request": request})

@app.get("/health")
def health():
    # show which engine is running so we can verify the stub is active
    return {"ok": True, "engine": ENGINE_VERSION}

# quick debug to PROVE which module is in use
@app.get("/debug/engine")
def debug_engine():
    return {
        "compute_natal_module": compute_natal.__module__,
        "current_transits_module": current_transits.__module__,
    }

from fastapi.responses import JSONResponse
import hashlib, random

from datetime import datetime, timezone
import calendar

@app.post("/api/v1/predict_event")
def predict_event(b: EventPayload, request: Request):
    try:
        natal = compute_natal(b)
        jd = jd_from_datetime(natal.utc_birth_dt)
        dasha = compute_vimshottari_dasha_for_birth(jd)

        subs = subdivide_vimshottari(dasha, levels=3)
        now_iso = datetime.now(timezone.utc).isoformat()
        focus = [x.lower() for x in QUESTION_FOCUS.get(b.question, [])]

        future_praty = [s for s in subs if s["level"]=="pratyantara" and s["end_iso"] > now_iso]
        future_antara = [s for s in subs if s["level"]=="antara" and s["end_iso"] > now_iso]

        def pick(cands, want_focus=True):
            if want_focus and focus:
                filt = [x for x in cands if x["lord"].lower() in focus]
                if filt: return min(filt, key=lambda x: x["start_jd"])
            return min(cands, key=lambda x: x["start_jd"]) if cands else None

        chosen = pick(future_praty, True) or pick(future_antara, True) or pick(future_praty, False) or pick(future_antara, False)
        if not chosen:
            chosen = min([s for s in subs if s["level"]=="maha"], key=lambda x: x["start_jd"])

        ys = datetime.fromisoformat(chosen["start_iso"].replace("Z","+00:00")).year
        ms = datetime.fromisoformat(chosen["start_iso"].replace("Z","+00:00")).month
        ye = datetime.fromisoformat(chosen["end_iso"].replace("Z","+00:00")).year
        me = datetime.fromisoformat(chosen["end_iso"].replace("Z","+00:00")).month

        lord = chosen["lord"].title()
        qtxt = {"marriage":"marriage","child":"childbirth","promotion":"promotion","travel":"foreign travel"}.get(b.question,"event")
        summary = f"Likely window for {qtxt}: {calendar.month_name[ms]} {ys} – {calendar.month_name[me]} {ye} (sub-period lord: {lord})."

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

@app.get("/debug/rules")
def debug_rules():
    return {
        "count": len(rule_lib.rules),
        "first": [
            {"id": r.id, "theme": r.theme, "trigger": r.trigger, "message": r.message}
            for r in rule_lib.rules[:5]
        ],
    }


# ---- Admin analytics (password form) ----
@app.get("/admin/analytics", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "authed": False, "data": None})

@app.post("/admin/analytics", response_class=HTMLResponse)
def admin_dashboard_post(request: Request, password: str = Form(...)):
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    summary = query_summary()
    return templates.TemplateResponse("dashboard.html", {"request": request, "authed": True, "data": summary})

# --- Event prediction payload ---

class EventPayload(BaseModel):
    name: Optional[str] = None
    dob: str
    utc_iso: str
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    question: str  # "marriage" | "child" | "promotion" | "travel"
    tone: Optional[str] = "Friendly"
# --- Simple KP-flavoured mapping for demo windows ---
from datetime import timezone
import calendar

# app/main.py
QUESTION_FOCUS = {
    "marriage":  ["venus","jupiter","moon"],
    "child":     ["jupiter","venus","moon"],
    "promotion": ["saturn","jupiter","mercury","sun","mars"],
    "travel":    ["rahu","jupiter","mercury","moon"],
}

def _month_year_from_iso(iso_str: str):
    dt = datetime.fromisoformat(iso_str.replace("Z","+00:00"))
    return dt.year, dt.month

@app.post("/api/v1/predict_event")
def predict_event(b: EventPayload, request: Request):
    try:
        natal = compute_natal(b)
        jd = jd_from_datetime(natal.utc_birth_dt)
        dasha = compute_vimshottari_dasha_for_birth(jd)

        # NEW: use subperiods (Antara + Pratyantara), future only
        subs = subdivide_vimshottari(dasha, levels=3)  # requires import from engine
        now_iso = datetime.now(timezone.utc).isoformat()
        focus = [x.lower() for x in QUESTION_FOCUS.get(b.question, [])]

        # Prefer earliest future pratyantara with a focused lord; then antara; then any future subperiod
        future_praty = [s for s in subs if s["level"]=="pratyantara" and s["end_iso"] > now_iso]
        future_antara = [s for s in subs if s["level"]=="antara" and s["end_iso"] > now_iso]

        def pick(cands, want_focus=True):
            if want_focus and focus:
                c = [x for x in cands if x["lord"].lower() in focus]
                if c: return min(c, key=lambda x: x["start_jd"])
            return min(cands, key=lambda x: x["start_jd"]) if cands else None

        chosen = pick(future_praty, True) or pick(future_antara, True) or pick(future_praty, False) or pick(future_antara, False)
        if not chosen:
            # fallback: next maha window
            chosen = min([s for s in subs if s["level"]=="maha"], key=lambda x: x["start_jd"])

        ys, ms = _month_year_from_iso(chosen["start_iso"])
        ye, me = _month_year_from_iso(chosen["end_iso"])
        lord = chosen["lord"].title()

        qtxt = {
            "marriage":  "marriage",
            "child":     "childbirth",
            "promotion": "promotion",
            "travel":    "foreign travel",
        }.get(b.question, "event")

        # Clamp summary to a crisp month-year window
        import calendar
        summary = f"Likely window for {qtxt}: {calendar.month_name[ms]} {ys} – {calendar.month_name[me]} {ye} (sub-period lord: {lord})."

        record_event_with_ga("event_prediction", {"q": b.question, "ip": request.client.host, "lord": lord})

        return {
            "question": b.question,
            "window_start": chosen["start_iso"],
            "window_end": chosen["end_iso"],
            "likely_month_year": {"from": {"year": ys, "month": ms}, "to": {"year": ye, "month": me}},
            "level": chosen["level"],
            "dasha_lord": lord,
            "summary": summary
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)



