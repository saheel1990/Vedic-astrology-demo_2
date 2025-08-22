import pandas as pd
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path

@dataclass
class Rule:
    id: str
    theme: str
    trigger: str
    message: str
    tone: str
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    logic: Optional[str] = None

class RuleLibrary:
    def __init__(self, rules: List[Rule]): self.rules = rules

    @staticmethod
    def load_from_file(path: str):
        p = Path(path); 
        if p.suffix.lower() in [".xls",".xlsx"]: df = pd.read_excel(p)
        else: df = pd.read_csv(p)
        req = ["ID","Theme","Astrological Trigger","Natural Prediction Message","Tone Options"]
        for c in req:
            if c not in df.columns: raise ValueError(f"Missing column: {c}")
        rules = []
        for _,row in df.iterrows():
            rules.append(Rule(id=str(row["ID"]), theme=str(row["Theme"]), trigger=str(row["Astrological Trigger"]).strip(),
                              message=str(row["Natural Prediction Message"]).strip(), tone=str(row.get("Tone Options","Friendly")),
                              logic=str(row.get("Logic","")) if "Logic" in df.columns else None))
        return RuleLibrary(rules)

    @staticmethod
    def load_default():
        p = Path(__file__).parent.parent / "data" / "Vedic_Astrology_Prediction_Rulebook_150+_Templates.xlsx"
        if not p.exists(): raise FileNotFoundError("Rulebook missing. Place XLSX in app/data/.")
        return RuleLibrary.load_from_file(str(p))
