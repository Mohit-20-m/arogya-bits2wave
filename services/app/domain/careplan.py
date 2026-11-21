"""After the result: (1) what the patient's habits mean for the future, (2) a personal roadmap of next steps.

Deterministic: built only from the decision, the answers and an approved content library (no free text is generated).
Facts are population-level and sourced; nothing here predicts an individual's future ("you will get cancer in X
years" is not knowable). Content version is stored with every roadmap; Kannada text needs a native speaker's check
and all content an oral-medicine specialist's review before use with real patients.
"""
from __future__ import annotations

from datetime import date, timedelta

from .careplan_hi import HI, SPEAK_HOW

CONTENT_VERSION = "care-content-1 (2026-11-21, awaiting clinician review)"

SOURCES = {
    "iarc_tobacco": "IARC Monographs vol. 89 / 100E: smokeless tobacco causes oral cancer in humans (Group 1)",
    "iarc_areca": "IARC Monographs vol. 85 / 100E: areca nut and betel quid cause oral cancer in humans (Group 1)",
    "osmf": "Oral submucous fibrosis is caused mainly by chewing areca nut (WHO Collaborating Centre, 2020 review)",
    "alcohol": "IARC: tobacco and alcohol together raise the risk of mouth cancer more than either alone",
    "cdc_quit": "US CDC: within 5 years of quitting smoking, the risk of mouth and throat cancer is cut in half",
    "early": "Mouth cancers found early are much easier to treat than those found late (WHO)",
}


def _t(en: str, kn: str) -> dict:
    return {"en": en, "kn": kn, "hi": HI.get(en, "")}


# ───────────────────────── 1. risk: what continuing means ─────────────────────────
HEADLINE = {
    "HIGH": _t("First: see the specialist. Then: what your habits mean for your mouth.",
               "ಮೊದಲು ತಜ್ಞರನ್ನು ಭೇಟಿ ಮಾಡಿ. ನಂತರ: ನಿಮ್ಮ ಅಭ್ಯಾಸಗಳು ಬಾಯಿಗೆ ಏನು ಮಾಡುತ್ತವೆ."),
    "NEEDS_REVIEW": _t("A doctor is checking your photos. Meanwhile, what your habits mean for your mouth.",
                       "ವೈದ್ಯರು ನಿಮ್ಮ ಫೋಟೋಗಳನ್ನು ಪರಿಶೀಲಿಸುತ್ತಿದ್ದಾರೆ. ಅಲ್ಲಿಯವರೆಗೆ, ನಿಮ್ಮ ಅಭ್ಯಾಸಗಳ ಪರಿಣಾಮ."),
    "CANNOT_ASSESS": _t("The photos need to be taken again. Meanwhile, what your habits mean for your mouth.",
                        "ಫೋಟೋಗಳನ್ನು ಮತ್ತೆ ತೆಗೆಯಬೇಕು. ಅಲ್ಲಿಯವರೆಗೆ, ನಿಮ್ಮ ಅಭ್ಯಾಸಗಳ ಪರಿಣಾಮ."),
    "MEDIUM": _t("One sign to watch. What happens if your habits continue - and if you stop.",
                 "ಗಮನಿಸಬೇಕಾದ ಒಂದು ಲಕ್ಷಣ. ಅಭ್ಯಾಸ ಮುಂದುವರಿದರೆ ಏನಾಗುತ್ತದೆ - ಬಿಟ್ಟರೆ ಏನಾಗುತ್ತದೆ."),
    "LOW_EXPOSED": _t("Your mouth looks healthy today. Your habits can change that over the years.",
                      "ಇಂದು ನಿಮ್ಮ ಬಾಯಿ ಆರೋಗ್ಯವಾಗಿದೆ. ನಿಮ್ಮ ಅಭ್ಯಾಸಗಳು ವರ್ಷಗಳಲ್ಲಿ ಇದನ್ನು ಬದಲಿಸಬಹುದು."),
    "LOW": _t("Your mouth looks healthy today - keep it that way.",
              "ಇಂದು ನಿಮ್ಮ ಬಾಯಿ ಆರೋಗ್ಯವಾಗಿದೆ - ಹಾಗೆಯೇ ಉಳಿಸಿಕೊಳ್ಳಿ."),
}

