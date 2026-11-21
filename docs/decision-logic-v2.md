# Arogya decision logic v2

Status: APPROVED by the project team on 2026-11-21 (decision point A6: refer directly, with the model's accuracy in the explanation). Implemented in services/app/domain/decision.py; the example patients below are automated tests (services/tests/test_decision_v2.py). Still to be reviewed by an oral medicine specialist.

## Why v2

v1 gives one label (LOW / MEDIUM / HIGH ...) that mixes three different questions, so a daily tobacco user with a
healthy mouth is shown "Medium risk", and habits can turn an AI flag into an automatic urgent referral.
v2 answers three questions separately and then picks one action.

1. **Findings today** - is there something suspicious in the mouth now? (AI on the photos + clinical signs)
2. **Exposure** - how likely are problems in future? (habits only)
3. **Confidence** - how much can we trust today's assessment? (photo quality, AI availability)

Habits never create a finding. They change follow-up, counselling and specialist-queue priority only.

## 1. Findings today

### AI evidence (EfficientNetV2-S, calibrated probability per mouth site)

| Band | Score | Meaning |
|---|---|---|
| Clean | below 40% | nothing seen |
| Uncertain | 40% to below 78% | cannot rule out; a doctor looks at the photo |
| Suspicious | 78% to below 90% | likely abnormal (78% = the model's validated screening threshold) |
| Highly suspicious | 90% and above | very likely abnormal |

A high score on an unclear or unusual photo is not trusted: that site is retaken or checked by a doctor.
The 90% line will be checked on the held-out benchmark set (346 photos) before it is used.

### Clinical signs

| Strong signs (refer on their own) | Weak signs (watch and recheck) |
|---|---|
| Patch or sore present 14 days or more | Patch noticed, less than 14 days |
| Ulcer that is not healing | Burning with spicy food, alone |
| Restricted opening (below 35 mm) with burning (OSMF) | Restricted opening without burning |
| Pain relieved by medicine while the finding persists | Borderline opening (35 to 40 mm) |
| Symptoms returned after an earlier high-risk result | Difficulty opening the mouth (reported) |

## 2. Exposure (habits only)

| Habit | Points |
|---|---|
| Smokeless tobacco (gutka, khaini, pan with tobacco), current | 3 |
| Smoked tobacco (beedi, cigarette), current | 2 |
| Areca nut, current | 2 |
| Alcohol daily | 2 (weekly: 1) |
| Any current habit for 10 years or more | +1 (20 years or more: +2) |
| Heavy daily amount (10+ cigarettes or 5+ quids a day) | +1 |
| Former user, quit less than 5 years ago | half points |
| Former user, quit 5+ years ago | 1 point in total |

Exposure level: **High** 4 or more, **Moderate** 2 to 3, **Low** 0 to 1.
Burning and difficulty opening are no longer counted here (they are clinical signs, counted once).

## 3. Confidence

| Level | When |
|---|---|
| Good | AI available, at most 2 sites unusable, no unreliable high score |
| Limited | an unclear or unusual photo has a high score (that site is retaken or checked) |
| Cannot assess | 3 or more sites unusable (retake the photos) |
| Pending | AI result not available yet (never treated as low) |

## 4. Action (first matching row wins)

| # | Situation | Action | Level shown |
|---|---|---|---|
| A1 | AI result not available | Wait for AI; never low | Pending (Needs review) |
| A2 | 3+ sites unusable | Retake photos | Cannot assess |
| A3 | Open referral already exists | Stays referred until a specialist decides | High |
| A4 | Any strong clinical sign | Refer within 14 days | High |
| A5 | AI suspicious or highly suspicious + any clinical sign (strong or weak) | Refer within 14 days | High |
| A6 | AI highly suspicious, no clinical sign | Refer within 14 days (**decision point**, see below) | High |
| A7 | High score on an unclear or unusual photo | Retake that site; if still high, specialist checks | Needs review |
| A8 | AI suspicious, no clinical sign | Specialist photo review within 7 days; high exposure = front of the queue | Needs review |
| A9 | AI uncertain on any site | Specialist photo review within 14 days | Needs review |
| A10 | Only weak clinical signs | Recheck: patch in 2 weeks, others in 3 months | Watch (Medium) |
| A11 | Nothing found, exposure High | "No suspicious signs today. High exposure." Quit counselling, rescreen in 6 months | Low |
| A12 | Nothing found, exposure Moderate | Counselling, rescreen in 12 months | Low |
| A13 | Nothing found, exposure Low | Routine, rescreen in 12 months | Low |

**Decision point A6:** should a very high AI score (90%+) with no other sign refer the patient directly, or go to a
specialist photo review within 48 hours first? Draft says refer (the model is the main detector); the safer
alternative is a fast photo review. To be decided with the team / clinician.

## 5. Result card (what the ASHA sees)

    Findings today : Suspicious area on the left cheek (AI 96%)
    Exposure       : High (smokeless tobacco daily, 12 years)
    Confidence     : Good (7 of 7 photos clear)
    Action         : Refer to Oral Medicine Centre within 14 days

## 6. Example patients (become automatic tests)

| # | Patient | AI (max site) | Signs | Habits | Expected |
|---|---|---|---|---|---|
| 1 | Healthy non-user | 2% | none | none | A13 Low, 12 months |
| 2 | Daily gutka 10 years | 3% | none | high | A11 Low + high exposure, counselling, 6 months |
| 3 | 20 cigarettes/day 15 years + daily alcohol | 5% | none | high | A11 Low + high exposure, 6 months |
| 4 | Former smoker, quit 8 years ago | 2% | none | low | A13 Low, 12 months |
| 5 | Daily pan (areca only) 5 years | 4% | none | moderate | A12 Low, counselling, 12 months |
| 6 | Patch noticed 5 days ago | 6% | weak | low | A10 Watch, recheck in 2 weeks |
| 7 | Patch for 21 days | 8% | strong | low | A4 High, refer |
| 8 | Ulcer not healing | 10% | strong | low | A4 High, refer |
| 9 | Opening 31 mm + burning | 5% | strong (OSMF) | high | A4 High, refer |
| 10 | Opening 31 mm, no burning | 5% | weak | moderate | A10 Watch, 3 months |
| 11 | Opening 38 mm | 3% | weak | low | A10 Watch, 3 months |
| 12 | Burning only, areca chewer | 4% | weak | moderate | A10 Watch, 3 months |
| 13 | One site uncertain | 60% | none | low | A9 Needs review, 14 days |
| 14 | Suspicious, non-user | 82% | none | low | A8 Needs review, 7 days |
| 15 | Suspicious, heavy tobacco user | 82% | none | high | A8 Needs review, 7 days, priority (v1 gave automatic High) |
| 16 | Suspicious + patch noticed | 82% | weak | low | A5 High, refer |
| 17 | Suspicious + restricted opening | 82% | weak | moderate | A5 High, refer |
| 18 | Highly suspicious, nothing else | 95% | none | low | A6 High, refer (decision point) |
| 19 | 95% on a blurry / unusual photo | 95% (unreliable) | none | low | A7 Needs review, retake |
| 20 | 3 photos unusable | - | none | low | A2 Cannot assess, retake |
| 21 | AI service down | - | none | high | A1 Pending, never low |
| 22 | Lalitha: gel relieved pain, patch remains | 12% | strong (masked) | moderate | A4 High, refer |
| 23 | Symptoms back after earlier High | 10% | strong | high | A4 High, refer |
| 24 | Open referral, new screening clean | 2% | none | high | A3 stays High |
| 25 | Shekhar: left cheek 99%, burning, 31 mm, gutka 12 years | 99% | strong + weak | high | A4/A5 High, refer |
| 26 | Ravi: healthy, no habits | 2% | none | none | A13 Low, 12 months |

## 7. What changes in the data collected

New optional habit fields (old screenings stay valid): current / former, years since quitting,
amount per day, tobacco form (smokeless / smoked, already collected).

## 8. Safety rules that stay

- AI missing is never low (fail-safe, enforced by the rule-set validator).
- Automation never lowers a case with an open referral; only a specialist can.
- Every rule change still needs approval by a second clinical lead (four-eyes).
- Every decision stores inputs, rule-set version and model version, and can be replayed.
