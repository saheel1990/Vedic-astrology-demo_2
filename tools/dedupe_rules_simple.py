# tools/dedupe_rules_simple.py
from pathlib import Path
import ujson as json
import re, hashlib

IN = Path("data/kp_rules.jsonl")
OUT = Path("data/kp_rules.dedup.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)

def norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\d+", "<num>", s)
    s = re.sub(r"[^a-z<>\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def main():
    if not IN.exists():
        print("Run tools/extract_rules_baseline.py first.")
        return
    seen = set()
    kept = 0
    with IN.open("r", encoding="utf-8") as r, OUT.open("w", encoding="utf-8") as w:
        for line in r:
            obj = json.loads(line)
            key = hashlib.md5(norm(obj["logic_text"]).encode()).hexdigest()
            if key in seen: 
                continue
            seen.add(key)
            w.write(json.dumps(obj, ensure_ascii=False) + "\n")
            kept += 1
    print(f"Deduped → kept {kept} rules at {OUT}")

if __name__ == "__main__":
    main()
