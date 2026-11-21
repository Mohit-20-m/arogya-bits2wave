"""Transparent, versioned decision engine.

A rule set is DATA (stored in rule_sets, approved by maker-checker). The engine
1. computes named facts from the screening (+ AI results + timeline),
2. evaluates every rule (simple JSON conditions),
3. returns the most severe matching level, ALL reasons, and the actions to take.

Fail-safe: if AI results are missing the outcome is NEEDS_REVIEW - never LOW.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

SEVERITY = {"LOW": 0, "MEDIUM": 1, "NEEDS_REVIEW": 2, "CANNOT_ASSESS": 3, "HIGH": 4}

# names usable in rule_set["lesion"]["supporting_signs"] -> human-readable text for reasons
SUPPORTING_SIGNS = {"habit_high": "high-risk habits", "patch_noticed": "patch noticed by patient",
                    "ulcer_not_healing": "ulcer not healing", "opening_restricted": "restricted mouth opening",
                    "opening_borderline": "borderline mouth opening", "burning": "burning sensation",
                    "difficulty_opening": "difficulty opening the mouth",
                    "previous_high": "previous high-risk screening"}

RULE_SET_V1: dict = {
    "name": "Arogya default triage rules",
    "habit_scoring": {
        "weights": {"tobacco": 3, "alcohol": 2, "areca": 2, "years_over_10": 1, "burning": 2,
                    "difficulty_opening": 1},
        "levels": {"high": 5, "moderate": 3},
    },
    "mouth_opening": {"restricted_mm": 35.0, "borderline_mm": 40.0, "iris_mm": 11.7, "card_mm": 85.6,
                      "max_head_angle_deg": 12, "calibration": {"slope": 1.0, "intercept": 0.0}},
    "lesion": {"threshold": None, "threshold_source": "model_screening", "min_sites_for_cannot_assess": 3,
               # An AI flag becomes HIGH (auto-referral) only together with one of these signs; otherwise a
               # specialist looks at the photos first (R1b). See SUPPORTING_SIGNS in build_facts for the names.
               "supporting_signs": ["habit_high", "patch_noticed", "ulcer_not_healing", "opening_restricted",
                                    "previous_high"]},
    "persistence_days": 14,
    "followup_days": {"HIGH": 90, "MEDIUM": 120, "LOW": 365, "CANNOT_ASSESS": 30, "NEEDS_REVIEW": 7},
    "referral_due_days": 14,
    "rules": [
        # AI rules are suppressed when too many photos are unusable: R6 (CANNOT_ASSESS) decides instead.
        {"id": "R1", "level": "HIGH",
         "reason": "Suspicious patch detected by AI ({lesion_sites}) with other warning signs ({supporting_signs})",
         "when": {"all": [{"fact": "lesion_suspicious", "eq": True}, {"fact": "too_many_unusable", "eq": False},
                          {"fact": "has_supporting_signs", "eq": True}]}},
        {"id": "R1b", "level": "NEEDS_REVIEW",
         "reason": "AI flagged {lesion_sites} but there are no other warning signs - a specialist will check "
                   "the photos before any referral",
         "when": {"all": [{"fact": "lesion_suspicious", "eq": True}, {"fact": "too_many_unusable", "eq": False},
                          {"fact": "has_supporting_signs", "eq": False}]}},
        # high score on a photo that failed the quality check or looks unlike the training photos: not trusted for an
        # automatic referral -> retake, then a doctor checks (a LOW score on such a photo simply counts as low)
        {"id": "R1c", "level": "NEEDS_REVIEW",
         "reason": "AI score is high on an unclear photo ({unreliable_sites}) - it will be retaken or checked by a doctor",
         "when": {"all": [{"fact": "unreliable_flag", "eq": True}, {"fact": "too_many_unusable", "eq": False}]}},
        {"id": "R2", "level": "HIGH", "reason": "Restricted mouth opening ({opening_mm} mm) with burning - OSMF signs",
         "when": {"all": [{"fact": "opening_restricted", "eq": True}, {"fact": "burning", "eq": True}]}},
        {"id": "R3", "level": "HIGH",
         "reason": "Patch or sore present for {patch_days} days (≥ {persistence_days}) - must be checked",
         "when": {"all": [{"fact": "patch_days", "gte_fact": "persistence_days"}]}},
        {"id": "R4", "level": "HIGH",
         "reason": "Pain relieved by {masking_medication} but findings persist - relief can hide disease",
         "when": {"all": [{"fact": "masked_symptom", "eq": True}]}},
        {"id": "R5", "level": "HIGH", "reason": "Symptoms returned after previous high-risk screening",
         "when": {"all": [{"fact": "symptoms_returned", "eq": True}, {"fact": "previous_high", "eq": True}]}},
        {"id": "R6", "level": "CANNOT_ASSESS", "reason": "Photos could not be assessed reliably ({unusable_sites} sites)",
         "when": {"all": [{"fact": "ai_available", "eq": True}, {"fact": "too_many_unusable", "eq": True}]}},
        {"id": "R7", "level": "NEEDS_REVIEW", "reason": "AI result not available yet - never treated as low risk",
         "when": {"all": [{"fact": "ai_available", "eq": False}]}},
        {"id": "R8", "level": "MEDIUM", "reason": "High-risk habits ({habit_factors})",
         "when": {"all": [{"fact": "habit_level", "eq": "high"}]}},
        {"id": "R9", "level": "MEDIUM", "reason": "Borderline mouth opening ({opening_mm} mm)",
         "when": {"all": [{"fact": "opening_borderline", "eq": True}]}},
        {"id": "R10", "level": "MEDIUM", "reason": "Restricted mouth opening ({opening_mm} mm)",
         "when": {"all": [{"fact": "opening_restricted", "eq": True}]}},
    ],
    "actions": {
        "HIGH": ["create_referral", "specialist_review", "schedule_checkin", "schedule_followup", "notify_patient"],
        "CANNOT_ASSESS": ["specialist_review", "schedule_followup"],
        "NEEDS_REVIEW": ["retry_ai", "schedule_followup"],
        "MEDIUM": ["schedule_followup", "habit_counselling"],
        "LOW": ["schedule_followup", "habit_counselling"],
    },
}


# Decision logic v2 (docs/decision-logic-v2.md): every result answers three questions separately - findings today
# (AI score bands + clinical signs), exposure (habits only, never a finding) and confidence - then one action.
# Rules carry their own action text, follow-up interval and specialist-queue priority.
DEFAULT_RULE_SET: dict = {
    "name": "Arogya decision logic v2 (findings / exposure / confidence)",
    "habit_scoring": {                       # exposure: habits only (symptoms are clinical signs, counted once)
        "points": {"tobacco_smokeless": 3, "tobacco_smoked": 2, "tobacco_both": 3, "areca": 2,
                   "alcohol_daily": 2, "alcohol_weekly": 1, "alcohol_occasional": 0,
                   "years_medium": 1, "years_long": 2, "heavy_amount": 1},
        "years_medium": 10, "years_long": 20,
        "heavy_amount": {"smoked_per_day": 10, "chewed_per_day": 5},
        "former": {"recent_quit_years": 5, "recent_factor": 0.5, "old_points": 1},
        "levels": {"high": 4, "moderate": 2},
    },
    "mouth_opening": {"restricted_mm": 35.0, "borderline_mm": 40.0, "iris_mm": 11.7, "card_mm": 85.6,
                      "max_head_angle_deg": 12, "calibration": {"slope": 1.0, "intercept": 0.0}},
    "lesion": {"threshold": None, "threshold_source": "model_screening",
               "uncertain_from": 0.40,           # below: clean; up to the model threshold: uncertain
               "highly_suspicious": 0.90,        # at or above: referred directly (with the model's accuracy shown)
               "min_sites_for_cannot_assess": 3,
               # an AI flag plus ANY of these clinical signs refers the patient (habits are not a sign)
               "supporting_signs": ["patch_noticed", "ulcer_not_healing", "opening_restricted", "opening_borderline",
                                    "burning", "difficulty_opening", "previous_high"]},
    "model_evidence": {"name": "EfficientNetV2-S", "sensitivity": 0.909, "specificity": 0.950, "n": 346},
    "persistence_days": 14,
    "followup_days": {"HIGH": 90, "MEDIUM": 90, "LOW": 365, "CANNOT_ASSESS": 30, "NEEDS_REVIEW": 7},
    "referral_due_days": 14,
    "rules": [
        # A1 / A2: never low without an AI result; too many unusable photos -> retake
        {"id": "R7", "level": "NEEDS_REVIEW", "reason": "AI result not available yet - never treated as low risk",
         "action": "Wait for the AI result; the screening is re-checked automatically",
         "when": {"all": [{"fact": "ai_available", "eq": False}]}},
        {"id": "R6", "level": "CANNOT_ASSESS", "reason": "Photos could not be assessed reliably ({unusable_sites} sites)",
         "action": "Retake the photos",
         "when": {"all": [{"fact": "ai_available", "eq": True}, {"fact": "too_many_unusable", "eq": True}]}},
        # A4: strong clinical signs refer on their own
        {"id": "R2", "level": "HIGH", "reason": "Restricted mouth opening ({opening_mm} mm) with burning - OSMF signs",
         "action": "Refer to a specialist within {referral_due_days} days",
         "when": {"all": [{"fact": "opening_restricted", "eq": True}, {"fact": "burning", "eq": True}]}},
        {"id": "R3", "level": "HIGH",
         "reason": "Patch or sore present for {patch_days} days (14 or more) - must be checked",
         "action": "Refer to a specialist within {referral_due_days} days",
         "when": {"all": [{"fact": "patch_days", "gte_fact": "persistence_days"}]}},
        {"id": "R3b", "level": "HIGH", "reason": "Ulcer that is not healing - must be checked",
         "action": "Refer to a specialist within {referral_due_days} days",
         "when": {"all": [{"fact": "ulcer_not_healing", "eq": True}]}},
        {"id": "R4", "level": "HIGH",
         "reason": "Pain relieved by {masking_medication} but findings persist - relief can hide disease",
         "action": "Refer to a specialist within {referral_due_days} days",
         "when": {"all": [{"fact": "masked_symptom", "eq": True}]}},
        {"id": "R5", "level": "HIGH", "reason": "Symptoms returned after previous high-risk screening",
         "action": "Refer to a specialist within {referral_due_days} days",
         "when": {"all": [{"fact": "symptoms_returned", "eq": True}, {"fact": "previous_high", "eq": True}]}},
        # A5 / A6: the AI finding
        {"id": "R1", "level": "HIGH",
         "reason": "AI found a suspicious area ({lesion_sites}, {lesion_score_pct}%) with other warning signs "
                   "({supporting_signs})",
         "action": "Refer to a specialist within {referral_due_days} days",
         "when": {"all": [{"fact": "lesion_suspicious", "eq": True}, {"fact": "too_many_unusable", "eq": False},
                          {"fact": "has_supporting_signs", "eq": True}]}},
        {"id": "R1a", "level": "HIGH",
         "reason": "AI score {lesion_score_pct}% for a suspicious area ({high_sites}). {model_name} found such lesions "
                   "with {model_sensitivity}% sensitivity and {model_specificity}% specificity on {model_test_n} "
                   "held-out photos, so a score this high is referred directly",
         "action": "Refer to a specialist within {referral_due_days} days",
         "when": {"all": [{"fact": "lesion_highly_suspicious", "eq": True},
                          {"fact": "too_many_unusable", "eq": False}]}},
        # A7 / A8 / A9: the AI is not certain enough to refer on its own -> a specialist looks at the photos
        {"id": "R1c", "level": "NEEDS_REVIEW",
         "reason": "AI score is high on an unclear photo ({unreliable_sites}) - it will be retaken or checked by a doctor",
         "action": "Retake the photo; if it is still high a specialist checks it",
         "when": {"all": [{"fact": "unreliable_flag", "eq": True}, {"fact": "too_many_unusable", "eq": False}]}},
        {"id": "R1b", "level": "NEEDS_REVIEW", "review_priority": 30,
         "reason": "AI flagged {lesion_sites} ({lesion_score_pct}%) with no other warning sign - a specialist checks "
                   "the photos within 7 days{priority_note}",
         "action": "Specialist photo review within 7 days",
         "when": {"all": [{"fact": "lesion_suspicious", "eq": True}, {"fact": "lesion_highly_suspicious", "eq": False},
                          {"fact": "too_many_unusable", "eq": False}, {"fact": "has_supporting_signs", "eq": False}]}},
        {"id": "R1d", "level": "NEEDS_REVIEW", "review_priority": 35,
         "reason": "AI is unsure about {uncertain_sites} ({uncertain_score_pct}%) - a specialist checks the photos "
                   "within 14 days",
         "action": "Specialist photo review within 14 days",
         "when": {"all": [{"fact": "lesion_uncertain", "eq": True}, {"fact": "lesion_suspicious", "eq": False},
                          {"fact": "too_many_unusable", "eq": False}]}},
        # A10: weak clinical signs only -> watch and recheck
        {"id": "R11", "level": "MEDIUM", "followup_days": 14,
         "reason": "Patch noticed recently ({patch_days_text}) - it must be checked again after 2 weeks",
         "action": "Recheck in 2 weeks",
         "when": {"all": [{"fact": "patch_recent", "eq": True}]}},
        {"id": "R10", "level": "MEDIUM", "followup_days": 90, "reason": "Restricted mouth opening ({opening_mm} mm)",
         "action": "Recheck in 3 months",
         "when": {"all": [{"fact": "opening_restricted", "eq": True}]}},
        {"id": "R9", "level": "MEDIUM", "followup_days": 90, "reason": "Borderline mouth opening ({opening_mm} mm)",
         "action": "Recheck in 3 months",
         "when": {"all": [{"fact": "opening_borderline", "eq": True}]}},
        {"id": "R12", "level": "MEDIUM", "followup_days": 90,
         "reason": "Burning with spicy food - an early sign worth watching",
         "action": "Recheck in 3 months",
         "when": {"all": [{"fact": "burning", "eq": True}]}},
        {"id": "R13", "level": "MEDIUM", "followup_days": 90, "reason": "Difficulty opening the mouth reported",
         "action": "Recheck in 3 months",
         "when": {"all": [{"fact": "difficulty_opening", "eq": True}]}},
        # A11 / A12: exposure (habits) - never a finding; changes counselling and the re-screen interval
        {"id": "E1", "level": "LOW", "followup_days": 180,
         "reason": "High exposure: {habit_factors} - quit-tobacco counselling advised",
         "action": "No suspicious signs today. Quit-tobacco counselling, re-screen in 6 months",
         "when": {"all": [{"fact": "habit_level", "eq": "high"}]}},
        {"id": "E2", "level": "LOW", "followup_days": 365,
         "reason": "Moderate exposure: {habit_factors} - counselling advised",
         "action": "No suspicious signs today. Counselling, re-screen in 12 months",
         "when": {"all": [{"fact": "habit_level", "eq": "moderate"}]}},
    ],
    "actions": {
        "HIGH": ["create_referral", "specialist_review", "schedule_checkin", "schedule_followup", "notify_patient"],
        "CANNOT_ASSESS": ["specialist_review", "schedule_followup"],
        "NEEDS_REVIEW": ["retry_ai", "schedule_followup"],
        "MEDIUM": ["schedule_followup", "habit_counselling"],
        "LOW": ["schedule_followup", "habit_counselling"],
    },
    "default_action": "Routine re-screen in 12 months",
}


# ───────────────────────── validation of proposed rule sets ─────────────────────────
class Condition(BaseModel):
    fact: str
    eq: Any = None
    ne: Any = None
    gte: float | None = None
    lte: float | None = None
    gt: float | None = None
    lt: float | None = None
    gte_fact: str | None = None
    is_in: list | None = Field(default=None, alias="in")


class Rule(BaseModel):
    id: str
    level: str
    reason: str
    when: dict

    @field_validator("level")
    @classmethod
    def _lvl(cls, v):
        if v not in SEVERITY:
            raise ValueError(f"level must be one of {list(SEVERITY)}")
        return v

    @field_validator("when")
    @classmethod
    def _when(cls, v):
        if not (set(v) <= {"all", "any"}) or not v:
            raise ValueError("'when' must contain 'all' and/or 'any'")
        for group in v.values():
            for c in group:
                Condition.model_validate(c)
        return v


class RuleSetDef(BaseModel):
    name: str
    habit_scoring: dict
    mouth_opening: dict
    lesion: dict
    persistence_days: int = 14
    followup_days: dict
    referral_due_days: int = 14
    rules: list[Rule]
    actions: dict

    @field_validator("lesion")
    @classmethod
    def _known_signs(cls, v):
        unknown = set(v.get("supporting_signs") or []) - set(SUPPORTING_SIGNS)
        if unknown:
            raise ValueError(f"unknown supporting_signs {sorted(unknown)}; allowed: {sorted(SUPPORTING_SIGNS)}")
        return v

    @field_validator("rules")
    @classmethod
    def _must_keep_failsafe(cls, rules):
        # Safety invariant: a rule set may not remove the "AI missing => NEEDS_REVIEW" fail-safe.
        ok = any(r.level in ("NEEDS_REVIEW", "HIGH", "CANNOT_ASSESS")
                 and any(c.get("fact") == "ai_available" and c.get("eq") is False
                         for c in r.when.get("all", []) + r.when.get("any", [])) for r in rules)
        if not ok:
            raise ValueError("rule set must keep the fail-safe: ai_available == false must not become LOW")
        return rules


def rule_set_sha(defn: dict) -> str:
    return hashlib.sha256(json.dumps(defn, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ───────────────────────── evaluation ─────────────────────────
def _cond_ok(c: dict, facts: dict) -> bool:
    v = facts.get(c["fact"])
    if "eq" in c and v != c["eq"]:
        return False
    if "ne" in c and v == c["ne"]:
        return False
    for op, fn in (("gte", lambda a, b: a >= b), ("lte", lambda a, b: a <= b), ("gt", lambda a, b: a > b),
                   ("lt", lambda a, b: a < b)):
        if op in c:
            if v is None or not fn(v, c[op]):
                return False
    if "gte_fact" in c:
        other = facts.get(c["gte_fact"])
        if v is None or other is None or v < other:
            return False
    if "in" in c and v not in c["in"]:
        return False
    return True


def _match(when: dict, facts: dict) -> bool:
    ok_all = all(_cond_ok(c, facts) for c in when.get("all", []))
    ok_any = True if "any" not in when else any(_cond_ok(c, facts) for c in when["any"])
    return ok_all and ok_any


class _SafeDict(dict):
    def __missing__(self, k):
        return "?"


def evaluate(rule_set: dict, facts: dict) -> dict:
    matched = [r for r in rule_set["rules"] if _match(r["when"], facts)]
    level = max((r["level"] for r in matched), key=lambda lv: SEVERITY[lv], default="LOW")
    reasons = [{"rule": r["id"], "level": r["level"], "text": r["reason"].format_map(_SafeDict(facts))}
               for r in sorted(matched, key=lambda r: -SEVERITY[r["level"]])]
    if not reasons:
        reasons = [{"rule": "DEFAULT", "level": "LOW", "text": "No warning signs found"}]
    at_level = [r for r in matched if r["level"] == level]
    # rules may set their own follow-up interval / queue priority; the most urgent one at the final level wins
    followups = [int(r["followup_days"]) for r in at_level if r.get("followup_days") is not None]
    priorities = [int(r["review_priority"]) for r in at_level if r.get("review_priority") is not None]
    due = rule_set.get("referral_due_days", 14)
    fmt = _SafeDict({**facts, "referral_due_days": due})
    top = next((r for r in sorted(matched, key=lambda r: -SEVERITY[r["level"]]) if r.get("action")), None)
    action = top["action"].format_map(fmt) if top else rule_set.get("default_action", "Routine re-screen")
    out = {"risk_level": level, "reasons": reasons, "actions": rule_set["actions"].get(level, []),
           "followup_days": min(followups) if followups else rule_set["followup_days"].get(level, 365),
           "referral_due_days": due,
           "disclaimer": "Screening aid only - not a diagnosis. A specialist confirms every high-risk result."}
    if priorities:
        out["review_priority"] = min(priorities)
    if "summary_ready" in facts:                       # v2 facts: findings / exposure / confidence / action
        out["summary"] = summarize(facts, level, action)
    return out


def summarize(facts: dict, level: str, action: str) -> dict:
    """The four lines on the result card. Deterministic, built only from facts (no free text generation)."""
    strong = facts.get("strong_sign_list") or []
    weak = facts.get("weak_sign_list") or []
    if not facts.get("ai_available"):
        findings = {"status": "pending", "text": "Waiting for the AI result"}
    elif facts.get("lesion_suspicious"):
        findings = {"status": "suspicious",
                    "text": f"Suspicious area: {facts['lesion_sites']} (AI {facts['lesion_score_pct']}%)"}
    elif strong:
        findings = {"status": "clinical", "text": "Clinical warning sign: " + ", ".join(strong)}
    elif facts.get("lesion_uncertain") or facts.get("unreliable_flag"):
        sites = facts.get("uncertain_sites") if facts.get("lesion_uncertain") else facts.get("unreliable_sites")
        findings = {"status": "uncertain", "text": f"Uncertain: {sites} - a doctor checks the photo"}
    elif weak:
        findings = {"status": "watch", "text": "No suspicious area. To watch: " + ", ".join(weak)}
    else:
        findings = {"status": "none", "text": "No suspicious signs today"}
    if strong and findings["status"] == "suspicious":
        findings["text"] += "; " + ", ".join(strong)
    lvl = facts.get("habit_level", "low")
    exposure = {"level": lvl, "text": f"{lvl.capitalize()}" + (f" ({facts['habit_factors']})"
                                                               if facts.get("habit_factors") not in (None, "none") else "")}
    if not facts.get("ai_available"):
        confidence = {"level": "pending", "text": "Pending - AI result not available yet"}
    elif facts.get("too_many_unusable"):
        confidence = {"level": "cannot_assess", "text": f"Cannot assess - {facts['unusable_sites']} photos unusable"}
    elif facts.get("unreliable_flag"):
        confidence = {"level": "limited", "text": f"Limited - unclear photo ({facts['unreliable_sites']})"}
    else:
        confidence = {"level": "good",
                      "text": f"Good ({facts.get('usable_sites', 0)} of {facts.get('total_sites', 0)} photos clear)"}
    return {"findings": findings, "exposure": exposure, "confidence": confidence,
            "action": {"level": level, "text": action}}


def build_facts(*, rule_set: dict, habit_level: str, habit_factors: list[str], symptoms: dict,
                opening_mm: float | None, ai: dict | None, timeline: dict) -> dict:
    """ai = {"available": bool, "max_prob": float, "threshold": float, "site_probs": {site: p},
             "unusable_sites": [...], "ood_sites": [...]}
    timeline = {"patch_days": int|None, "masking_medication": str|None, "pain_relieved": bool,
                "symptoms_returned": bool, "previous_high": bool}"""
    mo = rule_set["mouth_opening"]
    ai = ai or {"available": False}
    thr = rule_set["lesion"].get("threshold") or ai.get("threshold") or 0.5
    site_probs = ai.get("site_probs") or {}
    suspicious_sites = [s for s, p in site_probs.items() if p is not None and p >= thr]
    lesion_suspicious = bool(ai.get("available")) and bool(suspicious_sites)
    restricted = opening_mm is not None and opening_mm < mo["restricted_mm"]
    borderline = opening_mm is not None and mo["restricted_mm"] <= opening_mm < mo["borderline_mm"]
    # "unusable" = no score at all (photo missing / could not be read). Unclear or unusual photos still have a score:
    # a low one counts as low, a high one is an "unreliable flag" (rule R1c), see pipeline.pick_sites.
    unusable = sorted(set(ai.get("unusable_sites") or []))
    unreliable = sorted((ai.get("unreliable_flag_sites") or {}).keys())
    finding_persists = lesion_suspicious or restricted or bool(symptoms.get("patch_noticed"))
    masked = bool(timeline.get("pain_relieved") and timeline.get("masking_medication") and finding_persists)
    patch_days = timeline.get("patch_days")
    if patch_days is None and symptoms.get("patch_duration_days") is not None:
        patch_days = int(symptoms["patch_duration_days"])
    # warning signs that, together with an AI flag, justify an automatic referral (names listed in the rule set)
    signs = {"habit_high": habit_level == "high", "patch_noticed": bool(symptoms.get("patch_noticed")),
             "ulcer_not_healing": bool(symptoms.get("ulcer_not_healing")), "opening_restricted": restricted,
             "burning": bool(symptoms.get("burning")), "previous_high": bool(timeline.get("previous_high"))}
    signs.update({"opening_borderline": borderline, "difficulty_opening": bool(symptoms.get("difficulty_opening"))})
    wanted = rule_set["lesion"].get("supporting_signs", list(SUPPORTING_SIGNS))
    present = [n for n in wanted if signs.get(n)]

    # v2: AI score bands on reliable sites (clean / uncertain / suspicious / highly suspicious)
    lesion_cfg = rule_set["lesion"]
    unc_from = lesion_cfg.get("uncertain_from")
    high_from = lesion_cfg.get("highly_suspicious")
    avail = bool(ai.get("available"))
    reliable = {s: p for s, p in site_probs.items() if p is not None}
    top = max(reliable.values()) if reliable else None
    high_sites = [s for s, p in reliable.items() if high_from is not None and p >= high_from]
    uncertain = {s: p for s, p in reliable.items() if unc_from is not None and unc_from <= p < thr}
    nice = lambda xs: ", ".join(x.replace("_", " ") for x in xs) or "none"  # noqa: E731
    persist = rule_set.get("persistence_days", 14)
    patch_recent = bool(symptoms.get("patch_noticed")) and (patch_days is None or patch_days < persist)
    ev = {**(rule_set.get("model_evidence") or {}), **(ai.get("model_evidence") or {})}
    habit_high = habit_level == "high"
    strong = [label for cond, label in (
        (patch_days is not None and patch_days >= persist, f"patch or sore for {patch_days} days"),
        (bool(symptoms.get("ulcer_not_healing")), "ulcer not healing"),
        (restricted and bool(symptoms.get("burning")), "restricted opening with burning (OSMF signs)"),
        (masked, "symptoms hidden by medicine"),
        (bool(timeline.get("symptoms_returned")) and bool(timeline.get("previous_high")), "symptoms returned"),
    ) if cond]
    weak = [label for cond, label in (
        (patch_recent, "patch noticed recently"),
        (restricted and not symptoms.get("burning"), f"restricted opening ({opening_mm} mm)"),
        (borderline, f"borderline opening ({opening_mm} mm)"),
        (bool(symptoms.get("burning")) and not restricted, "burning with spicy food"),
        (bool(symptoms.get("difficulty_opening")), "difficulty opening the mouth"),
    ) if cond]
    v2 = {
        "lesion_highly_suspicious": avail and bool(high_sites),
        "high_sites": nice(high_sites),
        "lesion_uncertain": avail and bool(uncertain),
        "uncertain_sites": nice(list(uncertain)),
        "uncertain_score_pct": round(max(uncertain.values()) * 100) if uncertain else 0,
        "lesion_score_pct": round(top * 100) if top is not None else 0,
        "patch_recent": patch_recent,
        "patch_days_text": f"{patch_days} days ago" if patch_days is not None else "duration not known",
        "ulcer_not_healing": bool(symptoms.get("ulcer_not_healing")),
        "difficulty_opening": bool(symptoms.get("difficulty_opening")),
        "priority_note": " (moved up the queue: high exposure)" if habit_high else "",
        "model_name": ev.get("name", "the AI model"),
        "model_sensitivity": round(float(ev.get("sensitivity", 0)) * 100, 1),
        "model_specificity": round(float(ev.get("specificity", 0)) * 100, 1),
        "model_test_n": ev.get("n", "?"),
        "strong_sign_list": strong,
        "weak_sign_list": weak,
        "usable_sites": len(reliable),
        "total_sites": len(reliable) + len(unusable) + len(unreliable),
    }
    if unc_from is not None:
        v2["summary_ready"] = True
    return {
        **v2,
        "ai_available": bool(ai.get("available")),
        "lesion_score": ai.get("max_prob"),
        "lesion_threshold": thr,
        "lesion_suspicious": lesion_suspicious,
        "lesion_sites": ", ".join(s.replace("_", " ") for s in suspicious_sites) or "none",
        "lesion_site_count": len(suspicious_sites),
        "suspicious_sites": suspicious_sites,
        "unreliable_flag": bool(ai.get("available")) and bool(unreliable),
        "unreliable_site_list": unreliable,
        "unreliable_sites": ", ".join(s.replace("_", " ") for s in unreliable) or "none",
        "has_supporting_signs": bool(present),
        "supporting_signs": ", ".join(SUPPORTING_SIGNS.get(n, n) for n in present) or "none",
        "unusable_sites": len(unusable),
        "too_many_unusable": len(unusable) >= rule_set["lesion"].get("min_sites_for_cannot_assess", 3),
        "opening_mm": opening_mm,
        "opening_restricted": restricted,
        "opening_borderline": borderline,
        "burning": bool(symptoms.get("burning")),
        "habit_level": habit_level,
        "habit_factors": ", ".join(habit_factors) or "none",
        "patch_days": patch_days,
        "persistence_days": rule_set.get("persistence_days", 14),
        "masked_symptom": masked,
        "masking_medication": timeline.get("masking_medication") or "medication",
        "symptoms_returned": bool(timeline.get("symptoms_returned")),
        "previous_high": bool(timeline.get("previous_high")),
    }
