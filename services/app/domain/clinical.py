"""Habit risk scoring, mouth-opening measurement and server-side image quality checks.

All weights / cut-offs come from the ACTIVE rule set (versioned, maker-checker approved),
never from code, so clinicians can tune them without a deployment.
"""
from __future__ import annotations

import io
import statistics

import numpy as np

SITES = ["left_buccal", "right_buccal", "tongue_dorsum", "tongue_ventral", "gums", "palate"]
MEASUREMENT_SITE = "front_open"


# ───────────────────────── habits ─────────────────────────
def score_habits(habits: dict, symptoms: dict, cfg: dict) -> tuple[int, str, list[str]]:
    """Exposure (future risk) from habits. Returns (score, level, contributing factors).

    Rule sets from v2 on use "points" (habits only: type, amount, years, current or former use). Symptoms are
    clinical signs and are NOT counted here. Older rule sets ("weights") keep their original behaviour, so past
    decisions stay reproducible."""
    if "points" in cfg:
        return score_exposure(habits, cfg)
    w = cfg["weights"]
    score, why = 0, []

    def add(cond: bool, key: str, label: str):
        nonlocal score
        if cond and w.get(key):
            score += int(w[key])
            why.append(label)

    years = max(int(habits.get("areca_years") or 0), int(habits.get("tobacco_years") or 0))
    add(bool(habits.get("tobacco")), "tobacco", "tobacco use")
    add(bool(habits.get("alcohol")), "alcohol", "alcohol use")
    add(bool(habits.get("areca")), "areca", "areca nut use")
    add(years > 10, "years_over_10", f"habit for {years} years")
    add(bool(symptoms.get("burning")), "burning", "burning with spicy food")
    add(bool(symptoms.get("difficulty_opening")), "difficulty_opening", "difficulty opening mouth")
    lv = cfg["levels"]
    level = "high" if score >= lv["high"] else "moderate" if score >= lv["moderate"] else "low"
    return score, level, why


_TOBACCO_LABEL = {"smokeless": "smokeless tobacco", "smoked": "smoking", "both": "smokeless tobacco and smoking"}


def _status(habits: dict, kind: str) -> str:
    """current | former | never. A habit switched off (e.g. by a what-if) is never, whatever its old status."""
    if not habits.get(kind):
        return "never"
    st = habits.get(f"{kind}_status") or "current"
    return st if st in ("current", "former") else "current"


def score_exposure(habits: dict, cfg: dict) -> tuple[int, str, list[str]]:
    p = cfg["points"]
    former_cfg = cfg.get("former", {})
    recent_quit = former_cfg.get("recent_quit_years", 5)
    heavy = cfg.get("heavy_amount", {})
    score, why = 0.0, []
    long_ago_former = False
    current_years: list[int] = []
    heavy_use = False

    def habit(kind: str, base: float, label: str):
        nonlocal score, long_ago_former, heavy_use
        st = _status(habits, kind)
        if st == "never" or base <= 0:
            return
        years = habits.get(f"{kind}_years")
        if st == "former":
            quit = habits.get(f"{kind}_quit_years")
            if quit is not None and quit >= recent_quit:
                long_ago_former = True
                why.append(f"former {label} (quit {quit} years ago)")
                return
            score += base * former_cfg.get("recent_factor", 0.5)
            why.append(f"former {label}" + (f" (quit {quit} years ago)" if quit is not None else ""))
            return
        score += base
        why.append(label + (f" for {years} years" if years else ""))
        if years:
            current_years.append(int(years))
        per_day = habits.get(f"{kind}_per_day")
        limit = heavy.get("smoked_per_day", 10) if label == "smoking" else heavy.get("chewed_per_day", 5)
        if per_day is not None and per_day >= limit:
            heavy_use = True

    ttype = habits.get("tobacco_type") if habits.get("tobacco_type") not in (None, "none") else "smokeless"
    habit("tobacco", p.get(f"tobacco_{ttype}", p.get("tobacco_smokeless", 3)), _TOBACCO_LABEL.get(ttype, "tobacco"))
    habit("areca", p.get("areca", 2), "areca nut")
    if _status(habits, "alcohol") == "current":
        freq = habits.get("alcohol_frequency") or "occasional"
        pts = p.get(f"alcohol_{freq}", 0)
        if pts:
            score += pts
            why.append(f"alcohol {freq}")
    if current_years:
        longest = max(current_years)
        if longest >= cfg.get("years_long", 20):
            score += p.get("years_long", 2)
        elif longest >= cfg.get("years_medium", 10):
            score += p.get("years_medium", 1)
    if heavy_use:
        score += p.get("heavy_amount", 1)
        why.append("heavy daily use")
    if long_ago_former:
        score += former_cfg.get("old_points", 1)
    total = int(score + 0.5)
    lv = cfg["levels"]
    level = "high" if total >= lv["high"] else "moderate" if total >= lv["moderate"] else "low"
    return total, level, why


