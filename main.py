from fastapi import FastAPI, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
import os

from app.astrology.rules import RuleLibrary
from app.astrology.engine import compute_natal, compute_vimshottari_dasha_for_birth, current_transits, jd_from_datetime
from app.services.phrasing import phrase_prediction
from app.analytics.tracker import record_event_with_ga, query_summary

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")

app = FastAPI(title="Vedic Astrology — Production Demo")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

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
    return {"ok": True}

@app.post("/api/v1/predict")
def predict(b: BirthPayload, request: Request):
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