HABIT_FACTS = {
    "smokeless": [(_t("Gutka, khaini and tobacco in paan are proven to cause mouth cancer.",
                      "ಗುಟ್ಕಾ, ಖೈನಿ ಮತ್ತು ಪಾನ್‌ನಲ್ಲಿನ ತಂಬಾಕು ಬಾಯಿ ಕ್ಯಾನ್ಸರ್ ಉಂಟುಮಾಡುತ್ತದೆ ಎಂದು ಸಾಬೀತಾಗಿದೆ."), "iarc_tobacco"),
                  (_t("Where the quid rests, the cheek lining is damaged again and again - white patches often start there.",
                      "ತಂಬಾಕು ಇಡುವ ಜಾಗದಲ್ಲಿ ಕೆನ್ನೆಯ ಒಳಪದರ ಮತ್ತೆ ಮತ್ತೆ ಹಾನಿಯಾಗುತ್ತದೆ - ಬಿಳಿ ಕಲೆ ಅಲ್ಲಿಂದಲೇ ಶುರುವಾಗುತ್ತದೆ."), "iarc_tobacco")],
    "smoked": [(_t("Beedi and cigarette smoke damages the lining of the mouth and throat.",
                   "ಬೀಡಿ ಮತ್ತು ಸಿಗರೇಟ್ ಹೊಗೆ ಬಾಯಿ ಮತ್ತು ಗಂಟಲಿನ ಒಳಪದರವನ್ನು ಹಾನಿ ಮಾಡುತ್ತದೆ."), "cdc_quit")],
    "areca": [(_t("Areca nut on its own - even without tobacco - is proven to cause mouth cancer.",
                  "ತಂಬಾಕು ಇಲ್ಲದಿದ್ದರೂ ಅಡಿಕೆ ಮಾತ್ರವೇ ಬಾಯಿ ಕ್ಯಾನ್ಸರ್ ಉಂಟುಮಾಡುತ್ತದೆ ಎಂದು ಸಾಬೀತಾಗಿದೆ."), "iarc_areca"),
              (_t("Areca slowly stiffens the inside of the mouth (submucous fibrosis): burning first, then the mouth "
                  "opens less and less.",
                  "ಅಡಿಕೆ ಬಾಯಿಯ ಒಳಭಾಗವನ್ನು ನಿಧಾನವಾಗಿ ಗಟ್ಟಿಗೊಳಿಸುತ್ತದೆ: ಮೊದಲು ಉರಿ, ನಂತರ ಬಾಯಿ ಕಡಿಮೆ ತೆರೆಯುತ್ತದೆ."), "osmf")],
    "alcohol": [(_t("Drinking alcohol as well as using tobacco raises the risk more than either alone.",
                    "ತಂಬಾಕಿನ ಜೊತೆ ಮದ್ಯ ಸೇವನೆ ಅಪಾಯವನ್ನು ಇನ್ನಷ್ಟು ಹೆಚ್ಚಿಸುತ್ತದೆ."), "alcohol")],
}

# stages if habits continue (population pattern, not a personal prediction)
STAGES = {
    "areca": [("Months", _t("Burning with spicy food, blanching of the cheeks", "ಖಾರ ತಿಂದಾಗ ಉರಿ, ಕೆನ್ನೆ ಬಿಳಿಚುವುದು")),
              ("Years", _t("Stiff bands inside the cheeks; the mouth opens less", "ಕೆನ್ನೆಯೊಳಗೆ ಗಟ್ಟಿ ಪಟ್ಟಿಗಳು; ಬಾಯಿ ಕಡಿಮೆ ತೆರೆಯುತ್ತದೆ")),
              ("Many years", _t("Risk of mouth cancer rises, especially with tobacco", "ಬಾಯಿ ಕ್ಯಾನ್ಸರ್ ಅಪಾಯ ಹೆಚ್ಚುತ್ತದೆ, ವಿಶೇಷವಾಗಿ ತಂಬಾಕಿನೊಂದಿಗೆ"))],
    "tobacco": [("Months", _t("Stained teeth, gum and cheek irritation", "ಕಲೆಯಾದ ಹಲ್ಲು, ಒಸಡು ಮತ್ತು ಕೆನ್ನೆ ಕಿರಿಕಿರಿ")),
                ("Years", _t("White or red patches where tobacco touches the mouth", "ತಂಬಾಕು ತಾಗುವ ಜಾಗದಲ್ಲಿ ಬಿಳಿ ಅಥವಾ ಕೆಂಪು ಕಲೆಗಳು")),
                ("Many years", _t("Some patches turn into mouth cancer", "ಕೆಲವು ಕಲೆಗಳು ಬಾಯಿ ಕ್ಯಾನ್ಸರ್ ಆಗುತ್ತವೆ"))],
}

