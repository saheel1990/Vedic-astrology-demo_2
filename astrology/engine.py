# app/astrology/engine.py  — DEMO STUB (no swisseph)
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
import math, hashlib

ENGINE_VERSION = "stub-1.0"  # <-- we’ll read this via /health

SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]

# ── Data classes ───────────────────────────────────────────
@dataclass
class NatalContext:
    utc_birth_dt: datetime
    latitude: float
    longitude: float
    ascendant_deg: float
    moon_sign: str
    planet_longitudes: Dict[str, float]
    house_map: Dict[str, str]

@dataclass
class DashaPeriod:
    planet: str
    start_jd: float
    end_jd: float
    start_iso: str
    end_iso: str

@dataclass
class DashaContext:
    maha: Optional[str]
    antara: Optional[str]
    pratyantara: Optional[str]
    window_from: str
    window_to: str
    periods: List[DashaPeriod]

@dataclass
class TransitContext:
    active: Dict[str, Any]

# ── Helpers ────────────────────────────────────────────────
def _norm(x: float) -> float:
    x = float(x)
    x = x % 360.0
    return x + 360.0 if x < 0 else x

def _sign(lon: float) -> str:
    return SIGNS[int(math.floor(_norm(lon)/30.0))]

def _jd(dt: datetime) -> float:
    # Clean float, no tuples
    return float(dt.timestamp()/86400.0 + 2440587.5)

def _h(seed: str) -> float:
    # deterministic 0..1
    return (int(hashlib.sha256(seed.encode()).hexdigest(), 16) % 1_000_000) / 1_000_000.0

# ── Core ───────────────────────────────────────────────────
def compute_natal(birth) -> NatalContext:
    if not getattr(birth, "utc_iso", None):
        raise ValueError("birth.utc_iso is required (e.g., 1990-04-20T05:25:00+00:00)")
    if not hasattr(birth, "latitude") or not hasattr(birth, "longitude"):
        raise ValueError("birth.latitude and birth.longitude are required")

    dt_utc = datetime.fromisoformat(birth.utc_iso).astimezone(timezone.utc)

    # Deterministic pseudo-longitudes (no external libs)
    seed = f"{dt_utc.isoformat()}|{float(birth.latitude):.4f}|{float(birth.longitude):.4f}"
    longs = {
        "sun":     _norm(  0 + 360*_h("sun|"+seed)),
        "moon":    _norm( 30 + 360*_h("moon|"+seed)),
        "mercury": _norm( 60 + 360*_h("mercury|"+seed)),
        "venus":   _norm( 90 + 360*_h("venus|"+seed)),
        "mars":    _norm(120 + 360*_h("mars|"+seed)),
        "jupiter": _norm(150 + 360*_h("jupiter|"+seed)),
        "saturn":  _norm(180 + 360*_h("saturn|"+seed)),
        "rahu":    _norm(210 + 360*_h("rahu|"+seed)),
    }
    longs["ketu"] = _norm(longs["rahu"] + 180.0)

    # Houses: simple twelve-sign wheel anchored on a fake ascendant
    ascendant_deg = _norm((float(birth.longitude)*4.0 + (dt_utc.hour*15.0)))
    houses = [ _norm(ascendant_deg + i*30.0) for i in range(12) ]
    house_map = {str(i+1): _sign(houses[i]) for i in range(12)}
    moon_sign = _sign(longs["moon"])

    return NatalContext(
        utc_birth_dt=dt_utc,
        latitude=float(birth.latitude),
        longitude=float(birth.longitude),
        ascendant_deg=ascendant_deg,
        moon_sign=moon_sign,
        planet_longitudes=longs,
        house_map=house_map
    )

def compute_vimshottari_dasha_for_birth(jd_ut: float) -> DashaContext:
    # Lightweight deterministic windows for demo
    start_dt = datetime.fromtimestamp((float(jd_ut) - 2440587.5)*86400.0, tz=timezone.utc)
    p1_end = start_dt + timedelta(days=3650)  # ~10y
    p2_end = p1_end + timedelta(days=3650)    # next ~10y
    p1 = DashaPeriod("Saturn", float(jd_ut), float(jd_ut)+3650, start_dt.isoformat(), p1_end.isoformat())
    p2 = DashaPeriod("Jupiter", float(jd_ut)+3650, float(jd_ut)+7300, p1_end.isoformat(), p2_end.isoformat())
    return DashaContext(maha="Saturn", antara="Jupiter", pratyantara="Mercury",
                        window_from=p1.start_iso, window_to=p1.end_iso, periods=[p1,p2])

def current_transits(natal: NatalContext, as_of: datetime|None=None, orb: float=8.0) -> TransitContext:
    as_of = as_of or datetime.now(timezone.utc)
    day_shift = ((as_of - natal.utc_birth_dt).total_seconds()/86400.0) % 360.0
    cur = { k: _norm(v + day_shift*(1 + i*0.1)) for i,(k,v) in enumerate(natal.planet_longitudes.items()) }

    active = {}
    active["venus_transit_7th"] = (_sign(cur["venus"]) == natal.house_map.get("7"))
    active["saturn_in_10th"]    = (_sign(cur["saturn"]) == natal.house_map.get("10"))

    rulers = {"Aries":"mars","Taurus":"venus","Gemini":"mercury","Cancer":"moon","Leo":"sun","Virgo":"mercury",
              "Libra":"venus","Scorpio":"mars","Sagittarius":"jupiter","Capricorn":"saturn","Aquarius":"saturn","Pisces":"jupiter"}
    tenth_lord = rulers.get(natal.house_map.get("10",""), "")
    flag = False
    if tenth_lord and tenth_lord in natal.planet_longitudes:
        j = cur["jupiter"]; lord = natal.planet_longitudes[tenth_lord]
        for ang in (0,120,240):
            d = abs(((j - lord) - ang + 360.0) % 360.0)
            if d <= orb or abs(d-360.0) <= orb:
                flag = True; break
    active["jupiter_aspecting_10th_lord"] = flag
    return TransitContext(active=active)
