# app/astrology/event_policies.py
EVENT_POLICIES = {
    "marriage": {
        "houses_pos": ["7","2","11"],
        "houses_neg": ["1","6","10"],
        "focus_planets": {"venus": 2.0, "jupiter": 1.2, "moon": 1.0},
        "age_min": 18, "age_max": 70
    },
    "child": {
        "houses_pos": ["5","2","11","9"],
        "houses_neg": ["1","4","10"],
        "focus_planets": {"jupiter": 2.0, "moon": 1.2, "venus": 1.0},
        "age_min": 18, "age_max": 55
    },
    "promotion": {
        "houses_pos": ["10","11","2","6"],
        "houses_neg": ["12","8"],
        "focus_planets": {"saturn": 1.6, "jupiter": 1.2, "mercury": 1.0, "sun": 0.8, "mars": 0.6},
        "age_min": 20, "age_max": 75
    },
    "travel": {
        "houses_pos": ["12","9","3"],
        "houses_neg": ["4","2"],
        "focus_planets": {"rahu": 1.6, "jupiter": 1.2, "mercury": 1.0, "moon": 0.8},
        "age_min": 5, "age_max": 90
    }
}
