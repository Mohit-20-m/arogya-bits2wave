"""Decision logic v2: the 26 example patients approved in docs/decision-logic-v2.md (section 6).

Every result answers three questions separately (findings today, exposure, confidence) and then picks one action.
Habits are exposure only: they never create a finding and never turn an AI flag into an automatic referral.
"""
import pytest

from app.domain.clinical import score_habits
from app.domain.decision import DEFAULT_RULE_SET as R, RuleSetDef, build_facts, evaluate

SITES = ("left_buccal", "right_buccal", "tongue_dorsum", "tongue_ventral", "gums", "palate")


def ai(top=0.02, site="left_buccal", **extra):
    probs = {s: 0.02 for s in SITES}
    probs[site] = top
    return {"available": True, "max_prob": top, "threshold": 0.78, "site_probs": probs, "unusable_sites": [],
            **extra}


def decide(habits=None, symptoms=None, opening=45.0, ai_result=None, timeline=None):
    habits, symptoms = habits or {}, symptoms or {}
    _, level, factors = score_habits(habits, symptoms, R["habit_scoring"])
    facts = build_facts(rule_set=R, habit_level=level, habit_factors=factors, symptoms=symptoms, opening_mm=opening,
                        ai=ai() if ai_result is None else ai_result, timeline=timeline or {})
    out = evaluate(R, facts)
    out["_facts"] = facts
    return out


def rules(out):
    return [r["rule"] for r in out["reasons"]]


GUTKA_10Y = {"tobacco": True, "tobacco_type": "smokeless", "tobacco_years": 10, "tobacco_status": "current"}
HEAVY_SMOKER = {"tobacco": True, "tobacco_type": "smoked", "tobacco_years": 15, "tobacco_per_day": 20,
                "alcohol": True, "alcohol_frequency": "daily"}
AREKA_5Y = {"areca": True, "areca_years": 5}


def test_rule_set_v2_is_valid():
    RuleSetDef.model_validate(R)


# 1, 26 - healthy, no habits
@pytest.mark.parametrize("case", ["healthy non-user", "Ravi"])
def test_healthy_non_user_is_routine(case):
    out = decide()
    assert out["risk_level"] == "LOW" and out["followup_days"] == 365
    assert out["summary"]["findings"]["status"] == "none"
    assert out["summary"]["exposure"]["level"] == "low"


# 2 - the key change: daily gutka, healthy mouth -> Low + high exposure, not "Medium risk"
def test_daily_gutka_healthy_mouth_is_low_with_high_exposure():
    out = decide(habits=GUTKA_10Y)
    assert out["risk_level"] == "LOW"
    assert "E1" in rules(out) and out["followup_days"] == 180
    assert out["summary"]["findings"]["text"] == "No suspicious signs today"
    assert out["summary"]["exposure"]["level"] == "high"
    assert "counselling" in out["summary"]["action"]["text"]


# 3
def test_heavy_smoker_and_drinker_healthy_mouth_is_low_high_exposure():
    out = decide(habits=HEAVY_SMOKER)
    assert out["risk_level"] == "LOW" and out["summary"]["exposure"]["level"] == "high"
    assert "heavy daily use" in out["_facts"]["habit_factors"]


# 4
def test_former_smoker_quit_long_ago_is_low_exposure():
    out = decide(habits={"tobacco": True, "tobacco_type": "smoked", "tobacco_status": "former",
                         "tobacco_quit_years": 8})
    assert out["risk_level"] == "LOW" and out["summary"]["exposure"]["level"] == "low"
    assert out["followup_days"] == 365


# 5
def test_daily_pan_is_moderate_exposure():
    out = decide(habits=AREKA_5Y)
    assert out["risk_level"] == "LOW" and "E2" in rules(out)
    assert out["summary"]["exposure"]["level"] == "moderate"


# 6
def test_recent_patch_is_watch_recheck_in_two_weeks():
    out = decide(symptoms={"patch_noticed": True, "patch_duration_days": 5})
    assert out["risk_level"] == "MEDIUM" and "R11" in rules(out) and out["followup_days"] == 14


# 7, 8 - strong clinical signs refer even with clean photos
@pytest.mark.parametrize("symptoms,rule", [
    ({"patch_noticed": True, "patch_duration_days": 21}, "R3"),
    ({"ulcer_not_healing": True}, "R3b"),
])
def test_strong_clinical_sign_refers(symptoms, rule):
    out = decide(symptoms=symptoms)
    assert out["risk_level"] == "HIGH" and rule in rules(out) and "create_referral" in out["actions"]
    assert out["summary"]["findings"]["status"] == "clinical"


# 9 - OSMF signs
def test_restricted_opening_with_burning_refers():
    out = decide(symptoms={"burning": True}, opening=31.0, habits=GUTKA_10Y)
    assert out["risk_level"] == "HIGH" and "R2" in rules(out)


# 10, 11, 12 - weak signs only -> watch, 3 months
@pytest.mark.parametrize("symptoms,opening,rule", [
    ({}, 31.0, "R10"),
    ({}, 38.0, "R9"),
    ({"burning": True}, 45.0, "R12"),
])
def test_weak_signs_only_are_watch(symptoms, opening, rule):
    out = decide(symptoms=symptoms, opening=opening, habits=AREKA_5Y)
    assert out["risk_level"] == "MEDIUM" and rule in rules(out) and out["followup_days"] == 90