# ───────────────────────── mouth opening ─────────────────────────
def compute_opening(raw: dict, cfg: dict) -> tuple[float | None, dict]:
    """raw = {"method": "iris"|"card"|"manual", "readings": [...], "head_pose": {"yaw": deg, "pitch": deg}}
    iris reading: {"iris_px": float, "tap_px": float}   card reading: {"card_px": float, "tap_px": float}
    manual reading: {"mm": float}. Returns (calibrated median mm, details)."""
    if not raw or not raw.get("readings"):
        return None, {"status": "not_measured"}
    method = raw.get("method", "iris")
    ref_mm = {"iris": cfg.get("iris_mm", 11.7), "card": cfg.get("card_mm", 85.6)}.get(method)
    pose = raw.get("head_pose") or {}
    max_angle = cfg.get("max_head_angle_deg", 12)
    mms, rejected = [], []
    for i, r in enumerate(raw["readings"]):
        try:
            if method == "manual":
                mm = float(r["mm"])
            else:
                ref_px = float(r["iris_px"] if method == "iris" else r["card_px"])
                if ref_px <= 0:
                    raise ValueError("reference size must be > 0")
                mm = ref_mm / ref_px * float(r["tap_px"])
            if not 5 <= mm <= 80:
                raise ValueError(f"implausible opening {mm:.1f} mm")
            mms.append(mm)
        except (KeyError, TypeError, ValueError) as e:
            rejected.append({"reading": i, "reason": str(e)})
    if not mms:
        return None, {"status": "invalid", "rejected": rejected}
    raw_median = statistics.median(mms)
    cal = cfg.get("calibration", {"slope": 1.0, "intercept": 0.0})
    corrected = round(cal["slope"] * raw_median + cal["intercept"], 1)
    pose_ok = abs(float(pose.get("yaw", 0))) <= max_angle and abs(float(pose.get("pitch", 0))) <= max_angle
    spread = (max(mms) - min(mms)) if len(mms) > 1 else 0.0
    return corrected, {"status": "ok" if pose_ok else "pose_warning", "method": method, "source": raw.get("source"),
                       "readings_mm": [round(x, 1) for x in mms],
                       "raw_median_mm": round(raw_median, 2), "spread_mm": round(spread, 2),
                       "calibration": cal, "rejected": rejected, "head_pose_ok": pose_ok}


# ───────────────────────── image quality (server re-check) ─────────────────────────
def image_quality(data: bytes, cfg: dict | None = None) -> dict:
    """Same three checks the phone runs (blur, exposure, glare) + a mouth-tissue colour check.
    The server recomputes them so a modified or buggy client cannot bypass the quality gate."""
    import cv2
    from PIL import Image, ImageOps

    cfg = cfg or {}
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    w, h = im.size
    im.thumbnail((640, 640))
    rgb = np.asarray(im)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    ch, cw = gray.shape
    center = gray[ch // 6: ch - ch // 6, cw // 6: cw - cw // 6]
    blur = float(cv2.Laplacian(center, cv2.CV_64F).var())
    brightness = float(center.mean())
    glare = float((center >= 250).mean())
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    tissue = (((hue <= 12) | (hue >= 160)) & (sat >= 40) & (val >= 60)).mean()
    t = {"blur_min": 15.0, "bright_min": 45.0, "bright_max": 215.0, "glare_max": 0.06, "tissue_min": 0.12, **cfg}
    issues = []
    if blur < t["blur_min"]:
        issues.append("blurry")
    if brightness < t["bright_min"]:
        issues.append("too_dark")
    if brightness > t["bright_max"]:
        issues.append("too_bright")
    if glare > t["glare_max"]:
        issues.append("glare")
    if tissue < t["tissue_min"]:
        issues.append("not_mouth_tissue")
    return {"width": w, "height": h, "blur": round(blur, 1), "brightness": round(brightness, 1),
            "glare_fraction": round(glare, 4), "tissue_fraction": round(float(tissue), 3),
            "issues": issues, "ok": not issues}
