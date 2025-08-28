# app/astrology/engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone, timedelta
import math

import swisseph as sw

# ───────────────────────── Config / constants ─────────────────────────

ENGINE_VERSION = "kp-ephem-1.0"

# --- Sidereal mode: KP (Krishnamurti); fall back if not present ---
try:
    KP_CONST = getattr(sw, "SIDM_KRISHNAMURTI", None) or getattr(sw, "SIDM_KP", None)
    if KP_CONST is None:
        # last-resort fallback so import never crashes
        KP_CONST = sw.SIDM_LAHIRI
    sw.set_sid_mode(KP_CONST)
except Exception as e:
    # Never crash on import; default to Lahiri if anything odd happens
    try:
        sw.set_sid_mode(sw.SIDM_LAHIRI)
    except Exception:
        pass


# Vimśottarī sequence (9 lords, 120 years total)
VIM_SEQUENCE = ["ketu", "venus", "sun", "moon", "mars", "rahu", "jupiter", "saturn", "mercury"]
VIM_DURATIONS_YEARS: Dict[str, float] = {
    "ketu": 7.0,
    "venus": 20.0,
    "sun": 6.0,
    "moon": 10.0,
    "mars": 7.0,
    "rahu": 18.0,
    "jupiter": 16.0,
    "saturn": 19.0,
    "mercury": 17.0,
}
VIM_TOTAL_YEARS = 120.0

# Planets: use Mean Node by default (toggle to TRUE_NODE if you want)
PLANETS = {
    "sun": sw.SUN,
    "moon": sw.MOON,
    "mercury": sw.MERCURY,
    "venus": sw.VENUS,
    "mars": sw.MARS,
    "jupiter": sw.JUPITER,
    "saturn": sw.SATURN,
    "rahu": sw.MEAN_NODE,
    "ketu": sw.MEAN_NODE,  # will be rahu + 180
}

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

RULERS = {
    "Aries": "mars", "Taurus": "venus", "Gemini": "mercury", "Cancer": "moon",
    "Leo": "sun", "Virgo": "mercury", "Libra": "venus", "Scorpio": "mars",
    "Sagittarius": "jupiter", "Capricorn": "saturn", "Aquarius": "saturn", "Pisces": "jupiter"
}

NAK_SPAN_DEG = 360.0 / 27.0  # 13°20'

# ───────────────────────── Utilities ─────────────────────────

def _scalar(v) -> float:
    """Flatten nested lists/tuples until a scalar; then to float."""
    while isinstance(v, (list, tuple)) and len(v) > 0:
        v = v[0]
    return float(v)

def normalize_deg(x) -> float:
    x = float(x) % 360.0
    return x + 360.0 if x < 0 else x

def sign_from_longitude(lon) -> str:
    lon = normalize_deg(lon)
    return SIGNS[int(math.floor(lon / 30.0))]

def jd_from_datetime(dt: datetime) -> float:
    return dt.timestamp() / 86400.0 + 2440587.5

def datetime_from_jd(jd: float) -> datetime:
    ts = (jd - 2440587.5) * 86400.0
    return datetime.fromtimestamp(ts, tz=timezone.utc)

def calc_lon(jd_ut: float, body: int) -> float:
    """Swiss Ephemeris ecliptic longitude (sidereal) 0..360."""
    pos = sw.calc_ut(jd_ut, body, FLAGS)
    return normalize_deg(_scalar(pos))

def _arc(a: float, b: float) -> float:
    """Forward arc a→b in [0,360)."""
    return (normalize_deg(b) - normalize_deg(a)) % 360.0

# ───────────────────────── KP: star-lord / sub-lord / houses ─────────────────────────

