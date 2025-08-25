# tools/build_mvp_rules.py
from pathlib import Path
import ujson as json
import csv

IN = Path("data/kp_rules.dedup.jsonl")
OUT = Path("app/data/rules.csv")
OUT.parent.mkdir(parents=True, exist_ok=True)

def rule_to_trigger(rule):
    theme = (rule.get("theme") or "General").strip().lower()
    # encode theme directly into the trigger so we can match by theme later
    return f"theme_{theme.replace(' ', '_')}"


def main():
    if not IN.exists():
        print("Missing", IN)
        return
    rows = []
    with IN.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            r = json.loads(line)
            rows.append({
                "ID": r.get("id") or f"KP-{i:04d}",
                "Theme": r.get("theme","General"),
                "Astrological Trigger": rule_to_trigger(r),
                "Natural Prediction Message": r.get("logic_text","Keep it steady."),
                "Tone Options": "Neutral"
            })
    with OUT.open("w", newline="", encoding="utf-8") as w:
        writer = csv.DictWriter(w, fieldnames=[
            "ID","Theme","Astrological Trigger","Natural Prediction Message","Tone Options"
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} MVP rules -> {OUT}")

if __name__ == "__main__":
    main()