IF_QUIT = {
    "smoked": (_t("Within 5 years of stopping smoking, the risk of mouth cancer is cut in half.",
                  "ಧೂಮಪಾನ ಬಿಟ್ಟ 5 ವರ್ಷಗಳಲ್ಲಿ ಬಾಯಿ ಕ್ಯಾನ್ಸರ್ ಅಪಾಯ ಅರ್ಧಕ್ಕೆ ಇಳಿಯುತ್ತದೆ."), "cdc_quit"),
    "any": (_t("Stopping now lowers the risk year after year, and early patches can heal once the habit stops.",
               "ಈಗ ಬಿಟ್ಟರೆ ಅಪಾಯ ವರ್ಷದಿಂದ ವರ್ಷಕ್ಕೆ ಕಡಿಮೆಯಾಗುತ್ತದೆ; ಅಭ್ಯಾಸ ನಿಂತರೆ ಆರಂಭಿಕ ಕಲೆಗಳು ವಾಸಿಯಾಗಬಹುದು."), "early"),
    "check": (_t("Whatever you decide: see a doctor early for any patch, sore or stiffness - early is easier to treat.",
                 "ಯಾವುದೇ ಕಲೆ, ಹುಣ್ಣು ಅಥವಾ ಗಟ್ಟಿತನಕ್ಕೆ ಬೇಗ ವೈದ್ಯರನ್ನು ಕಾಣಿ - ಬೇಗ ಕಂಡರೆ ಚಿಕಿತ್ಸೆ ಸುಲಭ."), "early"),
}


def _habit_kinds(h: dict) -> dict:
    """current habit kinds: smokeless / smoked / areca / alcohol."""
    out = {}
    if h.get("tobacco") and (h.get("tobacco_status") or "current") == "current":
        t = h.get("tobacco_type") or "smokeless"
        if t in ("smokeless", "both", "none"):
            out["smokeless"] = h.get("tobacco_years")
        if t in ("smoked", "both"):
            out["smoked"] = h.get("tobacco_years")
    if h.get("areca") and (h.get("areca_status") or "current") == "current":
        out["areca"] = h.get("areca_years")
    if h.get("alcohol") and (h.get("alcohol_frequency") or "") in ("daily", "weekly"):
        out["alcohol"] = None
    return out


