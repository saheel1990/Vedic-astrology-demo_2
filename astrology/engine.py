# app/astrology/engine.py
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone
import math
import swisseph as sw

# ---------- helpers ----------

def _scalar(v) -> float:
    """Flatten nested tuples/lists from Swiss Ephemeris until a float."""
    while isinstance(v, (list, tuple)) and len(v) > 0:
        v = v[0]
    return float(v)

def jd_from_datetime(dt: datetime) -> float:
    ts = dt.timestamp()
    return ts / 86400.0 + 2440587.5

def datetime_from_jd(jd: float) -> datetime:
    ts = (jd - 2440587.5) * 86400.0
    return datetime.fromtimestamp(ts, tz=timezone.utc)

def normalize_deg(x) -> float:
    x = _scalar(x)
    x = x % 360.0
    if x < 0:
        x += 360.0
    return x

def sign_from_longitude(lon) -> str:
    lon = normalize_deg(lon)
    idx = int(math.floor(lon / 30.0))
    return [
        "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
        "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
    ][idx]

def nakshatra_index_and_fraction(moon_lon: float) -> Tuple[int, float, float]:
    span = 360.0 / 27.0
    moon_lon = normalize_deg(moon_lon)
    idx = int(math.floor(moon_lon / span))
    start = idx * span
    frac = (moon_lon - start) / span
    return idx, frac, span

# ---------- constants ----------

# Use SWIEPH ephemeris + speed for consistent return shape
FLAGS = sw.FLG_SWIEPH | sw.FLG_SPEED

PLANETS = {
    "sun": sw.SUN, "moon": sw.MOON, "mercury": sw.MERCURY, "venus": sw.VENUS,
    "mars": sw.MARS, "jupiter": sw.JUPITER, "saturn": sw.SATURN,
    "rahu": sw.MEAN_NODE, "ketu": sw.MEAN_NODE
}

VIM_DURATIONS_YEARS = {
    "ketu": 7.0, "venus": 20.0, "sun": 6.0, "moon": 10.0, "mars": 7.0,
    "rahu": 18.0, "jupiter": 16.0, "saturn": 19.0, "mercury": 17.0
}
VIM_SEQUENCE = ["ketu","venus","sun","moon","mars","rahu","jupiter","saturn","mercury"]

# ---------- dataclasses ----------

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

# ---------- core ----------

def compute_natal(birth) -> NatalContext:
    if not getattr(birth, "utc_iso", None):
        raise ValueError("birth.utc_iso is required (e.g., 1990-04-20T05:25:00+00:00)")
    if not hasattr(birth, "latitude") or not hasattr(birth, "longitude"):
        raise ValueError("birth.latitude and birth.longitude are required")

    dt_utc = datetime.fromisoformat(birth.utc_iso).astimezone(timezone.utc)
    jd_ut = jd_from_datetime(dt_utc)

    # Planets (force scalar)
    longs: Dict[str, float] = {}
    for name, const in PLANETS.items():
        if name == "ketu":
            rahu = sw.calc_ut(jd_ut, PLANETS["rahu"], FLAGS)   # may be nested
            rahu_lon = _scalar(rahu)
            longs["ketu"] = normalize_deg(rahu_lon + 180.0)
        else:
            pos = sw.calc_ut(jd_ut, const, FLAGS)
            lon = _scalar(pos)
            longs[name] = normalize_deg(lon)

    # Houses
    cusps_raw, _ascmc = sw.houses(jd_ut, float(birth.latitude), float(birth.longitude))
    cusps_list = list(cusps_raw)
    # Some builds return 13 elements (0..12) with dummy 0th; normalize to 12 cusps:
    if len(cusps_list) >= 13 and abs(cusps_list[0]) < 1e-9:
        cusps_vals = cusps_list[1:13]
    else:
        cusps_vals = cusps_list[:12]
    cusps = [normalize_deg(_scalar(c)) for c in cusps_vals]

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
    moon = sw.calc_ut(jd_ut, PLANETS["moon"], FLAGS)
    moon_lon = normalize_deg(_scalar(moon))
    nak_idx, frac, _ = nakshatra_index_and_fraction(moon_lon)
    lord = VIM_SEQUENCE[nakshatra_index := (nak_idx % 9)]
    remaining_years = VIM_DURATIONS_YEARS[lord] * (1.0 - frac)

    periods: List[DashaPeriod] = []
    ydays = 365.2425
    start = jd_ut - 1e-9
    end = start + remaining_years * ydays
    periods.append(DashaPeriod(lord, start, end, datetime_from_jd(start).isoformat(), datetime_from_jd(end).isoformat()))

    seq_idx = (VIM_SEQUENCE.index(lord) + 1) % len(VIM_SEQUENCE)
    cur = end
    max_jd = start + 120 * ydays
    while cur < max_jd:
        p = VIM_SEQUENCE[seq_idx % len(VIM_SEQUENCE)]
        nxt = cur + VIM_DURATIONS_YEARS[p] * ydays
        periods.append(DashaPeriod(p, cur, nxt, datetime_from_jd(cur).isoformat(), datetime_from_jd(nxt).isoformat()))
        cur = nxt
        seq_idx += 1

    maha = periods[0].planet if periods else None
    antara = periods[1].planet if len(periods) > 1 else None
    praty = periods[2].planet if len(periods) > 2 else None
    return DashaContext(maha, antara, praty, periods[0].start_iso, periods[0].end_iso, periods)

def current_transits(natal: NatalContext, as_of_dt: Optional[datetime] = None, orb_deg: float = 1.5) -> TransitContext:
    if as_of_dt is None:
        as_of_dt = datetime.now(timezone.utc)
    jd_ut = jd_from_datetime(as_of_dt)

    cur: Dict[str, float] = {}
    for name, const in PLANETS.items():
        if name == "ketu":
            r = sw.calc_ut(jd_ut, PLANETS["rahu"], FLAGS)
            cur["ketu"] = normalize_deg(_scalar(r) + 180.0)
        else:
            cur[name] = normalize_deg(_scalar(sw.calc_ut(jd_ut, const, FLAGS)))

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
            tgt = abs(((j - lord_lon) - ang + 360.0) % 360.0)
            if tgt <= orb_deg or abs(tgt - 360.0) <= orb_deg:
                flag = True
                break
    active["jupiter_aspecting_10th_lord"] = flag

    return TransitContext(active=active)
