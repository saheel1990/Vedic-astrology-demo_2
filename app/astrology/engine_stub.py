# app/astrology/engine_stub.py

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
import math, hashlib

ENGINE_VERSION = "stub-1.1"  # bumped

# -------------------------- Constants --------------------------

SIGNS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

VIM_SEQUENCE = ["ketu","venus","sun","moon","mars","rahu","jupiter","saturn","mercury"]
VIM_DURATIONS_YEARS = {
    "ketu": 7.0, "venus": 20.0, "sun": 6.0, "moon": 10.0, "mars": 7.0,
    "rahu": 18.0, "jupiter": 16.0, "saturn": 19.0, "mercury": 17.0
}
VIM_TOTAL = sum(VIM_DURATIONS_YEARS[p] for p in VIM_SEQUENCE)  # 120.0
YDAYS = 365.2425

# -------------------------- Data classes --------------------------

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

# -------------------------- Helpers --------------------------

def _datetime_from_jd(jd: float) -> datetime:
    ts = (jd - 2440587.5) * 86400.0
    return datetime.fromtimestamp(ts, tz=timezone.utc)

def _jd_from_datetime(dt: datetime) -> float:
    return dt.timestamp()/86400.0 + 2440587.5

def _norm(x: float) -> float:
    x = float(x) % 360.0
    return x + 360.0 if x < 0 else x

def _sign(lon: float) -> str:
    return SIGNS[int(math.floor(_norm(lon)/30.0))]

def _h(seed: str) -> float:
    # stable 0..1 hash for deterministic stub longs
    return (int(hashlib.sha256(seed.encode()).hexdigest(), 16) % 1_000_000) / 1_000_000.0

# -------------------------- Core stubs --------------------------

def compute_natal(birth) -> NatalContext:
    """
    Deterministic placeholder (no ephemeris). Keeps interface stable.
    """
    if not getattr(birth, "utc_iso", None):
        raise ValueError("birth.utc_iso required")
    if not hasattr(birth, "latitude") or not hasattr(birth, "longitude"):
        raise ValueError("latitude/longitude required")

    dt_utc = datetime.fromisoformat(birth.utc_iso).astimezone(timezone.utc)
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

    # fake houses/asc
    ascendant_deg = _norm((float(birth.longitude)*4.0 + (dt_utc.hour*15.0)))
    houses = [_norm(ascendant_deg + i*30.0) for i in range(12)]
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
    """
    Stubbed Vimshottari **with remaining first Mahadasha at birth**.
    This stops decade-long first windows starting at DOB.
    NOTE: This is a placeholder until real KP ayanamsa engine is enabled.
    """
    # --- Approximate nakshatra index & fraction deterministically from jd_ut ---
    # Map jd_ut into 27 nakshatras and a 0..1 fraction within the nakshatra.
    x = jd_ut * 27.0
    nak_idx = int(math.floor(x)) % 27
    frac_in_nak = x - math.floor(x)              # 0..1 within nakshatra

    start_dt = _datetime_from_jd(jd_ut)

    lord = VIM_SEQUENCE[nak_idx % 9]
    full_years = VIM_DURATIONS_YEARS[lord]
    remaining_years = max(0.0, full_years * (1.0 - frac_in_nak))  # remaining slice only

    periods: List[DashaPeriod] = []

    # First: remaining slice of the starting lord
    start = jd_ut
    end = start + remaining_years * YDAYS
    periods.append(DashaPeriod(
        planet=lord.title(),
        start_jd=start,
        end_jd=end,
        start_iso=_datetime_from_jd(start).isoformat(),
        end_iso=_datetime_from_jd(end).isoformat(),
    ))

    # Then: roll the rest with full durations
    seq_idx = (VIM_SEQUENCE.index(lord) + 1) % len(VIM_SEQUENCE)
    cur = end
    max_jd = start + 120.0 * YDAYS + 1.0  # full Vim cycle
    while cur < max_jd:
        p = VIM_SEQUENCE[seq_idx % len(VIM_SEQUENCE)]
        span = VIM_DURATIONS_YEARS[p] * YDAYS
        nxt = cur + span
        periods.append(DashaPeriod(
            planet=p.title(),
            start_jd=cur,
            end_jd=nxt,
            start_iso=_datetime_from_jd(cur).isoformat(),
            end_iso=_datetime_from_jd(nxt).isoformat(),
        ))
        cur = nxt
        seq_idx += 1

    maha = periods[0].planet if periods else None
    antara = periods[1].planet if len(periods) > 1 else None
    praty = periods[2].planet if len(periods) > 2 else None

    return DashaContext(
        maha=maha,
        antara=antara,
        pratyantara=praty,
        window_from=periods[0].start_iso,
        window_to=periods[0].end_iso,
        periods=periods
    )

