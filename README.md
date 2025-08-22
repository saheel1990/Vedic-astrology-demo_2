# Vedic Astrology App — Production Demo

This repo is ready to deploy on Render (or any Docker host).

## Features
- FastAPI backend with Swiss Ephemeris-based engine (validate before prod)
- 150+ natural prediction templates **baked in** (`app/data/Vedic_Astrology_Prediction_Rulebook_150+_Templates.xlsx`)
- Mobile-friendly frontend (Tailwind-like minimal CSS)
- Analytics: SQLite logger + GA4 Measurement Protocol
- Admin analytics dashboard at `/admin/analytics` (password-protected)

## Run locally
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

## Deploy to Render
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port 10000`
- Env Vars:
  - `GA4_MEASUREMENT_ID` (e.g., G-D5PVYPYZF3)
  - `GA4_API_SECRET` (your GA secret)
  - `ADMIN_PASSWORD` (e.g., saheel20050469620)

## Notes
- Engine uses pyswisseph. Ensure ephemeris files are accessible or rely on built-in calc. Validate results vs JHora before production use.
- Birth timezone conversion must be done client-side or add a timezone resolver service in the backend.