def star_lord_at(lon: float) -> str:
    """Nakshatra lord at longitude (sidereal)."""
    idx = int(normalize_deg(lon) // NAK_SPAN_DEG)
    return VIM_SEQUENCE[idx % 9]

def sub_lord_at(lon: float) -> str:
    """
    KP Sub-Lord inside a nakshatra:
    Split the 13°20' nakshatra by Vimśottarī proportions, BUT rotate the sequence
    so it starts at that nakshatra's star-lord (not always Ketu).
    """
    lon = normalize_deg(lon)
    n0 = int(lon // NAK_SPAN_DEG)
    start_deg = n0 * NAK_SPAN_DEG
    f = (lon - start_deg) / NAK_SPAN_DEG  # 0..1

    star = VIM_SEQUENCE[n0 % 9]
    idx0 = VIM_SEQUENCE.index(star)
    seq = [VIM_SEQUENCE[(idx0 + i) % 9] for i in range(9)]

    total = VIM_TOTAL_YEARS
    cum = 0.0
    for p in seq:
        seg = VIM_DURATIONS_YEARS[p] / total
        if cum <= f < cum + seg or abs(f - (cum + seg)) < 1e-12:
            return p
        cum += seg
    return seq[-1]

def house_num_of_lon(lon: float, cusps: List[float]) -> int:
    """
    Return house number (1..12) containing longitude 'lon',
    given 12 cusp longitudes in zodiac order starting at 1.
    """
    lon = normalize_deg(lon)
    for i in range(12):
        a = cusps[i]
        b = cusps[(i + 1) % 12]
        # width of this house as forward arc
        if i < 11:
            width = _arc(a, b)
        else:
            width = 360.0 - sum(_arc(cusps[j], cusps[(j+1) % 12]) for j in range(11))
        if _arc(a, lon) < width or abs(_arc(a, lon) - width) < 1e-12:
            return i + 1
    return 1

def planet_owned_houses(natal: "NatalContext", planet: str) -> List[str]:
    """Houses where the cusp sign is ruled by 'planet'."""
    out = []
    for h, sign in natal.house_map.items():
        if RULERS.get(sign, "") == planet.lower():
            out.append(h)
    return out

# ───────────────────────── Data classes ─────────────────────────

@dataclass
class NatalContext:
    utc_birth_dt: datetime
    latitude: float
    longitude: float
    ascendant_deg: float
    moon_sign: str
    planet_longitudes: Dict[str, float]
    house_map: Dict[str, str]             # sign on each house cusp
    house_cusps_deg: List[float]          # 12 cusp longitudes (deg)

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

# ───────────────────────── Core calculations ─────────────────────────

def compute_natal(birth) -> NatalContext:
    """
    birth must include:
      - utc_iso: ISO datetime string WITH timezone (UTC recommended)
      - latitude: float
      - longitude: float
    """
    if not getattr(birth, "utc_iso", None):
        raise ValueError("birth.utc_iso is required (e.g., 1990-04-20T05:25:00+00:00)")
    if not hasattr(birth, "latitude") or not hasattr(birth, "longitude"):
        raise ValueError("birth.latitude and birth.longitude are required")

    dt_utc = datetime.fromisoformat(birth.utc_iso).astimezone(timezone.utc)
    jd_ut = jd_from_datetime(dt_utc)

    # Planet longitudes (sidereal)
    longs: Dict[str, float] = {}
    for name, const in PLANETS.items():
        if name == "ketu":
            rahu_lon = calc_lon(jd_ut, PLANETS["rahu"])
            longs["ketu"] = normalize_deg(rahu_lon + 180.0)
        else:
            longs[name] = calc_lon(jd_ut, const)

    # House cusps (Placidus)
    cusps_raw, _ascmc = sw.houses(jd_ut, float(birth.latitude), float(birth.longitude))
    cusps_list = list(cusps_raw)
    if len(cusps_list) >= 13 and abs(cusps_list[0]) < 1e-9:
        cusps_vals = cusps_list[1:13]
    else:
        cusps_vals = cusps_list[:12]
    cusps = [normalize_deg(c) for c in cusps_vals]

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
        house_map=house_map,
        house_cusps_deg=cusps,
    )

# ───────────────────────── Vimśottarī Dasha ─────────────────────────

def _moon_nakshatra_fraction(jd_ut: float) -> Tuple[int, float]:
    """Return (nakshatra_index 0..26, fraction 0..1 inside it)."""
    moon_lon = calc_lon(jd_ut, PLANETS["moon"])
    idx = int(normalize_deg(moon_lon) // NAK_SPAN_DEG)
    start = idx * NAK_SPAN_DEG
    frac = (normalize_deg(moon_lon) - start) / NAK_SPAN_DEG
    return idx, frac

def compute_vimshottari_dasha_for_birth(jd_ut: float) -> DashaContext:
    """
    Start Maha from Moon's nakshatra lord with remaining portion first.
    Build full 120-year ladder forward.
    """
    n_idx, frac = _moon_nakshatra_fraction(jd_ut)
    first_lord = VIM_SEQUENCE[n_idx % 9]
    remaining_years = VIM_DURATIONS_YEARS[first_lord] * (1.0 - frac)

    ydays = 365.2425
    periods: List[DashaPeriod] = []

    # First partial maha
    start = jd_ut
    end = start + remaining_years * ydays
    periods.append(DashaPeriod(
        planet=first_lord.title(),
        start_jd=start,
        end_jd=end,
        start_iso=datetime_from_jd(start).isoformat(),
        end_iso=datetime_from_jd(end).isoformat(),
    ))

    # Continue through full cycle until ~120 years total
    cur = end
    seq_idx = (VIM_SEQUENCE.index(first_lord) + 1) % 9
    max_jd = start + VIM_TOTAL_YEARS * ydays + 1.0  # guard
    while cur < max_jd - 1e-6:
        lord = VIM_SEQUENCE[seq_idx % 9]
        span = VIM_DURATIONS_YEARS[lord] * ydays
        nxt = cur + span
        periods.append(DashaPeriod(
            planet=lord.title(),
            start_jd=cur,
            end_jd=nxt,
            start_iso=datetime_from_jd(cur).isoformat(),
            end_iso=datetime_from_jd(nxt).isoformat(),
        ))
        cur = nxt
        seq_idx += 1

    maha = periods[0].planet if periods else None
    antara = None
    praty = None
    return DashaContext(
        maha=maha, antara=antara, pratyantara=praty,
        window_from=periods[0].start_iso, window_to=periods[0].end_iso,
        periods=periods
    )

def subdivide_vimshottari(dasha_ctx, levels: int = 2) -> List[Dict[str, Any]]:
    """
    Split Maha → Antara → Pratyantara by Vimśottarī ratios (KP-correct):
      - Antara list starts from the parent MAHA lord, then follows the cycle
      - Pratyantara list starts from the parent ANTARA lord, then follows the cycle
    """
    out: List[Dict[str, Any]] = []

    def add_block(level: str, lord: str, start_jd: float, end_jd: float, parent: Optional[str] = None):
        out.append({
            "level": level,
            "lord": lord,
            "parent": parent,  # for antara: maha lord; for pratyantara: antara lord
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

        # ANTARA: rotate to start at MAHA lord
        m_len = m_end - m_start
        start_idx = VIM_SEQUENCE.index(m_lord)
        antara_seq = [VIM_SEQUENCE[(start_idx + i) % 9] for i in range(9)]

        cursor = m_start
        for lord in antara_seq:
            frac = VIM_DURATIONS_YEARS[lord] / VIM_TOTAL_YEARS
            span = m_len * frac
            a_start, a_end = cursor, min(cursor + span, m_end)
            add_block("antara", lord, a_start, a_end, parent=m_lord)
            cursor = a_end
            if cursor >= m_end - 1e-9:
                break

        if levels < 3:
            continue

        # PRATYANTARA: for each antara, rotate to start at that antara lord
        for a in [x for x in out if x["level"] == "antara" and x["parent"] == m_lord and m_start - 1e-9 <= x["start_jd"] <= m_end + 1e-9]:
            a_len = a["end_jd"] - a["start_jd"]
            start_idx = VIM_SEQUENCE.index(a["lord"])
            praty_seq = [VIM_SEQUENCE[(start_idx + i) % 9] for i in range(9)]

            cursor = a["start_jd"]
            for lord2 in praty_seq:
                frac2 = VIM_DURATIONS_YEARS[lord2] / VIM_TOTAL_YEARS
                span2 = a_len * frac2
                p_start, p_end = cursor, min(cursor + span2, a["end_jd"])
                add_block("pratyantara", lord2, p_start, p_end, parent=a["lord"])
                cursor = p_end
                if cursor >= a["end_jd"] - 1e-9:
                    break

    return out

# ───────────────────────── KP helpers: CSL & significators ─────────────────────────

def compute_csl_for_houses(natal: "NatalContext") -> Dict[str, str]:
    """Cuspal Sub-Lords (CSL) for houses 1..12."""
    csl: Dict[str, str] = {}
    for i, cusp_lon in enumerate(natal.house_cusps_deg, start=1):
        csl[str(i)] = sub_lord_at(cusp_lon)
    return csl

def planet_significators(natal: "NatalContext") -> Dict[str, Dict[str, float]]:
    """
    KP-flavoured house weights per planet:
      3× houses of planet's star-lord (placement + ownership),
      2× planet's own placement + ownership,
      1× houses of planet's sign-lord (placement + ownership).
    Nodes already inherit via their star/sign packages implicitly.
    """
    weights: Dict[str, Dict[str, float]] = {}

    for p, p_lon in natal.planet_longitudes.items():
        p = p.lower()
        wmap: Dict[str, float] = {}

        # own placement house
        p_house = str(house_num_of_lon(p_lon, natal.house_cusps_deg))

        # own ownership houses
        own_owned = planet_owned_houses(natal, p)

        # star-lord & sign-lord
        s_lord = star_lord_at(p_lon)
        zsign = sign_from_longitude(p_lon)
        sign_lord = RULERS.get(zsign, "")

        def add(houses: List[str], w: float):
            for h in houses:
                wmap[h] = wmap.get(h, 0.0) + w

        # star-lord package (3×)
        if s_lord:
            s_lon = natal.planet_longitudes.get(s_lord)
            if s_lon is not None:
                add([str(house_num_of_lon(s_lon, natal.house_cusps_deg))], 3.0)
            add(planet_owned_houses(natal, s_lord), 3.0)

        # planet itself (2×)
        add([p_house], 2.0)
        add(own_owned, 2.0)

        # sign-lord package (1×)
        if sign_lord:
            s2_lon = natal.planet_longitudes.get(sign_lord)
            if s2_lon is not None:
                add([str(house_num_of_lon(s2_lon, natal.house_cusps_deg))], 1.0)
            add(planet_owned_houses(natal, sign_lord), 1.0)

        weights[p] = wmap

    return weights

# ───────────────────────── Transits (simple demo) ─────────────────────────

def current_transits(natal: NatalContext, as_of_dt: Optional[datetime] = None, orb_deg: float = 1.5) -> TransitContext:
    """
    Very light demo transits (expand as needed):
      - Venus in 7th sign
      - Saturn in 10th sign
      - Jupiter aspect to 10th lord (0/120/240 within orb)
    """
    if as_of_dt is None:
        as_of_dt = datetime.now(timezone.utc)
    jd_ut = jd_from_datetime(as_of_dt)

    cur: Dict[str, float] = {}
    for name, const in PLANETS.items():
        if name == "ketu":
            rahu_lon = calc_lon(jd_ut, PLANETS["rahu"])
            cur["ketu"] = normalize_deg(rahu_lon + 180.0)
        else:
            cur[name] = calc_lon(jd_ut, const)

    active: Dict[str, Any] = {}
    # Venus in 7th sign
    active["venus_transit_7th"] = (sign_from_longitude(cur["venus"]) == natal.house_map.get("7"))
    # Saturn in 10th sign
    active["saturn_in_10th"] = (sign_from_longitude(cur["saturn"]) == natal.house_map.get("10"))

    # Jupiter aspecting 10th lord (0/120/240)
    tenth_sign = natal.house_map.get("10", "")
    tenth_lord = RULERS.get(tenth_sign)
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
