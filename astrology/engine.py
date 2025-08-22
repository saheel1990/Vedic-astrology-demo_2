from dataclasses import dataclass
from typing import Dict, Any, List, Tuple
import swisseph as sw
from datetime import datetime, timezone
import math

PLANETS = {
    "sun": sw.SUN,
    "moon": sw.MOON,
    "mercury": sw.MERCURY,
    "venus": sw.VENUS,
    "mars": sw.MARS,
    "jupiter": sw.JUPITER,
    "saturn": sw.SATURN,
    "rahu": sw.MEAN_NODE,
    "ketu": sw.MEAN_NODE
}

VIM_DURATIONS_YEARS = {
    "ketu": 7.0, "venus": 20.0, "sun": 6.0, "moon": 10.0, "mars": 7.0, "rahu": 18.0, "jupiter": 16.0, "saturn": 19.0, "mercury": 17.0
}
VIM_SEQUENCE = ["ketu","venus","sun","moon","mars","rahu","jupiter","saturn","mercury"]

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
    maha: str
    antara: str
    pratyantara: str
    window_from: str
    window_to: str
    periods: List[DashaPeriod]

@dataclass
class TransitContext:
    active: Dict[str, Any]

def jd_from_datetime(dt: datetime) -> float:
    ts = dt.timestamp()
    jd = ts / 86400.0 + 2440587.5
    return jd

def datetime_from_jd(jd: float) -> datetime:
    ts = (jd - 2440587.5) * 86400.0
    return datetime.fromtimestamp(ts, tz=timezone.utc)

def normalize_deg(x: float) -> float:
    x = x % 360.0
    if x < 0: x += 360.0
    return x

def sign_from_longitude(lon: float) -> str:
    sign_index = int(math.floor(lon / 30.0))
    signs = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]
    return signs[sign_index]

def nakshatra_index_and_fraction(moon_lon: float) -> Tuple[int, float, float]:
    span = 360.0 / 27.0
    idx = int(math.floor(moon_lon / span))
    start = idx * span
    frac = (moon_lon - start) / span
    return idx, frac, span

def compute_natal(birth) -> NatalContext:
    if not hasattr(birth, "utc_iso") or not birth.utc_iso:
        raise ValueError("birth.utc_iso required")
    if not hasattr(birth, "latitude") or not hasattr(birth, "longitude"):
        raise ValueError("latitude/longitude required")
    local_dt = datetime.fromisoformat(birth.utc_iso)
    jd_ut = jd_from_datetime(local_dt.astimezone(timezone.utc))

    longitudes = {}
    for name, sw_const in PLANETS.items():
        if name == "ketu":
            rahu_lon = sw.calc_ut(jd_ut, PLANETS["rahu"])[0]
            longitudes["ketu"] = normalize_deg(rahu_lon + 180.0); continue
        lonp = sw.calc_ut(jd_ut, sw_const)[0]
        longitudes[name] = normalize_deg(lonp)

    houses = sw.houses(jd_ut, birth.latitude, birth.longitude)[0]
    asc_deg = houses[0]
    moon_sign = sign_from_longitude(longitudes["moon"])
    house_map = { f"{i+1}": sign_from_longitude(h) for i,h in enumerate(houses[:12]) }

    return NatalContext(utc_birth_dt=local_dt.astimezone(timezone.utc), latitude=birth.latitude, longitude=birth.longitude,
                        ascendant_deg=asc_deg, moon_sign=moon_sign, planet_longitudes=longitudes, house_map=house_map)

def compute_vimshottari_dasha_for_birth(jd_ut: float) -> DashaContext:
    moon_lon = normalize_deg(sw.calc_ut(jd_ut, PLANETS["moon"])[0])
    nak_idx, frac, _ = nakshatra_index_and_fraction(moon_lon)
    lord = VIM_SEQUENCE[nak_idx % 9]
    remaining_years = VIM_DURATIONS_YEARS[lord] * (1.0 - frac)
    periods = []
    year_days = 365.2425
    start_jd = jd_ut - 1e-9
    end_jd = start_jd + remaining_years * year_days
    periods.append(DashaPeriod(planet=lord, start_jd=start_jd, end_jd=end_jd,
                               start_iso=datetime_from_jd(start_jd).isoformat(), end_iso=datetime_from_jd(end_jd).isoformat()))
    seq_idx = (VIM_SEQUENCE.index(lord) + 1) % len(VIM_SEQUENCE)
    cur_start = end_jd
    max_jd = start_jd + 120 * year_days
    while cur_start < max_jd:
        planet = VIM_SEQUENCE[seq_idx % len(VIM_SEQUENCE)]
        dur_years = VIM_DURATIONS_YEARS[planet]
        cur_end = cur_start + dur_years * year_days
        periods.append(DashaPeriod(planet=planet, start_jd=cur_start, end_jd=cur_end,
                                   start_iso=datetime_from_jd(cur_start).isoformat(), end_iso=datetime_from_jd(cur_end).isoformat()))
        cur_start = cur_end; seq_idx += 1

    maha = periods[0].planet; antara = periods[1].planet if len(periods)>1 else None; pratyantara = periods[2].planet if len(periods)>2 else None
    return DashaContext(maha=maha, antara=antara, pratyantara=pratyantara, window_from=periods[0].start_iso, window_to=periods[0].end_iso, periods=periods)

def current_transits(natal: NatalContext, as_of_dt: datetime = None, orb_deg: float = 1.5) -> TransitContext:
    if as_of_dt is None:
        as_of_dt = datetime.now(timezone.utc)
    jd_ut = jd_from_datetime(as_of_dt)
    current_lons = {}
    for name, sw_const in PLANETS.items():
        if name == "ketu":
            rahu_lon = sw.calc_ut(jd_ut, PLANETS["rahu"])[0]
            current_lons["ketu"] = normalize_deg(rahu_lon + 180.0); continue
        current_lons[name] = normalize_deg(sw.calc_ut(jd_ut, sw_const)[0])
    active = {}
    def sign(l): return sign_from_longitude(l)
    venus_sign = sign(current_lons["venus"]); sat_sign = sign(current_lons["saturn"])
    active["venus_transit_7th"] = (venus_sign == natal.house_map.get("7"))
    active["saturn_in_10th"] = (sat_sign == natal.house_map.get("10"))
    rulers = {"Aries":"mars","Taurus":"venus","Gemini":"mercury","Cancer":"moon","Leo":"sun","Virgo":"mercury","Libra":"venus","Scorpio":"mars","Sagittarius":"jupiter","Capricorn":"saturn","Aquarius":"saturn","Pisces":"jupiter"}
    tenth_lord = rulers.get(natal.house_map.get("10",""), None)
    jup_lon = current_lons["jupiter"]; flag=False
    if tenth_lord and tenth_lord in natal.planet_longitudes:
        lord_lon = natal.planet_longitudes[tenth_lord]
        for ang in [0, 120, 240]:
            target = abs(((jup_lon - lord_lon) - ang + 360) % 360)
            if target <= orb_deg or abs(target - 360) <= orb_deg: flag=True; break
    active["jupiter_aspecting_10th_lord"] = flag
    return TransitContext(active=active)
