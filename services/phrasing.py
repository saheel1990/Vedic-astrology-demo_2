from typing import Dict
from app.astrology.rules import Rule

def phrase_prediction(rule: Rule, natal, dasha, transits, tone: str = "Friendly") -> Dict[str, str]:
    msg = rule.message
    if tone == "Neutral": msg = msg.replace("!", ".")
    elif tone == "Playful": msg += " Enjoy the positive momentum."
    elif tone == "Spiritual": msg += " Trust the timing and stay centered."
    if getattr(rule, "date_from", None): msg = msg.replace("{from}", rule.date_from)
    if getattr(rule, "date_to", None): msg = msg.replace("{to}", rule.date_to)
    return {"id": rule.id, "theme": rule.theme, "message": msg, "from": rule.date_from, "to": rule.date_to}