# -------------------------- Subdivision (antara/pratyantara) --------------------------

def subdivide_vimshottari(dasha_ctx, levels: int = 2):
    """
    Return list of dicts for subperiods:
      [{"level":"antara"|"pratyantara"|"maha","lord":"venus","start_jd":...,"end_jd":...,
        "start_iso": "...", "end_iso":"...", "parent":"saturn"(optional)}]
    levels: 1 -> Maha only, 2 -> Antara within each Maha, 3 -> Pratyantara within each Antara
    """
    out: List[Dict[str, Any]] = []

    def add_block(level, lord, start_jd, end_jd, parent=None):
        out.append({
            "level": level,
            "lord": lord,
            "parent": parent,
            "start_jd": float(start_jd),
            "end_jd": float(end_jd),
            "start_iso": _datetime_from_jd(start_jd).isoformat(),
            "end_iso": _datetime_from_jd(end_jd).isoformat(),
        })

    for maha in getattr(dasha_ctx, "periods", []):
        m_lord = (maha.planet or "").lower()
        m_start, m_end = float(maha.start_jd), float(maha.end_jd)
        add_block("maha", m_lord, m_start, m_end, parent=None)
        if levels < 2:
            continue

        # Antara: split Maha proportionally (lord years / 120)
        m_len = m_end - m_start
        cursor = m_start
        for lord in VIM_SEQUENCE:
            frac = VIM_DURATIONS_YEARS[lord] / VIM_TOTAL
            span = m_len * frac
            a_start, a_end = cursor, min(cursor + span, m_end)
            add_block("antara", lord, a_start, a_end, parent=m_lord)
            cursor = a_end
            if cursor >= m_end - 1e-6:
                break

        if levels < 3:
            continue

        # Pratyantara: split each antara proportionally
        for a in [x for x in out if x["level"] == "antara" and x["parent"] == m_lord and m_start - 1e-6 <= x["start_jd"] <= m_end + 1e-6]:
            a_len = a["end_jd"] - a["start_jd"]
            cursor = a["start_jd"]
            for lord2 in VIM_SEQUENCE:
                frac2 = VIM_DURATIONS_YEARS[lord2] / VIM_TOTAL
                span2 = a_len * frac2
                p_start, p_end = cursor, min(cursor + span2, a["end_jd"])
                add_block("pratyantara", lord2, p_start, p_end, parent=a["lord"])
                cursor = p_end
                if cursor >= a["end_jd"] - 1e-6:
                    break

    return out

# -------------------------- Transits (stub triggers) --------------------------

def current_transits(natal: NatalContext, as_of: Optional[datetime]=None, orb: float=8.0) -> TransitContext:
    as_of = as_of or datetime.now(timezone.utc)
    day_shift = ((as_of - natal.utc_birth_dt).total_seconds()/86400.0) % 360.0

    cur = {k: _norm(v + day_shift*(1 + i*0.1)) for i,(k,v) in enumerate(natal.planet_longitudes.items())}

    active: Dict[str, Any] = {}
    # Example triggers matching your rulebook keys
    active["venus_transit_7th"] = (_sign(cur["venus"]) == natal.house_map.get("7"))
    active["saturn_in_10th"]    = (_sign(cur["saturn"]) == natal.house_map.get("10"))

    rulers = {
        "Aries":"mars","Taurus":"venus","Gemini":"mercury","Cancer":"moon","Leo":"sun",
        "Virgo":"mercury","Libra":"venus","Scorpio":"mars","Sagittarius":"jupiter",
        "Capricorn":"saturn","Aquarius":"saturn","Pisces":"jupiter"
    }
    tenth_lord = rulers.get(natal.house_map.get("10",""), "")
    flag = False
    if tenth_lord and tenth_lord in natal.planet_longitudes:
        j = cur["jupiter"]; lord = natal.planet_longitudes[tenth_lord]
        for ang in (0,120,240):
            d = abs(((j - lord) - ang + 360.0) % 360.0)
            if d <= orb or abs(d-360.0) <= orb:
                flag = True
                break
    active["jupiter_aspecting_10th_lord"] = flag

    return TransitContext(active=active)