def build_risk(level: str, exposure: str, habits: dict) -> dict:
    kinds = _habit_kinds(habits)
    former = any((habits.get(f"{k}_status") == "former") for k in ("tobacco", "areca"))
    key = level if level != "LOW" else ("LOW_EXPOSED" if kinds else "LOW")
    facts = [{"habit": k, "text": t, "source": SOURCES[src]} for k in kinds for t, src in HABIT_FACTS.get(k, [])]
    stages = []
    if "areca" in kinds:
        stages.append({"habit": "areca", "label": _t("If areca chewing continues", "ಅಡಿಕೆ ಮುಂದುವರಿದರೆ"),
                       "steps": [{"when": w, "text": t} for w, t in STAGES["areca"]]})
    if "smokeless" in kinds or "smoked" in kinds:
        stages.append({"habit": "tobacco", "label": _t("If tobacco use continues", "ತಂಬಾಕು ಮುಂದುವರಿದರೆ"),
                       "steps": [{"when": w, "text": t} for w, t in STAGES["tobacco"]]})
    quit = []
    if "smoked" in kinds:
        quit.append({"text": IF_QUIT["smoked"][0], "source": SOURCES[IF_QUIT["smoked"][1]]})
    if kinds:
        quit.append({"text": IF_QUIT["any"][0], "source": SOURCES[IF_QUIT["any"][1]]})
    quit.append({"text": IF_QUIT["check"][0], "source": SOURCES[IF_QUIT["check"][1]]})
    # illustrative curves (relative, unit-less): rising if continuing, falling after quitting - NOT a prediction
    weight = {"high": 1.0, "moderate": 0.7, "low": 0.35}.get(exposure, 0.35) if kinds else 0.15
    years = [0, 2, 4, 6, 8, 10]
    curve = [{"year": y, "continue": round(weight * (1 + 0.22 * y) * 10, 1),
              "quit": round(weight * max(0.35, 1 - 0.09 * y) * 10, 1)} for y in years]
    return {"level": level, "headline": HEADLINE[key], "habits": list(kinds), "former": former,
            "facts": facts, "stages": stages, "ifQuit": quit, "curve": curve if kinds else [],
            "disclaimer": _t("These are facts about many people with these habits, not a prediction about you.",
                             "ಇವು ಈ ಅಭ್ಯಾಸವಿರುವ ಅನೇಕ ಜನರ ಬಗ್ಗೆ ತಿಳಿದಿರುವ ಸಂಗತಿಗಳು, ನಿಮ್ಮ ಬಗ್ಗೆ ಭವಿಷ್ಯವಾಣಿ ಅಲ್ಲ.")}


