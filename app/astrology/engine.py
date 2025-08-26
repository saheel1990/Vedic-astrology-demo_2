# app/astrology/engine.py

from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone
import math
import swisseph as sw

# ───────────── Swiss Ephemeris config (KP ayanāṃśa, Moshier mode) ─────────────
FLAGS = sw.FLG_MOSEPH | sw.FLG_SPEED | sw.FLG_SIDEREAL
sw.set_sid_mode(sw.SIDM_KP)

# ───────────── Helpers ─────────────

def _scalar(v) -> float:
    """Flatten nested tuples/lists until a float."""
    while isinstance(v, (list, tuple)):
        v = v[0]
    return float(v)

def jd_from_datetime(dt: datetime) -> float:
    return dt.timestamp() / 86400.0 + 2440587.5

def datetime_from_jd(jd: float) -> datetime:
    ts = (jd - 2440587.5) * 86400.0
    return datetime.fromtimestamp(ts, tz=timezone.utc)

def normalize_deg(x) -> float:
    x = _scalar(x) % 360.0
    return x + 360.0 if x < 0 else x

SIGNS = [
    "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
    "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
]

def sign_from_longitude(lon) -> str:
    lon = normalize_deg(lon)
    return SIGNS[int(math.floor(lon / 30.0))]

def calc_lon(jd_ut: float, body: int) -> float:
    """Sidereal ecliptic longitude (0..360) for body, KP ayanāṃśa."""
    lon = _scalar(sw.calc_ut(jd_ut, body, FLAGS))
    return normalize_deg(lon)

def nakshatra_index_and_fraction(moon_lon: float) -> Tuple[int, float, float]:
    span = 360.0 / 27.0
    moon_lon = normalize_deg(moon_lon)
    idx = int(math.floor(moon_lon / span))             # 0..26
    start = idx * span
    frac = (moon_lon - start) / span                   # 0..1 within that nakshatra
    return idx, frac, span

# ───────────── Constants ─────────────

PLANETS = {
    "sun": sw.SUN, "moon": sw.MOON, "mercury": sw.MERCURY, "venus": sw.VENUS,
    "mars": sw.MARS, "jupiter": sw.JUPITER, "saturn": sw.SATURN,
    "rahu": sw.MEAN_NODE, "ketu": sw.MEAN_NODE  # ketu as 180° from rahu
}

VIM_SEQUENCE = ["ketu","venus","sun","moon","mars","rahu","jupiter","saturn","mercury"]
VIM_DURATIONS_YEARS = {
    "ketu": 7.0, "venus": 20.0, "sun": 6.0, "moon": 10.0, "mars": 7.0,
    "rahu": 18.0, "jupiter": 16.0, "saturn": 19.0, "mercury": 17.0
}
VIM_TOTAL = 120.0
ENGINE_VERSION = "kp-ephem-1.0"

# ───────────── Data classes ─────────────

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

# ───────────── Core calculations ─────────────

def compute_natal(birth) -> NatalContext:
    """
    birth must include:
      - utc_iso: ISO datetime string (with tz, e.g. 1990-04-20T05:25:00+00:00)
      - latitude: float
      - longitude: float
    """
    if not getattr(birth, "utc_iso", None):
        raise ValueError("birth.utc_iso is required")
    if not hasattr(birth, "latitude") or not hasattr(birth, "longitude"):
        raise ValueError("birth.latitude and birth.longitude are required")

    dt_utc = datetime.fromisoformat(birth.utc_iso).astimezone(timezone.utc)
    jd_ut = jd_from_datetime(dt_utc)

    # Planets (sidereal KP)
    longs: Dict[str, float] = {}
    for name, const in PLANETS.items():
        if name == "ketu":
            rahu_lon = calc_lon(jd_ut, PLANETS["rahu"])
            longs["ketu"] = (rahu_lon + 180.0) % 360.0
        else:
            longs[name] = calc_lon(jd_ut, const)

    # Houses
    cusps_raw, _ascmc = sw.houses(jd_ut, float(birth.latitude), float(birth.longitude))
    cusps_list = list(cusps_raw)
    if len(cusps_list) >= 13 and abs(cusps_list[0]) < 1e-9:
        cusps_vals = cusps_list[1:13]
    else:
        cusps_vals = cusps_list[:12]
    cusps = [normalize_deg(x) for x in cusps_vals]

    asc_deg = cusps[0]
    house_map = {str(i + 1): sign_from_longitude(cusps[i]) for i in range(12)}
    moon_sign = sign_from_longitude(longs["moon"])

    return NatalContext(
        utc_birth_dt=dt_utc,
        latitude=float(birth.latitude),
        longitude=float(birth.longitude),
        ascendant_deg=asc_deg,
        moon_sign=moon_sign,
        planet_longitudes=longs,
        house_map=house_map
    )

