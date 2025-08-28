#!/usr/bin/env python3
# tools/extract_kp_examples.py
#
# Usage:
#   python tools/extract_kp_examples.py \
#       --jsonl "data/book_text.jsonl" \
#       --cities "app/static/cities_in.json" \
#       --out "app/data/kp_examples.csv"
#
# Requires: python-dateutil
#   pip install python-dateutil

import re
import json
import csv
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dateutil import parser as dtp

# --- Heuristic regexes (tune as you see patterns in your books) ---

# Examples of birth lines the script can catch:
# "Born on 20 April 1990 at 5:22 am in Pune (Maharashtra, India)."
# "Birth: 20-04-1990, 05:22 IST, Pune"
# "DOB 20/4/1990 05:22 hrs Pune"
RX_BIRTH = re.compile(
    r"""(?ix)
    (?:
      \b(?:born|birth|dob)\b [^\n,.]*?
      (?:(?:on|:)\s*)?
    )
    (?P<date>
      \d{1,2}[-/\s]\d{1,2}[-/\s]\d{2,4} |
      \d{1,2}\s+\w+\s+\d{4} |
      \w+\s+\d{1,2},\s*\d{4}
    )
    [^\n,.;]*?
    (?:
      \b(?:at|@)\b\s*
      (?P<time>
        \d{1,2}[:.]\d{2}
        (?:\s*(?:AM|PM|am|pm))?
      )
      (?:\s*(?P<tzn>IST|I\.S\.T\.|hrs|HRS))?
    )?
    [^\n,.;]*?
    (?:
      \b(?:in|at)\b\s+
      (?P<place>[A-Za-z .'-]{3,}(?:,\s*[A-Za-z .'-]+){0,2})
    )?
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Event lines we care about with dates somewhere nearby.
EVENT_KEYWORDS = {
    "marriage": r"\b(marriage|married|wedding)\b",
    "child": r"\b(childbirth|birth\s+of\s+(?:a\s+)?(?:child|son|daughter)|blessed\s+with|baby\s+born)\b",
    "promotion": r"\b(promotion|promoted|elevation|career\s+rise)\b",
    "travel": r"\b(foreign\s+travel|went\s+abroad|overseas\s+trip|visa\s+granted|journey)\b",
}
RX_DATE = re.compile(
    r"""(?ix)
    \b(
      \d{1,2}[-/\s]\d{1,2}[-/\s]\d{2,4} |
      \d{1,2}\s+\w+\s+\d{4} |
      \w+\s+\d{1,2},\s*\d{4}
    )\b
    """
)

# --- Helpers ---

def parse_date(s: str):
    try:
        return dtp.parse(s, dayfirst=True, fuzzy=True)
    except Exception:
        return None

def normalize_birth(dt_local: datetime, tzn_hint: str | None):
    """
    If IST-ish hints are present, interpret as Asia/Kolkata (UTC+5:30) and convert to UTC.
    Else, leave naive as UTC (best-effort; books often omit TZ).
    """
    s = (tzn_hint or "").upper()
    if "IST" in s or "I.S.T" in s or "HRS" in s:
        # treat as IST (+5:30)
        # attach fake UTC then adjust backwards 5:30
        dt_naive = dt_local.replace(tzinfo=timezone.utc)
        return (dt_naive - timedelta(hours=5, minutes=30)).astimezone(timezone.utc)
    # If dt_local has no tzinfo, assume it's already UTC.
    if dt_local.tzinfo is None:
        return dt_local.replace(tzinfo=timezone.utc)
    return dt_local.astimezone(timezone.utc)

def load_cities(path: Path):
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Expect: [{"country":"India","state":"Maharashtra","city":"Pune","lat":18.5,"lon":73.8}, ...]
        idx = {}
        for r in data:
            key = (r.get("country","").strip().lower(), r.get("state","").strip().lower(), r.get("city","").strip().lower())
            idx[key] = (float(r["lat"]), float(r["lon"]))
            # also index by just city in case no state is given
            idx[("", "", r.get("city","").strip().lower())] = (float(r["lat"]), float(r["lon"]))
        return idx
    except Exception:
        return {}

def lookup_latlon(place: str, city_index: dict):
    if not place:
        return None, None
    parts = [p.strip() for p in re.split(r"[,(]", place) if p.strip()]
    city = parts[0].lower()
    state = parts[1].lower() if len(parts) > 1 else ""
    country = parts[2].lower() if len(parts) > 2 else ""
    # try (country,state,city), then just (,,city)
    for key in [
        (country, state, city),
        ("india", state, city),
        ("", "", city),
    ]:
        if key in city_index:
            return city_index[key]
    return None, None

def clean_place(place: str | None):
    if not place:
        return ""
    # trim trailing descriptors like "Maharashtra, India)."
    place = place.strip().rstrip(").,; ")
    return place

# --- Core extraction ---

def extract_examples(jsonl_path: Path, cities_path: Path | None, out_csv: Path):
    city_index = load_cities(cities_path) if cities_path else {}

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fout = out_csv.open("w", newline="", encoding="utf-8")
    w = csv.DictWriter(
        fout,
        fieldnames=[
            "name","utc_iso","lat","lon","event","date","source_book","source_page","notes"
        ],
    )
    w.writeheader()

    n_pages = 0
    n_births = 0
    n_events = 0

    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            text = rec.get("text","")
            source = rec.get("source","")
            page = rec.get("page", "")

            n_pages += 1

            # Try to find birth facts on the page
            birth = None
            for m in RX_BIRTH.finditer(text):
                date_s = (m.group("date") or "").strip()
                time_s = (m.group("time") or "").strip()
                tzn_s  = (m.group("tzn") or "").strip()
                place  = clean_place(m.group("place"))

                dt = parse_date(f"{date_s} {time_s}".strip()) or parse_date(date_s)
                if not dt:
                    continue
                dt_utc = normalize_birth(dt, tzn_s)
                lat, lon = lookup_latlon(place, city_index)
                birth = {
                    "name": "",  # many books anonymize; can attempt to parse nearby "Mr./Mrs./Case" if needed
                    "utc_iso": dt_utc.isoformat(),
                    "lat": lat if lat is not None else "",
                    "lon": lon if lon is not None else "",
                    "source_book": source,
                    "source_page": page,
                    "notes": f"place={place}; parsed={date_s} {time_s} {tzn_s}".strip(),
                }
                n_births += 1
                break

            # Scan for events with dates
            for evt, rx_kw in EVENT_KEYWORDS.items():
                for m in re.finditer(rx_kw, text, flags=re.IGNORECASE):
                    # Grab a small window around the match to find a date
                    start = max(0, m.start() - 120)
                    end   = min(len(text), m.end() + 120)
                    window = text[start:end]
                    dmatch = RX_DATE.search(window)
                    if not dmatch:
                        continue
                    evt_dt = parse_date(dmatch.group(1))
                    if not evt_dt:
                        continue
                    # Many books list event dates without times or tz. Record date only (UTC midnight).
                    evt_iso = evt_dt.date().isoformat()

                    row = {
                        "name": birth["name"] if birth else "",
                        "utc_iso": birth["utc_iso"] if birth else "",
                        "lat": birth["lat"] if birth else "",
                        "lon": birth["lon"] if birth else "",
                        "event": evt,
                        "date": evt_iso,
                        "source_book": source,
                        "source_page": page,
                        "notes": (birth["notes"] if birth else "").strip(),
                    }
                    w.writerow(row)
                    n_events += 1

    fout.close()
    print(f"Scanned pages: {n_pages}")
    print(f"Birth records found: {n_births}")
    print(f"Event records written: {n_events}")
    print(f"Wrote CSV -> {out_csv}")
    return n_births, n_events

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True, help="Path to data/book_text.jsonl")
    ap.add_argument("--cities", default="app/static/cities_in.json", help="Optional cities index (country/state/city/lat/lon)")
    ap.add_argument("--out", default="app/data/kp_examples.csv", help="Output CSV path")
    args = ap.parse_args()

    jsonl_path = Path(args.jsonl)
    cities_path = Path(args.cities) if args.cities else None
    out_csv = Path(args.out)

    if not jsonl_path.exists():
        raise SystemExit(f"JSONL not found: {jsonl_path}")

    extract_examples(jsonl_path, cities_path, out_csv)

if __name__ == "__main__":
    main()