# 13 - AI uncertain -> specialist photo review (14 days)
def test_uncertain_ai_goes_to_review():
    out = decide(ai_result=ai(0.60))
    assert out["risk_level"] == "NEEDS_REVIEW" and "R1d" in rules(out) and out["review_priority"] == 35
    assert out["summary"]["findings"]["status"] == "uncertain"


# 14 - AI suspicious, no signs -> review in 7 days
def test_suspicious_ai_without_signs_goes_to_review():
    out = decide(ai_result=ai(0.82))
    assert out["risk_level"] == "NEEDS_REVIEW" and "R1b" in rules(out)
    assert "create_referral" not in out["actions"]


# 15 - the other key change: habits do NOT turn an AI flag into an automatic referral
def test_suspicious_ai_plus_heavy_habits_is_review_not_referral():
    out = decide(ai_result=ai(0.82), habits=GUTKA_10Y)
    assert out["risk_level"] == "NEEDS_REVIEW" and "R1b" in rules(out)
    assert "moved up the queue" in out["reasons"][0]["text"]


# 16, 17 - AI suspicious + any clinical sign -> refer
@pytest.mark.parametrize("symptoms,opening", [({"patch_noticed": True, "patch_duration_days": 3}, 45.0), ({}, 31.0)])
def test_suspicious_ai_with_clinical_sign_refers(symptoms, opening):
    out = decide(ai_result=ai(0.82), symptoms=symptoms, opening=opening)
    assert out["risk_level"] == "HIGH" and "R1" in rules(out)


# 18 - decision A6: highly suspicious AI refers directly, with the model's accuracy in the explanation
def test_highly_suspicious_ai_refers_directly_with_model_evidence():
    out = decide(ai_result=ai(0.95))
    assert out["risk_level"] == "HIGH" and "R1a" in rules(out) and "create_referral" in out["actions"]
    text = next(r["text"] for r in out["reasons"] if r["rule"] == "R1a")
    assert "95%" in text and "EfficientNetV2-S" in text and "90.9% sensitivity" in text and "346" in text


def test_model_evidence_comes_from_the_active_model_when_available():
    a = ai(0.95, model_evidence={"name": "EfficientNetV2-S v2", "sensitivity": 0.93, "specificity": 0.96, "n": 400})
    text = next(r["text"] for r in decide(ai_result=a)["reasons"] if r["rule"] == "R1a")
    assert "93.0% sensitivity" in text and "400 held-out" in text


# 19 - high score on an unclear photo is not trusted
def test_high_score_on_unclear_photo_is_review():
    a = ai(0.02)
    a["unreliable_flag_sites"] = {"right_buccal": 0.95}
    out = decide(ai_result=a)
    assert out["risk_level"] == "NEEDS_REVIEW" and "R1c" in rules(out)
    assert out["summary"]["confidence"]["level"] == "limited"


# 20 - too many unusable photos
def test_three_unusable_photos_cannot_assess():
    out = decide(ai_result=ai(0.02, unusable_sites=["gums", "palate", "tongue_ventral"]))
    assert out["risk_level"] == "CANNOT_ASSESS" and out["summary"]["confidence"]["level"] == "cannot_assess"


# 21 - fail-safe: AI missing is never low, even with heavy habits
def test_ai_missing_is_never_low():
    out = decide(ai_result={"available": False}, habits=GUTKA_10Y)
    assert out["risk_level"] == "NEEDS_REVIEW" and out["summary"]["confidence"]["level"] == "pending"


# 22 - Lalitha: pain relieved by a gel while the patch persists
def test_masked_symptom_refers_lalitha():
    out = decide(symptoms={"patch_noticed": True, "patch_duration_days": 10, "pain_relieved_by_medication": True},
                 timeline={"pain_relieved": True, "masking_medication": "benzocaine gel"}, habits=AREKA_5Y)
    assert out["risk_level"] == "HIGH" and "R4" in rules(out)


# 23 - symptoms back after an earlier high-risk result
def test_symptoms_returned_refers():
    out = decide(timeline={"symptoms_returned": True, "previous_high": True}, habits=GUTKA_10Y)
    assert out["risk_level"] == "HIGH" and "R5" in rules(out)


# 25 - Shekhar
def test_shekhar_is_referred():
    habits = {"tobacco": True, "tobacco_type": "smokeless", "tobacco_years": 12, "areca": True, "areca_years": 12}
    out = decide(ai_result=ai(0.99), habits=habits, symptoms={"burning": True, "difficulty_opening": True},
                 opening=31.0)
    assert out["risk_level"] == "HIGH"
    assert {"R1", "R1a", "R2"} <= set(rules(out))
    s = out["summary"]
    assert s["findings"]["status"] == "suspicious" and "99%" in s["findings"]["text"]
    assert s["exposure"]["level"] == "high" and s["confidence"]["level"] == "good"
    assert s["action"]["text"] == "Refer to a specialist within 14 days"


# habits are counted once: symptoms no longer add to exposure
def test_symptoms_do_not_count_as_exposure():
    _, level, factors = score_habits({}, {"burning": True, "difficulty_opening": True}, R["habit_scoring"])
    assert level == "low" and factors == []


def test_switched_off_habit_is_never_whatever_its_status():
    _, level, _ = score_habits({**GUTKA_10Y, "tobacco": False}, {}, R["habit_scoring"])
    assert level == "low"