def compute_vimshottari_dasha_for_birth(jd_ut: float) -> DashaContext:
    """
    KP-style Vimshottari:
      - Start from Moon’s nakshatra fraction.
      - First Maha = remaining slice only.
      - Then roll through ~120 years.
    """
    moon_lon = calc_lon(jd_ut, PLANETS["moon"])
    nak_idx, frac, _ = nakshatra_index_and_fraction(moon_lon)
    lord = VIM_SEQUENCE[nak_idx % 9]
    remaining_years = VIM_DURATIONS_YEARS[lord] * (1.0 - frac)

    periods: List[DashaPeriod] = []
    ydays = 365.2425
    start = jd_ut
    end = start + remaining_years * ydays
    periods.append(DashaPeriod(
        planet=lord,
        start_jd=start,
        end_jd=end,
        start_iso=datetime_from_jd(start).isoformat(),
        end_iso=datetime_from_jd(end).isoformat(),
    ))

    seq_idx = (VIM_SEQUENCE.index(lord) + 1) % len(VIM_SEQUENCE)
    cur = end
    max_jd = start + 120.0 * ydays + 1.0
    while cur < max_jd:
        p = VIM_SEQUENCE[seq_idx % len(VIM_SEQUENCE)]
        nxt = cur + VIM_DURATIONS_YEARS[p] * ydays
        periods.append(DashaPeriod(
            planet=p,
            start_jd=cur,
            end_jd=nxt,
            start_iso=datetime_from_jd(cur).isoformat(),
            end_iso=datetime_from_jd(nxt).isoformat(),
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

def subdivide_vimshottari(dasha_ctx, levels: int = 2):
    """Split Maha into Antara (and Pratyantara) with Vimshottari ratios."""
    out: List[Dict[str, Any]] = []

    def add_block(level, lord, start_jd, end_jd, parent=None):
        out.append({
            "level": level,
            "lord": lord,
            "parent": parent,
            "start_jd": float(start_jd),
            "end_jd": float(end_jd),
            "start_iso": datetime_from_jd(start_jd).isoformat(),
            "end_iso": datetime_from_jd(end_jd).isoformat(),
        })

    for maha in getattr(dasha_ctx, "periods", []):
        m_lord = (maha.planet or "").lower()
        m_start, m_end = float(maha.start_jd), float(maha.end_jd)
        add_block("maha", m_lord, m_start, m_end, parent=None)
        if levels < 2:
            continue

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

        for a in [x for x in out if x["level"] == "antara" and x["parent"] == m_lord]:
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

def current_transits(natal: NatalContext, as_of_dt: Optional[datetime] = None, orb_deg: float = 1.5) -> TransitContext:
    if as_of_dt is None:
        as_of_dt = datetime.now(timezone.utc)
    jd_ut = jd_from_datetime(as_of_dt)

    cur: Dict[str, float] = {}
    for name, const in PLANETS.items():
        if name == "ketu":
            rahu_lon = calc_lon(jd_ut, PLANETS["rahu"])
            cur["ketu"] = (rahu_lon + 180.0) % 360.0
        else:
            cur[name] = calc_lon(jd_ut, const)

    active: Dict[str, Any] = {}
    venus_sign = sign_from_longitude(cur["venus"])
    sat_sign = sign_from_longitude(cur["saturn"])
    active["venus_transit_7th"] = (venus_sign == natal.house_map.get("7"))
    active["saturn_in_10th"] = (sat_sign == natal.house_map.get("10"))

    rulers = {
        "Aries": "mars","Taurus": "venus","Gemini": "mercury","Cancer": "moon",
        "Leo": "sun","Virgo": "mercury","Libra": "venus","Scorpio": "mars",
        "Sagittarius": "jupiter","Capricorn": "saturn","Aquarius": "saturn","Pisces": "jupiter"
    }
    tenth_sign = natal.house_map.get("10", "")
    tenth_lord = rulers.get(tenth_sign)
    flag = False
    if tenth_lord and tenth_lord in natal.planet_longitudes:
        j = cur["jupiter"]
        lord_lon = natal.planet_longitudes[tenth_lord]
        for ang in (0, 120, 240):
            delta = abs(((j - lord_lon) - ang + 360.0) % 360.0)
            if delta <= orb_deg or abs(delta - 360.0) <= orb_deg:
                flag = True
                break
    active["jupiter_aspecting_10th_lord"] = flag

    return TransitContext(active=active)
