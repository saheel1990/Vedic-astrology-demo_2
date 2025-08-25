# tools/extract_rules_baseline.py
from pathlib import Path
import ujson as json
import re

IN = Path("data/book_text.jsonl")
OUT = Path("data/kp_rules.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)

THEMES = [
    ("Marriage",  [r"\b7(th)?\b", r"\bmarriage\b", r"\bspouse\b"]),
    ("Career",    [r"\b10(th)?\b", r"\bcareer\b", r"\bprofession\b", r"\bjob\b"]),
    ("Education", [r"\beducation\b", r"\bstudy|studies\b"]),
    ("Property",  [r"\bproperty\b", r"\breal estate\b", r"\bland\b"]),
    ("Travel",    [r"\btravel\b", r"\bjourney\b", r"\bforeign\b"]),
    ("Wealth",    [r"\bwealth\b", r"\bfinance\b", r"\bmoney\b", r"\bincome\b"]),
    ("Health",    [r"\bhealth\b", r"\billness\b", r"\bdisease\b"]),
    ("Children",  [r"\bchild|children\b", r"\bprogeny\b"]),
    ("Litigation",[r"\bcourt\b", r"\blitigation\b", r"\blegal\b"]),
]

# crude patterns that look like KP-ish rules
RULE_HINTS = [
    r"\bif\b.+\bthen\b.+",                    # “If … then …”
    r"\bsublord\b.+\b(signif|signifies)\b.+", # sublord signifies …
    r"\bcusp\b.+\bsublord\b",                 # cusp sublord …
    r"\b(significator|signifies)\b.+\b(2|3|4|5|6|7|8|9|10|11|12)\b",  # house numbers
]

def guess_theme(text: str) -> str:
    t = text.lower()
    for theme, pats in THEMES:
        if any(re.search(p, t) for p in pats):
            return theme
    return "General"

def guess_house(text: str):
    t = text.lower()
    # look for “7th”, “10th”, etc.
    m = re.search(r"\b(1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th|11th|12th)\b", t)
    if m:
        order = m.group(1).rstrip("stndrth")
        try: return int(order)
        except: pass
    m2 = re.search(r"\bhouse\s*(1[0-2]|[1-9])\b", t)
    if m2: return int(m2.group(1))
    return None

def find_sets(text: str, pattern_words):
    # find tokens like Venus, Jupiter, 2,7,11, Rahu, etc.
    names = re.findall(r"\b(venus|jupiter|saturn|mars|mercury|moon|sun|rahu|ketu)\b", text.lower())
    houses = re.findall(r"\b(1[0-2]|[2-9])\b", text)  # 2..12
    out = []
    if names: out += [n.title() for n in names]
    if houses: out += list(dict.fromkeys(houses))
    return list(dict.fromkeys(out))[:6]  # unique, keep a few

def main():
    if not IN.exists():
        print("Run tools/extract_text_mupdf.py first.")
        return

    wrote = 0
    with IN.open("r", encoding="utf-8") as r, OUT.open("w", encoding="utf-8") as w:
        for idx, line in enumerate(r, start=1):
            rec = json.loads(line)
            txt = rec.get("text","").strip()
            if not txt: continue

            # split into sentences; scan for rule-y ones
            sents = re.split(r"(?<=[.!?])\s+", txt)
            for s in sents:
                if len(s) < 40: 
                    continue
                if not any(re.search(p, s, flags=re.I) for p in RULE_HINTS):
                    continue

                theme = guess_theme(s)
                house = guess_house(s)
                sigs = find_sets(s, None)

                rule = {
                    "id": f"BASE-{rec['book']}-{rec['page']}-{wrote+1}",
                    "theme": theme,
                    "house": house,
                    "sublord_any": [x for x in sigs if x in {"Venus","Jupiter","Saturn","Mars","Mercury","Moon","Sun","Rahu","Ketu"}] or None,
                    "significators_any": [x for x in sigs if x.isdigit()] or None,
                    "timing_clues": None,
                    "logic_text": s.strip()[:400],
                    "confidence": 0.35,
                    "source": {"book": rec["book"], "page": rec["page"], "chapter": rec["chapter"]}
                }
                w.write(json.dumps(rule, ensure_ascii=False) + "\n")
                wrote += 1

    print(f"Wrote ~{wrote} baseline rules -> {OUT}")

if __name__ == "__main__":
    main()
