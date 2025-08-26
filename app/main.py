# app/main.py

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

# ---- Engine: use STUB ONLY (no swiss ephemeris needed) ----
from app.astrology.engine_stub import (
    compute_natal,
    compute_vimshottari_dasha_for_birth,
    current_transits,
    subdivide_vimshottari,
    ENGINE_VERSION,  # visible in /health
)

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
    utc_iso: str
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    question: str  # "marriage" | "child" | "promotion" | "travel"
    tone: Optional[str] = "Friendly"


QUESTION_FOCUS: Dict[str, List[str]] = {
    "marriage":  ["venus", "jupiter", "moon"],
    "child":     ["jupiter", "venus", "moon"],
    "promotion": ["saturn", "jupiter", "mercury", "sun", "mars"],
    "travel":    ["rahu", "jupiter", "mercury", "moon"],
}


# --------------------------- Helpers ---------------------------

def jd_from_datetime(dt: datetime) -> float:
    # Julian Day from UTC datetime (no external deps)
    return dt.timestamp() / 86400.0 + 2440587.5

def _month_year_from_iso(iso_str: str):
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.year, dt.month


# --------------------------- Routes ---------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # Serve the v3 UI (with question dropdown + event button)
    return templates.TemplateResponse("index_v3.html", {"request": request})


@app.get("/health")
def health():
    # Show which engine is active
    return {"ok": True, "engine": ENGINE_VERSION}


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


@app.post("/api/v1/predict")
def predict(b: BirthPayload, request: Request):
    try:
        natal = compute_natal(b)
        jd = jd_from_datetime(natal.utc_birth_dt)
        dasha = compute_vimshottari_dasha_for_birth(jd)
        transits = current_transits(natal)

        # fire rules based on transit triggers
        fired = []
        for r in rule_lib.rules:
            if transits.active.get(r.trigger, False):
                r.date_from = dasha.window_from
                r.date_to = dasha.window_to
                fired.append(r)

        # fallback: at least one rule so UI shows something
        if not fired and rule_lib.rules:
            fd = rule_lib.rules[0]
            fd.date_from = dasha.window_from
            fd.date_to = dasha.window_to
            fired = [fd]

        phrased = [
            phrase_prediction(r, natal=natal, dasha=dasha, transits=transits, tone=b.tone)
            for r in fired
        ]

        today = phrased[0]["message"] if phrased else "A steady stretch—work the basics."
        week = phrased[1]["message"] if len(phrased) > 1 else today
        key_dates = [{"from": r.date_from, "to": r.date_to, "theme": r.theme} for r in fired]

        record_event_with_ga("prediction_requested", {
            "tone": b.tone, "ip": request.client.host, "themes": [r.theme for r in fired]
        })

        return {
            "today": today,
            "week": week,
            "key_dates": key_dates,
            "dasha": {"maha": dasha.maha, "antara": dasha.antara},
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