# ───────────────────────── 2. personal roadmap ─────────────────────────
# step id -> phase, icon, title, why, how (all bilingual)
STEPS = {
    "see_specialist": ("medical", "stethoscope",
                       _t("See the specialist", "ತಜ್ಞರನ್ನು ಭೇಟಿ ಮಾಡಿ"),
                       _t("A specialist must examine the finding - early is much easier to treat.",
                          "ತಜ್ಞರು ಪರೀಕ್ಷಿಸಬೇಕು - ಬೇಗ ಕಂಡರೆ ಚಿಕಿತ್ಸೆ ಸುಲಭ."),
                       _t("Go to {facility} by {due}. Take the referral slip and your health card.",
                          "{due} ಒಳಗೆ {facility} ಗೆ ಹೋಗಿ. ರೆಫರಲ್ ಚೀಟಿ ಮತ್ತು ಆರೋಗ್ಯ ಕಾರ್ಡ್ ತೆಗೆದುಕೊಳ್ಳಿ.")),
    "doctor_review": ("medical", "stethoscope",
                      _t("Wait for the doctor's photo review", "ವೈದ್ಯರ ಫೋಟೋ ಪರಿಶೀಲನೆಗಾಗಿ ಕಾಯಿರಿ"),
                      _t("A doctor looks at your photos before any trip is needed.",
                         "ಪ್ರಯಾಣದ ಮೊದಲು ವೈದ್ಯರು ನಿಮ್ಮ ಫೋಟೋಗಳನ್ನು ನೋಡುತ್ತಾರೆ."),
                      _t("Your ASHA will tell you the result within a week.",
                         "ಒಂದು ವಾರದೊಳಗೆ ನಿಮ್ಮ ಆಶಾ ಕಾರ್ಯಕರ್ತೆ ಫಲಿತಾಂಶ ತಿಳಿಸುತ್ತಾರೆ.")),
    "retake_photos": ("medical", "camera",
                      _t("Retake the photos", "ಫೋಟೋಗಳನ್ನು ಮತ್ತೆ ತೆಗೆಯಿರಿ"),
                      _t("Some photos were not clear enough to judge.", "ಕೆಲವು ಫೋಟೋಗಳು ಸ್ಪಷ್ಟವಾಗಿರಲಿಲ್ಲ."),
                      _t("Your ASHA will visit again to take them.", "ನಿಮ್ಮ ಆಶಾ ಮತ್ತೆ ಬಂದು ತೆಗೆಯುತ್ತಾರೆ.")),
    "recheck_patch": ("medical", "calendar",
                      _t("Recheck the patch in 2 weeks", "2 ವಾರಗಳಲ್ಲಿ ಕಲೆಯನ್ನು ಮತ್ತೆ ಪರೀಕ್ಷಿಸಿ"),
                      _t("A patch that is still there after 2 weeks must be seen by a specialist.",
                         "2 ವಾರಗಳ ನಂತರವೂ ಇರುವ ಕಲೆಯನ್ನು ತಜ್ಞರು ನೋಡಬೇಕು."),
                      _t("If it has not gone, your ASHA arranges the referral.",
                         "ಅದು ಹೋಗದಿದ್ದರೆ ನಿಮ್ಮ ಆಶಾ ರೆಫರಲ್ ಏರ್ಪಡಿಸುತ್ತಾರೆ.")),
    "quit_date": ("quit", "flag",
                  _t("Choose your quit date", "ಬಿಡುವ ದಿನವನ್ನು ಆಯ್ಕೆಮಾಡಿ"),
                  _t("A fixed date makes quitting real - most people who succeed pick a day.",
                     "ನಿಗದಿತ ದಿನ ಇದ್ದರೆ ಬಿಡುವುದು ಸುಲಭ."),
                  _t("Pick a day within 2 weeks and tell your family.", "2 ವಾರಗಳೊಳಗಿನ ದಿನ ಆರಿಸಿ, ಕುಟುಂಬಕ್ಕೆ ತಿಳಿಸಿ.")),
    "quitline": ("quit", "phone",
                 _t("Call the free quitline", "ಉಚಿತ ಕ್ವಿಟ್‌ಲೈನ್‌ಗೆ ಕರೆ ಮಾಡಿ"),
                 _t("Trained counsellors help you plan and stay quit, in your language.",
                    "ತರಬೇತಿ ಪಡೆದ ಸಲಹೆಗಾರರು ನಿಮ್ಮ ಭಾಷೆಯಲ್ಲಿ ಸಹಾಯ ಮಾಡುತ್ತಾರೆ."),
                 _t("National Tobacco Quitline: 1800-11-2356 (free).", "ರಾಷ್ಟ್ರೀಯ ತಂಬಾಕು ಕ್ವಿಟ್‌ಲೈನ್: 1800-11-2356 (ಉಚಿತ).")),
    "swap_chew": ("quit", "leaf",
                  _t("Swap the after-meal chew", "ಊಟದ ನಂತರದ ಜಗಿತವನ್ನು ಬದಲಿಸಿ"),
                  _t("Cravings come at the same times every day - after meals, with tea, with friends.",
                     "ಬಯಕೆ ಪ್ರತಿದಿನ ಅದೇ ಸಮಯದಲ್ಲಿ ಬರುತ್ತದೆ - ಊಟದ ನಂತರ, ಚಹಾದೊಂದಿಗೆ, ಸ್ನೇಹಿತರೊಂದಿಗೆ."),
                  _t("Keep saunf (fennel), cardamom or sugar-free gum ready; drink water; walk for 5 minutes.",
                     "ಸೋಂಪು, ಏಲಕ್ಕಿ ಅಥವಾ ಸಕ್ಕರೆ ರಹಿತ ಗಮ್ ಇಟ್ಟುಕೊಳ್ಳಿ; ನೀರು ಕುಡಿಯಿರಿ; 5 ನಿಮಿಷ ನಡೆಯಿರಿ.")),
    "smoke_free_home": ("quit", "home",
                        _t("Make home smoke-free", "ಮನೆಯನ್ನು ಹೊಗೆ ರಹಿತವಾಗಿಸಿ"),
                        _t("Fewer cues at home means fewer cravings - and protects your family.",
                           "ಮನೆಯಲ್ಲಿ ಕಡಿಮೆ ಪ್ರಚೋದನೆ ಎಂದರೆ ಕಡಿಮೆ ಬಯಕೆ - ಕುಟುಂಬವೂ ಸುರಕ್ಷಿತ."),
                        _t("Remove beedis, lighters and ashtrays; never smoke indoors.",
                           "ಬೀಡಿ, ಲೈಟರ್ ತೆಗೆದುಹಾಕಿ; ಮನೆಯೊಳಗೆ ಎಂದೂ ಧೂಮಪಾನ ಮಾಡಬೇಡಿ.")),
    "ask_nrt": ("quit", "pill",
                _t("Ask about nicotine replacement", "ನಿಕೋಟಿನ್ ಬದಲಿ ಚಿಕಿತ್ಸೆ ಬಗ್ಗೆ ಕೇಳಿ"),
                _t("Heavy daily use is hard to stop alone; nicotine gum or patches ease withdrawal.",
                   "ಹೆಚ್ಚಿನ ಬಳಕೆ ಒಬ್ಬರೇ ನಿಲ್ಲಿಸುವುದು ಕಷ್ಟ; ನಿಕೋಟಿನ್ ಗಮ್ ಅಥವಾ ಪ್ಯಾಚ್ ಸಹಾಯ ಮಾಡುತ್ತದೆ."),
                _t("Ask the doctor or pharmacist which is right for you.", "ಯಾವುದು ಸೂಕ್ತ ಎಂದು ವೈದ್ಯರು ಅಥವಾ ಔಷಧಿಕಾರರನ್ನು ಕೇಳಿ.")),
    "mouth_exercise": ("mouth", "move",
                       _t("Daily mouth-opening exercise", "ದೈನಂದಿನ ಬಾಯಿ ತೆರೆಯುವ ವ್ಯಾಯಾಮ"),
                       _t("Gentle stretching helps keep the mouth from getting stiffer.",
                          "ಮೃದುವಾದ ವ್ಯಾಯಾಮ ಬಾಯಿ ಇನ್ನಷ್ಟು ಗಟ್ಟಿಯಾಗದಂತೆ ಸಹಾಯ ಮಾಡುತ್ತದೆ."),
                       _t("Open wide slowly 10 times, twice a day - stop if it hurts and tell the doctor.",
                          "ದಿನಕ್ಕೆ ಎರಡು ಬಾರಿ 10 ಸಲ ನಿಧಾನವಾಗಿ ಬಾಯಿ ತೆರೆಯಿರಿ - ನೋವಾದರೆ ನಿಲ್ಲಿಸಿ.")),
    "avoid_spicy": ("mouth", "flame",
                    _t("Go easy on very spicy food", "ಹೆಚ್ಚು ಖಾರದ ಆಹಾರ ಕಡಿಮೆ ಮಾಡಿ"),
                    _t("Burning with spicy food is a sign the lining is irritated.",
                       "ಖಾರ ತಿಂದಾಗ ಉರಿ ಎಂದರೆ ಒಳಪದರ ಕಿರಿಕಿರಿಗೊಂಡಿದೆ."),
                    _t("Choose milder food until the doctor has seen you.", "ವೈದ್ಯರು ನೋಡುವವರೆಗೆ ಸೌಮ್ಯ ಆಹಾರ ಸೇವಿಸಿ.")),
    "self_check": ("mouth", "search",
                   _t("Check your mouth every Sunday", "ಪ್ರತಿ ಭಾನುವಾರ ನಿಮ್ಮ ಬಾಯಿ ಪರೀಕ್ಷಿಸಿ"),
                   _t("You will notice changes early - most warning signs do not hurt.",
                      "ಬದಲಾವಣೆಯನ್ನು ಬೇಗ ಗಮನಿಸುತ್ತೀರಿ - ಹೆಚ್ಚಿನ ಎಚ್ಚರಿಕೆ ಲಕ್ಷಣಗಳು ನೋವು ಕೊಡುವುದಿಲ್ಲ."),
                   _t("Use a mirror and good light: look for white or red patches, sores that do not heal, stiffness.",
                      "ಕನ್ನಡಿ ಮತ್ತು ಬೆಳಕಿನಲ್ಲಿ ನೋಡಿ: ಬಿಳಿ/ಕೆಂಪು ಕಲೆ, ವಾಸಿಯಾಗದ ಹುಣ್ಣು, ಗಟ್ಟಿತನ.")),
    "brush_rinse": ("mouth", "sparkles",
                    _t("Brush twice, rinse after meals", "ದಿನಕ್ಕೆ ಎರಡು ಬಾರಿ ಹಲ್ಲುಜ್ಜಿ, ಊಟದ ನಂತರ ಬಾಯಿ ತೊಳೆಯಿರಿ"),
                    _t("A clean mouth heals better and makes changes easier to see.",
                       "ಸ್ವಚ್ಛ ಬಾಯಿ ಬೇಗ ವಾಸಿಯಾಗುತ್ತದೆ ಮತ್ತು ಬದಲಾವಣೆ ಸುಲಭವಾಗಿ ಕಾಣುತ್ತದೆ."),
                    _t("Soft brush, fluoride paste; rinse with water after eating.",
                       "ಮೃದು ಬ್ರಷ್, ಫ್ಲೋರೈಡ್ ಪೇಸ್ಟ್; ತಿಂದ ನಂತರ ನೀರಿನಿಂದ ತೊಳೆಯಿರಿ.")),
    "eat_colour": ("diet", "apple",
                   _t("Eat fruit and vegetables every day", "ಪ್ರತಿದಿನ ಹಣ್ಣು ಮತ್ತು ತರಕಾರಿ ತಿನ್ನಿ"),
                   _t("Good for the mouth and overall health; some studies link fruit and vegetables to a lower "
                      "risk of mouth cancer. It supports - but never replaces - quitting and seeing the doctor.",
                      "ಬಾಯಿ ಮತ್ತು ಒಟ್ಟು ಆರೋಗ್ಯಕ್ಕೆ ಒಳ್ಳೆಯದು; ಕೆಲವು ಅಧ್ಯಯನಗಳು ಕಡಿಮೆ ಅಪಾಯಕ್ಕೆ ಸಂಬಂಧ ತೋರಿಸುತ್ತವೆ. "
                      "ಇದು ಬಿಡುವುದನ್ನು ಮತ್ತು ವೈದ್ಯರ ಭೇಟಿಯನ್ನು ಎಂದೂ ಬದಲಿಸುವುದಿಲ್ಲ."),
                   _t("Aim for local seasonal fruit, greens, guava, amla, carrots; drink enough water.",
                      "ಸ್ಥಳೀಯ ಹಣ್ಣು, ಸೊಪ್ಪು, ಪೇರಲ, ನೆಲ್ಲಿಕಾಯಿ, ಕ್ಯಾರೆಟ್; ಸಾಕಷ್ಟು ನೀರು ಕುಡಿಯಿರಿ.")),
    "limit_alcohol": ("diet", "glass",
                      _t("Cut down alcohol", "ಮದ್ಯ ಕಡಿಮೆ ಮಾಡಿ"),
                      _t("Alcohol with tobacco multiplies the damage.", "ತಂಬಾಕಿನೊಂದಿಗೆ ಮದ್ಯ ಹಾನಿಯನ್ನು ಹೆಚ್ಚಿಸುತ್ತದೆ."),
                      _t("Set alcohol-free days each week; avoid drinking while chewing or smoking.",
                         "ವಾರದಲ್ಲಿ ಮದ್ಯ ರಹಿತ ದಿನಗಳನ್ನು ಇಡಿ.")),
    "rescreen": ("followup", "repeat",
                 _t("Next screening with your ASHA", "ನಿಮ್ಮ ಆಶಾ ಜೊತೆ ಮುಂದಿನ ತಪಾಸಣೆ"),
                 _t("Regular checks catch changes before they become serious.",
                    "ನಿಯಮಿತ ತಪಾಸಣೆ ಬದಲಾವಣೆಯನ್ನು ಬೇಗ ಹಿಡಿಯುತ್ತದೆ."),
                 _t("Your ASHA will visit around {rescreen}.", "{rescreen} ಸುಮಾರಿಗೆ ನಿಮ್ಮ ಆಶಾ ಭೇಟಿ ನೀಡುತ್ತಾರೆ.")),
}
PHASES = {"medical": _t("Medical", "ವೈದ್ಯಕೀಯ"), "quit": _t("Quitting", "ಬಿಡುವುದು"),
          "mouth": _t("Mouth care", "ಬಾಯಿ ಆರೈಕೆ"), "diet": _t("Food", "ಆಹಾರ"),
          "followup": _t("Follow-up", "ಮುಂದಿನ ತಪಾಸಣೆ")}


