# app/astrology/engine.py
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone
import math
import swisseph as sw

# --------------------------
# Helpers & constants
# --------------------------

def _scalar(v) -> float:
    """Swiss Ephemeris often returns (value, speed, ...). We only want the first value as float."""
    if isinstance(v, (list, tuple)):
        v = v[0]
    return float(v)

def jd_from_datetime(dt: datetime) -> float:
    ts = dt.timestamp()
    return ts / 86400.0 + 2440587.5

def datetime_from_jd(jd: float) -> datetime:
    ts = (jd - 2440587.5) * 86400.0
    return datetime.fromtimestamp(ts, tz=timezone.utc)

def normalize_deg(x: float) -> float:
    x = _scalar(x)
    x = x % 360.0
    if x < 0:
        x += 360.0
    return x

def sign_from_longitude(lon: float) -> str:
    lon = normalize_deg(lon)
    sign_index = int(math.floor(lon / 30.0))
    signs = [
        "Aries","Taurus","Gemini","Cancer","Leo","Virgo",
        "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"
    ]
    return signs[sign_index]

def nakshatra_index_and_fraction(moon_lon: float) -> Tuple[int, float, float]:
    """27 nakshatras, each 13°20' (13.333... deg)"""
    span = 360.0 / 27.0
    moon_lon = normalize_deg(moon_lon)
    idx = int(math.floor(moon_lon / span))  # 0..26
    start = idx * span
    frac = (moon_lon - start) / span
    return idx, frac, span

PLANETS = {
    "sun": sw.SUN,
    "moon": sw.MOON,
    "mercury": sw.MERCURY,
    "venus": sw.VENUS,
    "mars": sw.MARS,
    "jupiter": sw.JUPITER,
    "saturn": sw.SATURN,
    "rahu": sw.MEAN_NODE,   # mean node
    "ketu": sw.MEAN_NODE    # computed as rahu + 180
}

VIM_DURATIONS_YEARS = {
    "ketu": 7.0, "venus": 20.0, "sun": 6.0, "moon": 10.0, "mars": 7.0,
    "rahu": 18.0, "jupiter": 16.0, "saturn": 19.0, "mercury": 17.0
}
VIM_SEQUENCE = ["ketu","venus","sun","moon","mars","rahu","jupiter","saturn","mercury"]

# --------------------------
# Data classes
# --------------------------

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

# --------------------------
# Core calculations
# --------------------------

def compute_natal(birth) -> NatalContext:
    """
    birth must have:
      - utc_iso: ISO datetime string with timezone (UTC recommended)
      - latitude: float
      - longitude: float
    """
    if not hasattr(birth, "utc_iso") or not birth.utc_iso:
        raise ValueError("birth.utc_iso is required (e.g., 1990-04-20T05:25:00+00:00)")
    if not hasattr(birth, "latitude") or not hasattr(birth, "longitude"):
        raise ValueError("birth.latitude and birth.longitude are required")

    dt_utc = datetime.fromisoformat(birth.utc_iso).astimezone(timezone.utc)
    jd_ut = jd_from_datetime(dt_utc)

    # Planet longitudes
    longs: Dict[str, float] = {}
    for name, const in PLANETS.items():
        if name == "ketu":
            rahu_lon = _scalar(sw.calc_ut(jd_ut, PLANETS["rahu"]))
            longs["ketu"] = normalize_deg(rahu_lon + 180.0)
        else:
            lonp = _scalar(sw.calc_ut(jd_ut, const))
            longs[name] = normalize_deg(lonp)

    # Houses: sw.houses returns (cusps, ascmc)
    cusps, _ascmc = sw.houses(jd_ut, float(birth.latitude), float(birth.longitude))
    # cusps is a sequence of 12 floats (1..12 house cusps in ecliptic longitude)
    asc_deg = normalize_deg(_scalar(cusps[0]))
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
    """Build Vimśottarī mahadasha chain starting at birth."""
    moon_lon = normalize_deg(_scalar(sw.calc_ut(jd_ut, PLANETS["moon"])))
    nak_idx, frac, _ = nakshatra_index_and_fraction(moon_lon)
    lord = VIM_SEQUENCE[nak_idx % 9]
    remaining_years = VIM_DURATIONS_YEARS[lord] * (1.0 - frac)

    periods: List[DashaPeriod] = []
    ydays = 365.2425
    start = jd_ut - 1e-9
    end = start + remaining_years * ydays
    periods.append(DashaPeriod(
        planet=lord,
        start_jd=start,
        end_jd=end,
        start_iso=datetime_from_jd(start).isoformat(),
        end_iso=datetime_from_jd(end).isoformat()
    ))

    seq_idx = (VIM_SEQUENCE.index(lord) + 1) % len(VIM_SEQUENCE)
    cur = end
    max_jd = start + 120 * ydays
    while cur < max_jd:
        p = VIM_SEQUENCE[seq_idx % len(VIM_SEQUENCE)]
        nxt = cur + VIM_DURATIONS_YEARS[p] * ydays
        periods.append(DashaPeriod(
            planet=p,
            start_jd=cur,
            end_jd=nxt,
            start_iso=datetime_from_jd(cur).isoformat(),
            end_iso=datetime_from_jd(nxt).isoformat()
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

def current_transits(natal: NatalContext, as_of_dt: Optional[datetime] = None, orb_deg: float = 1.5) -> TransitContext:
    if as_of_dt is None:
        as_of_dt = datetime.now(timezone.utc)
    jd_ut = jd_from_datetime(as_of_dt)

    cur: Dict[str, float] = {}
    for name, const in PLANETS.items():
        if name == "ketu":
            r = _scalar(sw.calc_ut(jd_ut, PLANETS["rahu"]))
            cur["ketu"] = normalize_deg(r + 180.0)
        else:
            cur[name] = normalize_deg(_scalar(sw.calc_ut(jd_ut, const)))

    active: Dict[str, Any] = {}

    # Example triggers aligned with your rulebook
    venus_sign = sign_from_longitude(cur["venus"])
    sat_sign = sign_from_longitude(cur["saturn"])
    active["venus_transit_7th"] = (venus_sign == natal.house_map.get("7"))
    active["saturn_in_10th"] = (sat_sign == natal.house_map.get("10"))

    # Jupiter aspecting 10th lord (0/120/240 within orb)
    rulers = {
        "Aries": "mars", "Taurus": "venus", "Gemini": "mercury", "Cancer": "moon",
        "Leo": "sun", "Virgo": "mercury", "Libra": "venus", "Scorpio": "mars",
        "Sagittarius": "jupiter", "Capricorn": "saturn", "Aquarius": "saturn", "Pisces": "jupiter"
    }
    tenth_sign = natal.house_map.get("10", "")
    tenth_lord = rulers.get(tenth_sign)
    flag = False
    if tenth_lord and tenth_lord in natal.planet_longitudes:
        j = cur["jupiter"]
        lord_lon = natal.planet_longitudes[tenth_lord]
        for ang in (0, 120, 240):
            # distance from target angle between Jupiter and lord
            tgt = abs(((j - lord_lon) - ang + 360.0) % 360.0)
            if tgt <= orb_deg or abs(tgt - 360.0) <= orb_deg:
                flag = True
                break
    active["jupiter_aspecting_10th_lord"] = flag

    return TransitContext(active=active)
