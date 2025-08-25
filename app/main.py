# app/main.py
from fastapi import FastAPI, Request, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
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
    return templates.TemplateResponse("index.html", {"request": request})

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

@app.post("/api/v1/predict")
def predict(b: BirthPayload, request: Request):
    try:
        natal = compute_natal(b)
        jd = jd_from_datetime(natal.utc_birth_dt)
        dasha = compute_vimshottari_dasha_for_birth(jd)
        transits = current_transits(natal)

        # Fire rules
        fired = []
        for r in rule_lib.rules:
            if transits.active.get(r.trigger, False):
                r.date_from = dasha.window_from
                r.date_to = dasha.window_to
                fired.append(r)

        # Fallback if nothing fired
        if not fired and rule_lib.rules:
            fd = rule_lib.rules[0]
            fd.date_from = dasha.window_from
            fd.date_to = dasha.window_to
            fired = [fd]

        # Phrase messages
        phrased = [phrase_prediction(r, natal=natal, dasha=dasha, transits=transits, tone=b.tone) for r in fired]
        today = phrased[0]["message"] if phrased else "A calm day. Focus on basics."
        week = phrased[1]["message"] if len(phrased) > 1 else today
        key_dates = [{"from": r.date_from, "to": r.date_to, "theme": r.theme} for r in fired]

        # Analytics
        record_event_with_ga(
            "prediction_requested",
            {"tone": b.tone, "ip": request.client.host, "themes": [r.theme for r in fired]},
        )

        return {"today": today, "week": week, "key_dates": key_dates,
                "dasha": {"maha": dasha.maha, "antara": dasha.antara}}
    except Exception as e:
        # Always return JSON on error + show module in use
        return JSONResponse({"error": str(e), "engine_mod": compute_natal.__module__}, status_code=500)

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