def build_roadmap(*, level: str, rules: list[str], habits: dict, symptoms: dict, exposure: str, opening_mm,
                  start: date, referral: dict | None, followup_days: int, done: dict) -> dict:
    """Pick and order the steps for this patient. Every step says why it was added ('because')."""
    kinds = _habit_kinds(habits)
    heavy = any(v and v >= 10 for v in (habits.get("tobacco_per_day"), habits.get("areca_per_day")))
    picked: list[tuple[str, int, str]] = []                      # (step id, due in days, because)

    def add(step, due, because):
        if step not in {p[0] for p in picked}:
            picked.append((step, due, because))

    if referral:
        due = (referral["dueBy"] - start).days if referral.get("dueBy") else 14
        add("see_specialist", max(1, due), "the result needs a specialist")
    elif level == "NEEDS_REVIEW":
        add("doctor_review", 7, "a doctor checks the photos first")
    elif level == "CANNOT_ASSESS":
        add("retake_photos", 3, "some photos were unclear")
    if "R11" in rules:
        add("recheck_patch", 14, "a patch was noticed recently")
    if kinds:
        add("quit_date", 3, "current " + ", ".join(k.replace("smoked", "smoking").replace("smokeless", "smokeless tobacco")
                                                   for k in kinds))
        add("quitline", 7, "free help makes quitting more likely to succeed")
    if "smokeless" in kinds or "areca" in kinds:
        add("swap_chew", 7, "chewing habit")
    if "smoked" in kinds:
        add("smoke_free_home", 7, "smoking habit")
    if heavy or exposure == "high":
        add("ask_nrt", 14, "heavy daily use")
    restricted = opening_mm is not None and opening_mm < 40
    if restricted or symptoms.get("difficulty_opening"):
        add("mouth_exercise", 7, f"mouth opening {opening_mm} mm" if opening_mm else "difficulty opening the mouth")
    if symptoms.get("burning"):
        add("avoid_spicy", 3, "burning with spicy food")
    add("self_check", 7, "most warning signs do not hurt")
    add("brush_rinse", 1, "everyone")
    add("eat_colour", 14, "everyone")
    if "alcohol" in kinds:
        add("limit_alcohol", 14, "regular alcohol")
    add("rescreen", max(followup_days, 14), "routine follow-up")

    rescreen_on = start + timedelta(days=max(followup_days, 14))
    steps = []
    # medical steps always lead (a HIGH result starts with "see the specialist"), then by due date
    for sid, due, because in sorted(picked, key=lambda p: (STEPS[p[0]][0] != "medical", p[1], list(STEPS).index(p[0]))):
        phase, icon, title, why, how = STEPS[sid]
        fill = {"facility": (referral or {}).get("facility") or "the hospital",
                "due": (referral or {}).get("dueBy").strftime("%d %b") if referral and referral.get("dueBy") else "",
                "rescreen": rescreen_on.strftime("%B %Y")}
        steps.append({"id": sid, "phase": phase, "phaseLabel": PHASES[phase], "icon": icon, "title": title,
                      "why": why, "how": {k: v.format(**fill) for k, v in how.items()},
                      # the voice reads this one: never a hospital name or date (those are only shown on screen)
                      "howSpeak": SPEAK_HOW.get(sid, how),
                      "dueOn": (start + timedelta(days=due)).isoformat(), "dueInDays": due, "because": because,
                      "done": sid in done, "doneAt": done.get(sid)})
    return {"steps": steps, "done": sum(1 for s in steps if s["done"]), "total": len(steps),
            "contentVersion": CONTENT_VERSION}
