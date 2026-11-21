"""Backend-for-frontend endpoints for the web app (/api/v1/web/...).

They return exactly the shapes the React screens use, computed in SQL (one round trip instead of many), and
add the phone → desktop photo hand-off. Every endpoint goes through the same OPA permission check and the same
PostgreSQL row-level security as the rest of the API.
"""
from __future__ import annotations

import base64
import json
import secrets
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from ... import storage
from ...config import get_settings
from ...db import request_session
from ...resilience import all_breakers
from ..deps import Ctx, ctx, log_patient_access, presign_or_none

router = APIRouter(prefix="/web", tags=["web app"])

FRONT_STATUS = {"pending": "issued", "booked": "booked", "visited": "visited", "completed": "completed",
                "cancelled": "completed"}


def _age(birth_year):
    return (date.today().year - birth_year) if birth_year else None


def _ref_status(status: str | None, due_by) -> str | None:
    if status is None:
        return None
    if status in ("pending", "booked") and due_by and due_by < date.today():
        return "overdue"
    return FRONT_STATUS.get(status, status)


def ref_code(rid) -> str:
    return "RF-" + str(rid).replace("-", "")[:8].upper()


# ───────────────────────── patients ─────────────────────────
_PATIENT_SQL = """
SELECT p.id, p.display_id, p.full_name, p.sex, p.birth_year, p.phone, p.language, p.created_at,
       p.awareness_watched_at, v.name AS village, v.taluk, ls.id AS sid, ls.captured_at, ls.risk_level,
       rf.status AS ref_status, rf.due_by, rf.facility AS ref_facility,
       EXISTS (SELECT 1 FROM reviews rv WHERE rv.screening_id = ls.id) AS reviewed
FROM patients p
LEFT JOIN villages v ON v.id = p.village_id
LEFT JOIN LATERAL (SELECT id, captured_at, risk_level FROM screenings s WHERE s.patient_id = p.id
                   ORDER BY captured_at DESC LIMIT 1) ls ON true
LEFT JOIN LATERAL (SELECT r.status, r.due_by, f.name AS facility FROM referrals r
                   LEFT JOIN facilities f ON f.id = r.facility_id WHERE r.patient_id = p.id
                   ORDER BY r.created_at DESC LIMIT 1) rf ON true
WHERE p.deleted_at IS NULL {where}
ORDER BY coalesce(ls.captured_at, p.created_at) DESC
LIMIT :lim
"""


def _patient(r) -> dict:
    return {"id": str(r.id), "displayId": r.display_id, "name": r.full_name, "age": _age(r.birth_year),
            "sex": r.sex, "phone": r.phone or "", "village": r.village or "-", "taluk": r.taluk or "-",
            "preferredLanguage": r.language, "registeredAt": r.created_at,
            "lastScreeningAt": r.captured_at, "lastRisk": r.risk_level, "reviewed": bool(r.reviewed),
            "referralStatus": _ref_status(r.ref_status, r.due_by), "referralFacility": r.ref_facility,
            "awarenessWatchedAt": r.awareness_watched_at}


@router.get("/patients")
async def patients(q: str | None = None, limit: int = 60, c: Ctx = Depends(ctx)):
    await c.can("patient:read")
    where, params = "", {"lim": min(limit, 200)}
    if q and q.strip():
        where = ("AND (p.full_name ILIKE :q OR p.display_id ILIKE :q OR p.phone ILIKE :q OR v.name ILIKE :q "
                 "OR CAST(p.id AS text) = :exact)")
        params.update(q=f"%{q.strip()}%", exact=q.strip())
    async with c.session() as s:
        rows = (await s.execute(text(_PATIENT_SQL.format(where=where)), params)).all()
        return [_patient(r) for r in rows]


@router.get("/patients/{pid}")
async def patient(pid: uuid.UUID, c: Ctx = Depends(ctx)):
    await c.can("patient:read", {"patient_id": pid})
    async with c.session() as s:
        rows = (await s.execute(text(_PATIENT_SQL.format(where="AND p.id = :pid")), {"pid": pid, "lim": 1})).all()
        if not rows:
            raise HTTPException(404, "patient not found (or not visible to you)")
        await log_patient_access(s, c, pid, "patient")
        return _patient(rows[0])


@router.get("/patients/{pid}/history")
async def history(pid: uuid.UUID, c: Ctx = Depends(ctx)):
    await c.can("screening:read", {"patient_id": pid})
    async with c.session() as s:
        rows = (await s.execute(text("""
            SELECT s.id, s.captured_at, s.risk_level, s.mouth_opening_mm, s.lesion_score,
                   rv.verdict, rv.notes AS review_notes, rv.diagnosis_text, rv.created_at AS reviewed_at,
                   st.full_name AS reviewer
            FROM screenings s
            LEFT JOIN LATERAL (SELECT verdict, specialist_id, notes, diagnosis_text, created_at FROM reviews r WHERE r.screening_id = s.id
                               ORDER BY created_at DESC LIMIT 1) rv ON true
            LEFT JOIN staff st ON st.id = rv.specialist_id
            WHERE s.patient_id = :pid ORDER BY s.captured_at DESC"""), {"pid": pid})).all()
        out = []
        for r in rows:
            bits = []
            if r.lesion_score is not None:
                bits.append(f"highest photo score {r.lesion_score:.2f}")
            if r.mouth_opening_mm is not None:
                bits.append(f"mouth opening {r.mouth_opening_mm:.0f} mm")
            if r.verdict:
                bits.append("specialist: " + r.verdict.replace("_", " "))
            out.append({"id": str(r.id), "patientId": str(pid), "date": r.captured_at,
                        "risk": r.risk_level or "NEEDS_REVIEW", "reviewed": r.verdict is not None,
                        "reviewer": r.reviewer, "summary": "; ".join(bits) or "Screening recorded",
                        "reviewVerdict": r.verdict, "reviewNote": r.review_notes or r.diagnosis_text,
                        "reviewedAt": r.reviewed_at})
        return out


# ───────────────────────── referrals ─────────────────────────
_REF_SQL = """
SELECT r.id, r.status, r.due_by, r.booked_for, r.created_at, r.patient_id, p.full_name, f.name AS facility, s.risk_level,
       EXISTS (SELECT 1 FROM messages m WHERE m.template = 'referral_patient'
               AND m.related->>'referral_id' = CAST(r.id AS text)) AS sms
FROM referrals r JOIN patients p ON p.id = r.patient_id JOIN facilities f ON f.id = r.facility_id
LEFT JOIN screenings s ON s.id = r.screening_id
WHERE true {where} ORDER BY r.created_at DESC LIMIT 200
"""


def _ref(r) -> dict:
    return {"id": str(r.id), "code": ref_code(r.id), "patientId": str(r.patient_id), "patientName": r.full_name,
            "facility": r.facility, "visitBy": r.due_by, "status": _ref_status(r.status, r.due_by),
            "issuedAt": r.created_at, "risk": r.risk_level or "HIGH", "smsSent": bool(r.sms),
            "bookedFor": r.booked_for, "apiStatus": r.status}


@router.get("/referrals")
async def referrals(c: Ctx = Depends(ctx)):
    await c.can("referral:read")
    async with c.session() as s:
        return [_ref(r) for r in (await s.execute(text(_REF_SQL.format(where="")))).all()]


@router.get("/referrals/lookup")
async def referral_lookup(code: str, c: Ctx = Depends(ctx)):
    """Accepts the short code printed on the slip (RF-XXXXXXXX), or the scanned QR text/token."""
    await c.can("referral:read")
    code = code.strip()
    async with c.session() as s:
        if "." in code:                              # a scanned QR: signed token, possibly inside a URL
            from ...security.tokens import verify_token

            claims = verify_token(code.rsplit("/", 1)[-1], "referral")
            where, params = "AND r.id = :rid", {"rid": claims["sub"]}
        else:
            hexpart = code.upper().removeprefix("RF-").replace("-", "").lower()
            if len(hexpart) < 6:
                raise HTTPException(400, "enter the full referral code, e.g. RF-1A2B3C4D")
            where, params = "AND replace(CAST(r.id AS text), '-', '') LIKE :p", {"p": f"{hexpart}%"}
        rows = (await s.execute(text(_REF_SQL.format(where=where)), params)).all()
        if not rows:
            raise HTTPException(404, "no referral with this code is visible to you")
        await log_patient_access(s, c, rows[0].patient_id, "referral_lookup")
        return _ref(rows[0])


# ───────────────────────── specialist stats ─────────────────────────
VERDICT_LABEL = {"confirm_refer": "Confirm referral", "not_suspicious": "Not suspicious",
                 "needs_biopsy": "Needs biopsy", "cannot_assess": "Cannot assess"}


@router.get("/specialist/stats")
async def specialist_stats(c: Ctx = Depends(ctx)):
    await c.can("review:queue")
    me = uuid.UUID(c.p.user_id)
    async with c.session() as s:
        rows = (await s.execute(text("""
            SELECT r.created_at, r.verdict, r.ai_agreed, t.created_at AS task_at
            FROM reviews r LEFT JOIN review_tasks t ON t.id = r.task_id
            WHERE r.specialist_id = :me ORDER BY r.created_at"""), {"me": me})).all()
    now = datetime.now(timezone.utc)
    agreed = [r.ai_agreed for r in rows if r.ai_agreed is not None]
    waits = sorted((r.created_at - r.task_at).total_seconds() / 60 for r in rows if r.task_at)
    days = [(now - timedelta(days=i)).date() for i in range(6, -1, -1)]
    by_day = [{"day": d.strftime("%a"), "reviewed": sum(1 for r in rows if r.created_at.date() == d),
               "agreed": sum(1 for r in rows if r.created_at.date() == d and r.ai_agreed)} for d in days]
    return {"reviewed": len(rows), "agreementRate": (sum(agreed) / len(agreed)) if agreed else 0,
            "medianMinutes": round(waits[len(waits) // 2], 1) if waits else 0,
            "thisWeek": sum(1 for r in rows if r.created_at >= now - timedelta(days=7)),
            "byDay": by_day,
            "byDecision": [{"name": VERDICT_LABEL.get(v, v), "value": sum(1 for r in rows if r.verdict == v)}
                           for v in VERDICT_LABEL]}


# ───────────────────────── district dashboard ─────────────────────────
@router.get("/district")
async def district(taluk: str = "all", days: int = 90, c: Ctx = Depends(ctx)):
    """Aggregates only. Any count below k (default 5) is returned as null (shown as "<5")."""
    await c.can("analytics:read")
    k = get_settings().k_anonymity_min_cell
    since = datetime.now(timezone.utc) - timedelta(days=days)
    tw = "" if taluk == "all" else "AND v.taluk = :taluk"
    params = {"since": since, "taluk": taluk}
    sup = lambda n: None if n is None or n < k else int(n)  # noqa: E731
    async with request_session(c.p.user_id, "system") as s:
        base = f"""FROM screenings sc JOIN patients p ON p.id = sc.patient_id
                   LEFT JOIN villages v ON v.id = p.village_id WHERE sc.captured_at >= :since {tw}"""
        t = (await s.execute(text(f"""SELECT count(DISTINCT sc.patient_id) AS screened,
                    count(DISTINCT sc.patient_id) FILTER (WHERE sc.risk_level = 'HIGH') AS high {base}"""),
                             params)).one()
        rbase = f"""FROM referrals r JOIN patients p ON p.id = r.patient_id
                    LEFT JOIN villages v ON v.id = p.village_id WHERE r.created_at >= :since {tw}"""
        rr = (await s.execute(text(f"""SELECT count(*) AS referred,
                    count(*) FILTER (WHERE r.status IN ('visited','completed')) AS visited,
                    count(*) FILTER (WHERE r.status = 'completed') AS completed,
                    count(*) FILTER (WHERE r.status IN ('pending','booked') AND r.due_by < current_date) AS overdue
                    {rbase}"""), params)).one()
        flagged = (await s.execute(text(f"""SELECT count(DISTINCT sc.patient_id) {base}
                    AND sc.risk_level IN ('HIGH','MEDIUM')"""), params)).scalar()
        monthly = (await s.execute(text(f"""SELECT to_char(date_trunc('month', sc.captured_at), 'Mon') AS m,
                    date_trunc('month', sc.captured_at) AS mm, count(*) AS n,
                    count(*) FILTER (WHERE sc.risk_level = 'LOW') AS low,
                    count(*) FILTER (WHERE sc.risk_level = 'MEDIUM') AS med,
                    count(*) FILTER (WHERE sc.risk_level = 'HIGH') AS high {base} GROUP BY 1, 2 ORDER BY 2"""),
                                   params)).all()
        vil = (await s.execute(text(f"""SELECT v.name, v.taluk, v.population,
                    count(DISTINCT sc.patient_id) AS screened,
                    count(DISTINCT sc.patient_id) FILTER (WHERE sc.risk_level = 'HIGH') AS high
                    FROM villages v LEFT JOIN patients p ON p.village_id = v.id
                    LEFT JOIN screenings sc ON sc.patient_id = p.id AND sc.captured_at >= :since
                    WHERE true {tw} GROUP BY v.id ORDER BY v.taluk, v.name"""), params)).all()
        taluks = [r[0] for r in (await s.execute(text("SELECT DISTINCT taluk FROM villages ORDER BY 1"))).all()]
    return {
        "totals": {"screened": sup(t.screened) or 0, "highRisk": sup(t.high) or 0, "referred": sup(rr.referred) or 0,
                   "visited": sup(rr.visited) or 0, "overdue": sup(rr.overdue) or 0},
        "volume": [{"month": m.m, "screened": m.n} for m in monthly],
        "riskTrend": [{"month": m.m, "LOW": round(100 * m.low / m.n, 1) if m.n else 0,
                       "MEDIUM": round(100 * m.med / m.n, 1) if m.n else 0,
                       "HIGH": round(100 * m.high / m.n, 1) if m.n else 0} for m in monthly],
        "funnel": [{"stage": "Screened", "value": sup(t.screened) or 0},
                   {"stage": "Flagged", "value": sup(flagged) or 0},
                   {"stage": "Referred", "value": sup(rr.referred) or 0},
                   {"stage": "Visited", "value": sup(rr.visited) or 0},
                   {"stage": "Completed", "value": sup(rr.completed) or 0}],
        "villages": [{"name": v.name, "taluk": v.taluk, "screened": sup(v.screened), "highRisk": sup(v.high),
                      "coverage": (round(v.screened / v.population, 3) if v.population and sup(v.screened) else None)}
                     for v in vil],
        "taluks": taluks,
        "privacy": f"aggregates only; counts below {k} hidden",
    }


# ───────────────────────── admin ─────────────────────────
@router.get("/admin/health")
async def health(c: Ctx = Depends(ctx)):
    await c.can("admin:ops")
    cfg = get_settings()
    checks = [("api", "API gateway", None), ("postgres", "PostgreSQL (data, RLS, audit chain)", None),
              ("opa", "OPA policy engine", f"{cfg.opa_url}/health"),
              ("inference", "AI inference (ONNX Runtime)", f"{cfg.inference_url}/ready"),
              ("keycloak", "Keycloak identity",
               f"{cfg.keycloak_internal_url}/realms/{cfg.keycloak_realm}" if cfg.auth_mode == "keycloak" else None),
              ("vault", "Vault secrets", f"{cfg.vault_addr}/v1/sys/health"),
              ("redis", "Job queue (Redis)", None), ("storage", "Object storage (photos)", None)]
    out = []
    # real 30-day uptime from the checks the worker records every minute (None until there is history)
    async with request_session(c.p.user_id, "system") as s:
        uptime = {r[0]: float(r[1]) for r in (await s.execute(text(
            "SELECT service, avg((state <> 'down')::int) FROM service_checks "
            "WHERE checked_at > now() - interval '30 days' GROUP BY service"))).all()}
    async with httpx.AsyncClient(timeout=4) as h:
        for sid, name, url in checks:
            t0, state = time.perf_counter(), "operational"
            try:
                if sid == "postgres":
                    async with request_session(c.p.user_id, "system") as s:
                        await s.execute(text("SELECT 1"))
                elif sid == "redis":
                    import redis.asyncio as aredis

                    r = aredis.from_url(cfg.redis_url, socket_timeout=2)
                    await r.ping()
                    await r.aclose()
                elif sid == "storage":
                    storage.client().head_bucket(Bucket=cfg.bucket_images)
                elif url:
                    resp = await h.get(url)
                    state = "operational" if resp.status_code < 500 else "degraded"
                elif sid == "keycloak":
                    state = "degraded"
            except Exception:  # noqa: BLE001
                state = "down"
            out.append({"id": sid, "name": name, "state": state,
                        "latencyMs": round((time.perf_counter() - t0) * 1000), "uptime": uptime.get(sid),
                        "description": {"operational": "Responding normally", "degraded": "Responding slowly or partly",
                                        "down": "Not reachable - work is queued or refused safely"}[state]})
    open_circuits = [b for b in all_breakers() if b.get("state") != "closed"]
    for b in open_circuits:
        out.append({"id": f"circuit-{b.get('name')}", "name": f"Circuit breaker: {b.get('name')}",
                    "state": "degraded", "latencyMs": 0, "uptime": 0,
                    "description": f"{b.get('state')} - calls are short-circuited until it recovers"})
    return out


@router.get("/admin/metrics")
async def metrics(c: Ctx = Depends(ctx)):
    """Measured system metrics for the admin dashboard: service uptime / latency / incidents (recorded every minute
    by the worker), server resources, workflow and AI health. Nothing here is estimated or hard-coded."""
    await c.can("admin:ops")
    from ...services.health import SERVICES

    names = dict(SERVICES)

    async def rows(sql: str, **kw):
        return [dict(r._mapping) for r in (await s.execute(text(sql), kw)).all()]

    async with request_session(c.p.user_id, "system") as s:
        svc = await rows("""
            SELECT service,
                   avg((state <> 'down')::int) FILTER (WHERE checked_at > now() - interval '24 hours') AS up_24h,
                   avg((state <> 'down')::int) FILTER (WHERE checked_at > now() - interval '7 days')   AS up_7d,
                   avg((state <> 'down')::int)                                                       AS up_30d,
                   count(*) FILTER (WHERE checked_at > now() - interval '24 hours')                 AS checks_24h,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)
                     FILTER (WHERE checked_at > now() - interval '24 hours')                        AS p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                     FILTER (WHERE checked_at > now() - interval '24 hours')                        AS p95_ms,
                   min(checked_at) AS since
            FROM service_checks WHERE checked_at > now() - interval '30 days' GROUP BY service""")
        latest = {r["service"]: r for r in await rows("""
            SELECT DISTINCT ON (service) service, state, latency_ms, checked_at
            FROM service_checks ORDER BY service, checked_at DESC""")}
        hourly = await rows("""
            SELECT date_trunc('hour', checked_at) AS hour, avg((state <> 'down')::int) AS up,
                   avg(latency_ms) AS avg_ms, count(*) AS checks
            FROM service_checks WHERE checked_at > now() - interval '24 hours' GROUP BY 1 ORDER BY 1""")
        incidents = await rows("""
            WITH x AS (SELECT service, checked_at, state,
                              lag(state) OVER (PARTITION BY service ORDER BY checked_at) AS prev
                       FROM service_checks WHERE checked_at > now() - interval '7 days')
            SELECT service, checked_at AS at, state, prev FROM x
            WHERE prev IS NOT NULL AND state <> prev ORDER BY checked_at DESC LIMIT 30""")
        host_series = await rows("""
            SELECT date_bin('10 minutes', sampled_at, TIMESTAMPTZ '2000-01-01') AS at,
                   round(avg(cpu_pct)::numeric, 1) AS cpu, round(avg(mem_pct)::numeric, 1) AS mem,
                   round(avg(disk_pct)::numeric, 1) AS disk
            FROM host_samples WHERE sampled_at > now() - interval '24 hours' GROUP BY 1 ORDER BY 1""")
        host_now = (await rows("SELECT cpu_pct, mem_pct, disk_pct, load1, sampled_at FROM host_samples "
                               "ORDER BY sampled_at DESC LIMIT 1") or [None])[0]
        screenings = await rows("""
            SELECT date_trunc('hour', received_at) AS hour, count(*) AS n FROM screenings
            WHERE received_at > now() - interval '24 hours' GROUP BY 1 ORDER BY 1""")
        timing = (await rows("""
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM d.created_at - s.received_at)) AS p50,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY extract(epoch FROM d.created_at - s.received_at)) AS p95,
                   count(*) AS n
            FROM decisions d JOIN screenings s ON s.id = d.screening_id
            WHERE d.trigger = 'initial' AND d.created_at > now() - interval '7 days'"""))[0]
        risk = await rows("""SELECT risk_level, count(*) AS n FROM decisions
                             WHERE trigger = 'initial' AND created_at > now() - interval '7 days' GROUP BY 1""")
        queue = (await rows("""SELECT (SELECT count(*) FROM outbox WHERE published_at IS NULL) AS outbox_pending,
                                      (SELECT count(*) FROM dead_letters WHERE NOT resolved) AS failed_jobs"""))[0]
        msgs = await rows("""SELECT status, count(*) AS n FROM messages
                             WHERE channel <> 'in_app' AND created_at > now() - interval '24 hours' GROUP BY 1""")
        ai = (await rows("""
            SELECT count(*) AS photos,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_ms,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms,
                   avg(out_of_distribution::int) AS unusual_rate
            FROM image_results WHERE created_at > now() - interval '7 days'"""))[0]
        ai_extra = (await rows("""
            SELECT (SELECT count(*) FROM screenings WHERE ai_status = 'unavailable'
                      AND received_at > now() - interval '7 days') AS ai_unavailable,
                   (SELECT avg((outputs ? 'retake')::int) FROM decisions
                      WHERE trigger = 'initial' AND created_at > now() - interval '7 days') AS retake_rate,
                   (SELECT avg(ai_agreed::int) FROM reviews
                      WHERE ai_agreed IS NOT NULL AND created_at > now() - interval '30 days') AS agreement,
                   (SELECT count(*) FROM reviews
                      WHERE ai_agreed IS NOT NULL AND created_at > now() - interval '30 days') AS reviews"""))[0]

    def f(v, nd=4):
        return None if v is None else round(float(v), nd)

    services = []
    for sid, name in SERVICES:
        r = next((x for x in svc if x["service"] == sid), {})
        cur = latest.get(sid, {})
        services.append({"id": sid, "name": name, "state": cur.get("state"), "latencyMs": cur.get("latency_ms"),
                         "checkedAt": cur.get("checked_at"), "uptime24h": f(r.get("up_24h")),
                         "uptime7d": f(r.get("up_7d")), "uptime30d": f(r.get("up_30d")),
                         "checks24h": r.get("checks_24h", 0), "p50Ms": f(r.get("p50_ms"), 0),
                         "p95Ms": f(r.get("p95_ms"), 0), "since": r.get("since")})
    return {
        "services": services,
        "availability": [{"hour": h["hour"], "up": f(h["up"]), "avgMs": f(h["avg_ms"], 0), "checks": h["checks"]}
                         for h in hourly],
        "incidents": [{**i, "name": names.get(i["service"], i["service"])} for i in incidents],
        "host": {"now": host_now, "series": host_series},
        "workflow": {"screeningsPerHour": screenings, "screenings24h": sum(x["n"] for x in screenings),
                     "decisionSecondsP50": f(timing["p50"], 1), "decisionSecondsP95": f(timing["p95"], 1),
                     "decisions7d": timing["n"], "riskMix7d": {r["risk_level"]: r["n"] for r in risk},
                     "outboxPending": queue["outbox_pending"], "failedJobs": queue["failed_jobs"],
                     "messages24h": {m["status"]: m["n"] for m in msgs}},
        "ai": {"photos7d": ai["photos"], "latencyP50Ms": f(ai["p50_ms"], 0), "latencyP95Ms": f(ai["p95_ms"], 0),
               "unusualRate": f(ai["unusual_rate"]), "aiUnavailable7d": ai_extra["ai_unavailable"],
               "retakeRate": f(ai_extra["retake_rate"]), "specialistAgreement": f(ai_extra["agreement"]),
               "reviews30d": ai_extra["reviews"]},
        "messagingMode": get_settings().messaging_mode,
        "generatedAt": datetime.now(timezone.utc),
    }


@router.get("/admin/audit")
async def audit(q: str | None = None, limit: int = 200, c: Ctx = Depends(ctx)):
    await c.can("audit:read")
    where, params = "", {"lim": min(limit, 1000)}
    if q and q.strip():
        where = ("WHERE (a.action ILIKE :q OR a.entity_type ILIKE :q OR coalesce(st.username, a.actor_id) ILIKE :q "
                 "OR CAST(a.id AS text) = :exact OR coalesce(a.entity_id,'') ILIKE :q)")
        params.update(q=f"%{q.strip()}%", exact=q.strip())
    async with c.session() as s:
        rows = (await s.execute(text(f"""
            SELECT a.id, a.ts, a.actor_id, a.actor_role, a.action, a.entity_type, a.entity_id, a.ip, a.hash,
                   a.prev_hash, coalesce(st.full_name, st.username, a.actor_id) AS actor
            FROM audit_log a LEFT JOIN staff st ON CAST(st.id AS text) = a.actor_id
            {where} ORDER BY a.id DESC LIMIT :lim"""), params)).all()
    return [{"id": str(r.id), "at": r.ts, "actor": r.actor, "role": r.actor_role, "action": r.action,
             "resource": f"{r.entity_type}{(' ' + r.entity_id[:8]) if r.entity_id else ''}", "ip": r.ip or "-",
             "hash": r.hash, "prevHash": r.prev_hash} for r in rows]


# ───────────────────────── provider (local doctor) summary ─────────────────────────
@router.get("/provider/summary")
async def provider_summary(c: Ctx = Depends(ctx)):
    if not c.p.is_provider:
        raise HTTPException(403, "provider token required")
    pid = uuid.UUID(c.p.patient_scope)
    await c.can("patient:read", {"patient_id": pid})
    async with c.session() as s:
        p = (await s.execute(text(_PATIENT_SQL.format(where="AND p.id = :pid")), {"pid": pid, "lim": 1})).one()
        await log_patient_access(s, c, pid, "provider_summary")
        ref = (await s.execute(text(_REF_SQL.format(where="AND r.patient_id = :pid")), {"pid": pid})).first()
        meds = (await s.execute(text("""SELECT coalesce(name_matched, name_entered) AS name, prescribed_by, started_on,
                    created_at, masks_symptoms FROM medications WHERE patient_id = :pid ORDER BY created_at DESC
                    LIMIT 20"""), {"pid": pid})).all()
        tl = (await s.execute(text("""SELECT occurred_at, kind, source, summary, created_by FROM timeline_events
                    WHERE patient_id = :pid ORDER BY occurred_at DESC LIMIT 40"""), {"pid": pid})).all()
    return {
        "patient": {"id": p.display_id, "name": p.full_name, "age": _age(p.birth_year), "sex": p.sex,
                    "village": p.village or "-"},
        "risk": p.risk_level or "NEEDS_REVIEW", "reviewed": bool(p.reviewed),
        "referral": _ref(ref) if ref else None,
        "medicines": [{"name": m.name or "-", "dose": "as prescribed" + (" · can hide symptoms" if m.masks_symptoms
                                                                          else ""),
                       "since": m.started_on or m.created_at, "addedBy": m.prescribed_by or "-"} for m in meds],
        "history": [{"date": e.occurred_at, "event": e.summary} for e in tl if e.kind != "note"],
        "notes": [{"at": e.occurred_at, "by": e.created_by or e.source, "text": e.summary} for e in tl
                  if e.kind == "note"],
        "guidance": "Pain relief from gels or painkillers can hide a worsening patch. Any patch or sore lasting "
                    "more than 2 weeks needs specialist review.",
    }


# ───────────────────────── phone → desktop photo capture ─────────────────────────
CAPTURE_TTL = 15 * 60


def _redis():
    import redis.asyncio as aredis

    return aredis.from_url(get_settings().redis_url, socket_timeout=3)


async def _session(r, sid: str) -> dict:
    raw = await r.get(f"cap:{sid}")
    if not raw:
        raise HTTPException(410, "this capture session has expired - create a new QR code")
    return json.loads(raw)


async def _push(r, sid: str, event: dict) -> int:
    n = await r.rpush(f"cap:{sid}:ev", json.dumps(event, default=str))
    await r.expire(f"cap:{sid}:ev", CAPTURE_TTL)
    return n


@router.post("/capture-sessions", status_code=201)
async def capture_create(request: Request, c: Ctx = Depends(ctx)):
    """The desktop asks for a QR code. The phone page needs no login: the QR carries a one-session secret that
    only allows uploading photos into this session for 15 minutes."""
    await c.can("image:upload")
    cfg = get_settings()
    sid, secret = uuid.uuid4().hex[:16], secrets.token_urlsafe(18)
    expires = datetime.now(timezone.utc) + timedelta(seconds=CAPTURE_TTL)
    r = _redis()
    try:
        await r.set(f"cap:{sid}", json.dumps({"secret": secret, "owner": c.p.user_id,
                                              "expires": expires.isoformat()}), ex=CAPTURE_TTL)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, "phone capture needs the queue service (Redis) - use webcam or upload") from e
    finally:
        await r.aclose()
    base = (cfg.capture_base_url or cfg.public_base_url).rstrip("/")
    return {"id": sid, "url": f"{base}/capture/{sid}?t={secret}", "expiresAt": expires}


class CaptureConnect(BaseModel):
    device: str = Field(default="phone", max_length=120)


class CapturePhoto(BaseModel):
    site: str = Field(max_length=30)
    dataUrl: str = Field(max_length=14_000_000)
    quality: dict = Field(default_factory=dict)
    capturedAt: str | None = None
    source: str = "phone"


async def _check_secret(r, sid: str, t: str) -> dict:
    sess = await _session(r, sid)
    if not secrets.compare_digest(sess["secret"], t or ""):
        raise HTTPException(403, "invalid capture link")
    return sess


@router.post("/capture-sessions/{sid}/connect")
async def capture_connect(sid: str, body: CaptureConnect, t: str = ""):
    r = _redis()
    try:
        await _check_secret(r, sid, t)
        await _push(r, sid, {"type": "connected", "device": body.device})
        return {"ok": True}
    finally:
        await r.aclose()


@router.post("/capture-sessions/{sid}/photos", status_code=201)
async def capture_photo(sid: str, body: CapturePhoto, t: str = ""):
    if not body.dataUrl.startswith("data:image/"):
        raise HTTPException(400, "expected an image data URL")
    head, b64 = body.dataUrl.split(",", 1)
    data = base64.b64decode(b64)
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "photo too large")
    r = _redis()
    try:
        await _check_secret(r, sid, t)
        n = await r.llen(f"cap:{sid}:ev")
        key = f"capture/{sid}/{n:03d}-{body.site}.jpg"
        storage.put_bytes(get_settings().bucket_images, key, data, head[5:].split(";")[0] or "image/jpeg")
        await _push(r, sid, {"type": "photo", "key": key, "site": body.site, "quality": body.quality,
                             "capturedAt": body.capturedAt or datetime.now(timezone.utc).isoformat()})
        return {"ok": True}
    finally:
        await r.aclose()


@router.get("/capture-sessions/{sid}/events")
async def capture_events(sid: str, after: int = 0, c: Ctx = Depends(ctx)):
    """The desktop polls this every ~1.5 s; photos come back as data URLs ready for the screening form."""
    await c.can("image:upload")
    r = _redis()
    try:
        sess = await _session(r, sid)
        if sess["owner"] != c.p.user_id:
            raise HTTPException(403, "not your capture session")
        raw = await r.lrange(f"cap:{sid}:ev", after, after + 20)
    finally:
        await r.aclose()
    out = []
    for i, item in enumerate(raw):
        e = json.loads(item)
        if e["type"] == "photo":
            data = storage.get_bytes(get_settings().bucket_images, e["key"])
            e = {"type": "photo", "photo": {"site": e["site"], "quality": e["quality"], "capturedAt": e["capturedAt"],
                                            "source": "phone",
                                            "dataUrl": "data:image/jpeg;base64," + base64.b64encode(data).decode()}}
        out.append({"seq": after + i + 1, "event": e})
    return {"events": out, "expiresAt": sess["expires"]}


# ───────────────────────── home dashboards ─────────────────────────
@router.get("/home")
async def home(c: Ctx = Depends(ctx)):
    """The few numbers each role's home page shows - real counts, never placeholders."""
    await c.can("staff:me")
    role, me = c.p.role, c.p.user_id
    out: dict = {"role": role}
    async with c.session() as s:
        if role in ("asha", "nurse"):
            q = lambda sql, **kw: s.execute(text(sql), {"me": me, **kw})  # noqa: E731
            out.update({
                "screenedToday": (await q("""SELECT count(*) FROM screenings WHERE CAST(worker_id AS text) = :me
                                              AND captured_at >= date_trunc('day', now())""")).scalar(),
                "screenedAvg": (await q("""SELECT round(count(*) / 30.0, 1) FROM screenings
                                            WHERE CAST(worker_id AS text) = :me AND captured_at >= now() - interval '30 days'
                                            """)).scalar(),
                "followupsDue": (await q("""SELECT count(*) FROM followups WHERE status IN ('scheduled','notified')
                                             AND due_on <= current_date + 7""")).scalar(),
                "followupsOverdue": (await q("""SELECT count(*) FROM followups WHERE status IN ('scheduled','notified')
                                                 AND due_on < current_date""")).scalar(),
                "pendingUploads": (await q("""SELECT count(*) FROM screenings WHERE CAST(worker_id AS text) = :me
                                               AND status <> 'completed'""")).scalar(),
                "activeReferrals": (await q("SELECT count(*) FROM referrals WHERE status IN ('pending','booked')")).scalar(),
                "visitedThisWeek": (await q("""SELECT count(*) FROM referrals WHERE status IN ('visited','completed')
                                                AND coalesce(visited_at, completed_at, created_at) >= now() - interval '7 days'
                                                """)).scalar(),
            })
        elif role == "specialist":
            out["facilities"] = (await s.execute(text("""SELECT count(DISTINCT sc.facility_id) FROM review_tasks t
                                 JOIN screenings sc ON sc.id = t.screening_id WHERE t.status = 'open'"""))).scalar()
    if role in ("district_officer", "clinical_lead", "admin"):
        async with request_session(me, "system") as s:
            one = lambda sql: s.execute(text(sql))  # noqa: E731
            out.update({
                "screened90d": (await one("SELECT count(DISTINCT patient_id) FROM screenings "
                                          "WHERE captured_at >= now() - interval '90 days'")).scalar(),
                "overdueReferrals": (await one("SELECT count(*) FROM referrals WHERE status IN ('pending','booked') "
                                               "AND due_by < current_date")).scalar(),
                "worstTaluk": (await one("""SELECT v.taluk FROM referrals r JOIN patients p ON p.id = r.patient_id
                                             JOIN villages v ON v.id = p.village_id WHERE r.status IN ('pending','booked')
                                             GROUP BY 1 ORDER BY count(*) DESC LIMIT 1""")).scalar(),
                "candidateModels": (await one("SELECT count(*) FROM model_versions WHERE status IN ('candidate','shadow')"
                                              )).scalar(),
                "activeModel": (await one("SELECT version FROM model_versions WHERE status = 'active' "
                                          "ORDER BY promoted_at DESC NULLS LAST LIMIT 1")).scalar(),
                "pendingRules": (await one("SELECT count(*) FROM rule_sets WHERE status = 'pending_approval'")).scalar(),
                "openIncidents": (await one("SELECT count(*) FROM incidents WHERE status = 'open'")).scalar(),
                "failedJobs": (await one("SELECT count(*) FROM dead_letters WHERE NOT resolved")).scalar(),
                "failedMessages": (await one("SELECT count(*) FROM messages WHERE status = 'failed' "
                                             "AND created_at >= now() - interval '7 days'")).scalar(),
            })
    return {k: (float(v) if hasattr(v, "is_integer") and not isinstance(v, int) else v) for k, v in out.items()}


# ───────────────────────── demo phones (sandbox messaging only) ─────────────────────────
class PhoneReplyIn(BaseModel):
    patient_id: uuid.UUID
    digit: str = Field(pattern=r"^[12]$")


class PhoneCheckinIn(BaseModel):
    patient_id: uuid.UUID


def _sandbox_only():
    if get_settings().messaging_mode != "sandbox":
        raise HTTPException(404, "demo phones exist only while messaging is in demo (sandbox) mode")


@router.get("/messaging-mode")
async def messaging_mode(c: Ctx = Depends(ctx)):
    """Whether patient SMS really leave the system (twilio) or are only stored and shown (sandbox)."""
    return {"mode": get_settings().messaging_mode}


@router.get("/demo-phones")
async def demo_phones(patient_id: uuid.UUID | None = None, c: Ctx = Depends(ctx)):
    """Sandbox messaging: the patient's SMS thread and the signed-in staff member's OWN phone (their alerts about this
    patient). Messages are the real records the system created; nothing leaves the system. Only patients the caller
    may see are listed (row-level security), and nobody sees another staff member's notifications."""
    _sandbox_only()
    from sqlalchemy import select

    from ...models import CheckIn, Message, Patient, Screening, Staff

    async with c.session() as us:                    # the caller's own view: RLS decides which patients exist
        recent = (await us.execute(text("""
            SELECT patient_id, max(created_at) AS last_at FROM messages
            WHERE patient_id IS NOT NULL AND channel IN ('sms', 'voice') AND created_at > now() - interval '30 days'
            GROUP BY patient_id ORDER BY last_at DESC LIMIT 12"""))).all()
        visible = {}
        for pid, last_at in recent:
            p = await us.get(Patient, pid)
            if p is not None:
                visible[pid] = (p, last_at)
    patients = [{"id": str(pid), "name": p.full_name, "displayId": p.display_id, "lastAt": last}
                for pid, (p, last) in visible.items()]
    chosen = patient_id if patient_id in visible else (next(iter(visible)) if visible else None)
    out = {"mode": "sandbox", "patients": patients, "patient": None, "staff": []}
    if chosen is None:
        return out
    p = visible[chosen][0]
    async with request_session(c.p.user_id, "system") as s:
        msgs = (await s.execute(select(Message).where(Message.patient_id == chosen,
                                                      Message.channel.in_(["sms", "voice"]))
                                .order_by(Message.created_at))).scalars().all()
        open_ci = (await s.execute(select(CheckIn).where(CheckIn.patient_id == chosen, CheckIn.status == "sent")
                                   )).scalars().first()
        last = (await s.execute(select(Screening).where(Screening.patient_id == chosen)
                                .order_by(Screening.captured_at.desc()))).scalars().first()
        # only the signed-in person's own phone: each role sees its own notifications, never someone else's
        staff_ids = [uuid.UUID(c.p.user_id)]
        staff = []
        for sid in staff_ids:
            st = await s.get(Staff, sid)
            if st is None:
                continue
            inbox = (await s.execute(select(Message).where(Message.to_staff_id == sid, Message.channel == "in_app",
                                                           Message.body.like(f"%{p.display_id}%"),
                                                           Message.created_at > text("now() - interval '30 days'"))
                                     .order_by(Message.created_at.desc()).limit(8))).scalars().all()
            staff.append({"id": str(st.id), "name": st.full_name or st.username, "role": st.role,
                          "messages": [{"id": str(m.id), "body": m.body, "template": m.template, "at": m.created_at}
                                       for m in reversed(inbox)]})
    phone = p.phone or ""
    out["patient"] = {"id": str(p.id), "name": p.full_name, "displayId": p.display_id,
                      "phone": f"{phone[:3]}*****{phone[-3:]}" if len(phone) > 6 else None,
                      "canReply": open_ci is not None,
                      "messages": [{"id": str(m.id), "channel": m.channel, "template": m.template, "body": m.body,
                                    "status": m.status, "at": m.created_at,
                                    "fromPatient": m.template == "patient_reply"} for m in msgs]}
    out["staff"] = staff
    return out


@router.post("/demo-phones/reply")
async def demo_phone_reply(body: PhoneReplyIn, c: Ctx = Depends(ctx)):
    """Sandbox: the patient answers the check-in on the demo phone. Goes through the SAME handler as a real SMS
    reply (YES re-evaluates and escalates the case)."""
    _sandbox_only()
    from ...models import Message, Patient
    from .system import _handle_reply

    await c.can("timeline:read", {"patient_id": str(body.patient_id)})
    async with c.session() as us:
        if await us.get(Patient, body.patient_id) is None:
            raise HTTPException(404, "patient not found")
    async with request_session(c.p.user_id, "system") as s:
        p = await s.get(Patient, body.patient_id)
        s.add(Message(channel="sms", patient_id=p.id, template="patient_reply", body=body.digit, status="received",
                      provider="sandbox", language=p.language, related={"demo_phone": True}))
        out = await _handle_reply(s, p, body.digit, "sms")
        await c.audit(s, "demo_phone.reply", "patient", p.id, p.id, {"digit": body.digit})
        return {"status": "ok", **(out if isinstance(out, dict) else {})}


@router.post("/demo-phones/checkin")
async def demo_phone_checkin(body: PhoneCheckinIn, c: Ctx = Depends(ctx)):
    """Sandbox: send the two-week check-in SMS now (instead of waiting 14 days), so the reply can be tried."""
    _sandbox_only()
    from ...models import CheckIn, Patient
    from ...services.notify import queue_sms

    await c.can("timeline:read", {"patient_id": str(body.patient_id)})
    async with c.session() as us:
        if await us.get(Patient, body.patient_id) is None:
            raise HTTPException(404, "patient not found")
    async with request_session(c.p.user_id, "system") as s:
        p = await s.get(Patient, body.patient_id)
        if not p.phone:
            raise HTTPException(409, "this patient has no phone number")
        now = datetime.now(timezone.utc)
        s.add(CheckIn(patient_id=p.id, channel="sms", scheduled_for=now, sent_at=now, status="sent"))
        await s.run_sync(lambda ss: queue_sms(ss, p.phone, "checkin_sms", p.language, patient_id=p.id,
                                              related={"demo_phone": True}))
        await c.audit(s, "demo_phone.checkin", "patient", p.id, p.id, {})
        return {"status": "sent"}


# ───────────────────────── transparency: about the AI ─────────────────────────
@router.get("/about-ai")
async def about_ai(c: Ctx = Depends(ctx)):
    """What the AI is, how well it works, what it must not be used for, which rules decide, how long data is kept and
    whom to contact. Read live from the active model, its model card and the active rule set."""
    from pathlib import Path

    cfg = get_settings()
    card = {}
    try:
        card = json.loads((Path(cfg.models_dir) / "current" / "model_card.json").read_text())
    except (OSError, ValueError):
        pass
    async with request_session(c.p.user_id, "system") as s:
        model = (await s.execute(text(
            "SELECT version, status, benchmark, promoted_at, created_at FROM model_versions WHERE status = 'active' "
            "ORDER BY promoted_at DESC NULLS LAST LIMIT 1"))).mappings().first()
        rs = (await s.execute(text(
            "SELECT version, definition->>'name' AS name, rationale, activated_at, "
            "definition->'lesion' AS lesion, definition->'referral_due_days' AS due "
            "FROM rule_sets WHERE status = 'active' ORDER BY version DESC LIMIT 1"))).mappings().first()
    ev = (card.get("evaluation") or {}).get("held_out_test", {}).get("balanced", {})
    td = card.get("training_data") or {}
    uniq = (td.get("deduplication") or {}).get("unique_after_grouping_by_label") or {}
    return {
        "model": {
            "name": "EfficientNetV2-S", "backbone": card.get("backbone"),
            "version": model["version"] if model else None,
            "activeSince": (model["promoted_at"] or model["created_at"]) if model else None,
            "benchmark": dict(model["benchmark"]) if model and model["benchmark"] else None,
            "heldOutTest": {k: ev.get(k) for k in ("n", "auc", "sensitivity", "specificity", "ppv", "npv", "ci95")},
            "trainingPhotos": sum(uniq.values()) if uniq else None,
            "trainingByLabel": uniq or None,
            "labelDefinition": card.get("label_definition"),
            "comparedWith": [x.get("key") for x in card.get("candidate_selection", [])],
            "intendedUse": card.get("intended_use"),
            "notIntendedFor": card.get("not_intended_for"),
            "limitations": card.get("limitations"),
            "ethics": card.get("ethical_considerations"),
        },
        "rules": {"version": rs["version"] if rs else None, "name": rs["name"] if rs else None,
                  "rationale": rs["rationale"] if rs else None, "activeSince": rs["activated_at"] if rs else None,
                  "lesion": rs["lesion"] if rs else None, "referralDueDays": rs["due"] if rs else None},
        "privacy": {"retentionMessageDays": cfg.retention_message_days, "retentionPhotoDays": cfg.retention_photo_days,
                    "messagingMode": cfg.messaging_mode},
        "grievance": {"name": cfg.grievance_name, "email": cfg.grievance_email, "phone": cfg.grievance_phone or None},
    }


# ───────────────────────── real hospitals near the patient (OpenStreetMap) ─────────────────────────
class ChooseHospitalIn(BaseModel):
    osm_id: str = Field(pattern=r"^(node|way|relation)/[0-9]{1,15}$")


async def _origin(us, scr) -> dict:
    """Where the patient lives: the screening's GPS point, else their village."""
    from ...models import Patient, Village

    if scr.lat is not None and scr.lon is not None:
        return {"lat": scr.lat, "lon": scr.lon, "label": "where the screening was done"}
    p = await us.get(Patient, scr.patient_id)
    v = await us.get(Village, p.village_id) if p and p.village_id else None
    if v:
        return {"lat": v.lat, "lon": v.lon, "label": f"{v.name} village"}
    return {"lat": 12.7597, "lon": 75.2017, "label": "Puttur (no location recorded)"}


@router.get("/screenings/{sid}/nearby-care")
async def nearby_care(sid: uuid.UUID, c: Ctx = Depends(ctx)):
    """Real hospitals and clinics around the patient (OpenStreetMap) with real road travel times (OSRM), best match
    for an oral pre-cancer referral first. Only a map location is sent to these services, never patient data."""
    from ...models import Facility, Referral, Screening
    from ...services import nearby

    async with c.session() as us:                     # the caller must be able to see this screening
        scr = await us.get(Screening, sid)
        if scr is None:
            raise HTTPException(404, "screening not found")
        await c.can("timeline:read", {"patient_id": str(scr.patient_id)})
        origin = await _origin(us, scr)
        ref = (await us.execute(text("SELECT id FROM referrals WHERE screening_id = :s"), {"s": str(sid)})).scalar()
        current = None
        if ref:
            r = await us.get(Referral, ref)
            f = await us.get(Facility, r.facility_id)
            current = {"referralId": str(r.id), "facility": f.name if f else None,
                       "osmId": f.code[4:].replace("-", "/", 1) if f and f.code.startswith("OSM-") else None,
                       "dueBy": r.due_by}
    try:
        places = await nearby.places_near(origin["lat"], origin["lon"])
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    # travel times for the closest 60 (straight line first), then rank: right kind of care first, then time
    for p in places:
        p["crowKm"] = round(nearby.haversine_km(origin["lat"], origin["lon"], p["lat"], p["lon"]), 1)
    places.sort(key=lambda p: p["crowKm"])
    shortlist = places[:60]
    times = await nearby.travel_times(origin["lat"], origin["lon"], shortlist)
    for p in shortlist:
        p.update(times.get(p["osmId"], {}))
        p["score"] = p["fit"] - 0.4 * p.get("minutes", 999)
    shortlist.sort(key=lambda p: -p["score"])
    return {"origin": origin, "places": shortlist, "current": current,
            "source": "OpenStreetMap contributors (ODbL) · routes by OSRM",
            "note": "Kind of care is guessed from each place's name and map tags - call before going."}


@router.get("/route")
async def route(a_lat: float, a_lon: float, b_lat: float, b_lon: float, c: Ctx = Depends(ctx)):
    from ...services import nearby

    await c.can("staff:me")
    return {"line": await nearby.route_line(a_lat, a_lon, b_lat, b_lon)}


@router.post("/referrals/{rid}/choose-hospital")
async def choose_hospital(rid: uuid.UUID, body: ChooseHospitalIn, c: Ctx = Depends(ctx)):
    """The patient chose where to go. The referral records that real hospital; the patient gets an SMS with its
    address and a map link. Specialist review: that hospital's Arogya specialists if it has any, otherwise Arogya's
    specialist panel reviews the photos remotely while the patient visits the chosen hospital."""
    from sqlalchemy import select

    from ...models import Facility, Patient, Referral, ReviewTask, Screening, Staff
    from ...services import nearby
    from ...services.notify import notify_staff, queue_sms

    async with c.session() as us:
        r = await us.get(Referral, rid)
        if r is None:
            raise HTTPException(404, "referral not found")
        await c.can("timeline:read", {"patient_id": str(r.patient_id)})
        scr = await us.get(Screening, r.screening_id)
        origin = await _origin(us, scr)
    try:
        places = await nearby.places_near(origin["lat"], origin["lon"])      # server data, never trust the client
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    place = next((p for p in places if p["osmId"] == body.osm_id), None)
    if place is None:
        raise HTTPException(404, "that place is not in the list for this patient")
    code = "OSM-" + body.osm_id.replace("/", "-")
    async with request_session(c.p.user_id, "system") as s:
        fac = (await s.execute(select(Facility).where(Facility.code == code))).scalars().first()
        if fac is None:
            fac = Facility(code=code, name=place["name"][:160], kind=place["category"], district="Dakshina Kannada",
                           lat=place["lat"], lon=place["lon"], phone=place.get("phone"), accepts_referrals=True)
            s.add(fac)
        fac.services = [place["category"]]
        fac.ownership = "government" if place.get("government") else None
        fac.address, fac.hours = place.get("address"), place.get("openingHours")
        await s.flush()
        r = await s.get(Referral, rid)
        old = r.facility_id
        r.facility_id = fac.id
        # specialist review: this hospital's Arogya specialists, else stay with the current specialist panel
        on_site = (await s.execute(select(Staff.id).where(Staff.role == "specialist", Staff.facility_id == fac.id))
                   ).scalars().all()
        routed = "panel"
        if on_site:
            for t in (await s.execute(select(ReviewTask).where(ReviewTask.screening_id == r.screening_id,
                                                               ReviewTask.status == "open"))).scalars():
                t.facility_id = fac.id
            p = await s.get(Patient, r.patient_id)
            for sid_ in on_site:
                await s.run_sync(lambda ss, x=sid_: notify_staff(ss, x, "staff_new_case", related={"referral_id": str(rid)},
                                                                 level="HIGH-risk", patient=p.display_id,
                                                                 reason="patient chose your hospital"))
            routed = "hospital"
        p = await s.get(Patient, r.patient_id)
        if p.phone:
            mp = f"https://www.openstreetmap.org/?mlat={place['lat']:.5f}&mlon={place['lon']:.5f}#map=17/{place['lat']:.5f}/{place['lon']:.5f}"
            await s.run_sync(lambda ss: queue_sms(ss, p.phone, "referral_location", p.language, patient_id=p.id,
                                                  related={"referral_id": str(rid)}, facility=place["name"],
                                                  address=place.get("address") or "see map", map=mp,
                                                  due=r.due_by.strftime("%d %b")))
        await c.audit(s, "referral.hospital_chosen", "referral", rid, r.patient_id,
                      {"osm_id": body.osm_id, "name": place["name"], "previous_facility": str(old), "review": routed})
        return {"facility": place["name"], "review": routed,
                "message": "Sent to that hospital's Arogya specialists" if routed == "hospital" else
                           "Arogya's specialist panel reviews the photos; the patient visits the chosen hospital"}


# ───────────────────────── after the result: risk explanation + personal roadmap ─────────────────────────
class CareStepIn(BaseModel):
    done: bool = True


async def _care_inputs(us, sid):
    from ...models import Decision, Facility, Referral, Screening

    scr = await us.get(Screening, sid)
    if scr is None:
        raise HTTPException(404, "screening not found")
    dec = await us.get(Decision, scr.decision_id) if scr.decision_id else None
    if dec is None:
        raise HTTPException(409, "the result is not ready yet")
    ref = (await us.execute(text("SELECT id FROM referrals WHERE screening_id = :s"), {"s": str(sid)})).scalar()
    referral = None
    if ref:
        r = await us.get(Referral, ref)
        f = await us.get(Facility, r.facility_id)
        referral = {"facility": f.name if f else None, "dueBy": r.due_by}
    return scr, dec, referral


@router.get("/screenings/{sid}/care")
async def screening_care(sid: uuid.UUID, c: Ctx = Depends(ctx)):
    """What the habits mean (sourced population facts, adapted to the result) and the patient's personal roadmap,
    with the steps already done. Built from approved content - no free text is generated."""
    from sqlalchemy import select

    from ...domain import careplan
    from ...models import CareProgress

    async with c.session() as us:
        scr, dec, referral = await _care_inputs(us, sid)
        await c.can("timeline:read", {"patient_id": str(scr.patient_id)})
    async with request_session(c.p.user_id, "system") as s:
        rows = (await s.execute(select(CareProgress).where(CareProgress.screening_id == sid))).scalars().all()
    done = {r.step_id: r.done_at for r in rows}
    out = dec.outputs or {}
    level = dec.risk_level
    exposure = ((out.get("summary") or {}).get("exposure") or {}).get("level") or scr.habit_level or "low"
    rules = [r.get("rule") for r in out.get("reasons", [])]
    start = (scr.captured_at or datetime.now(timezone.utc)).date()
    return {
        "level": level,
        "risk": careplan.build_risk(level, exposure, scr.habits or {}),
        "roadmap": careplan.build_roadmap(level=level, rules=rules, habits=scr.habits or {},
                                          symptoms=scr.symptoms or {}, exposure=exposure,
                                          opening_mm=scr.mouth_opening_mm, start=start, referral=referral,
                                          followup_days=int(out.get("followup_days") or 365), done=done),
        "sources": careplan.SOURCES,
    }


@router.post("/patients/{pid}/awareness-watched")
async def awareness_watched(pid: uuid.UUID, c: Ctx = Depends(ctx)):
    """The patient watched the awareness film to the end (it is required before their first result only)."""
    from ...models import Patient

    await c.can("timeline:read", {"patient_id": str(pid)})
    async with request_session(c.p.user_id, "system") as s:
        p = await s.get(Patient, pid)
        if p is None or p.deleted_at is not None:
            raise HTTPException(404, "patient not found")
        first = p.awareness_watched_at is None
        if first:
            p.awareness_watched_at = datetime.now(timezone.utc)
        await c.audit(s, "awareness.watched", "patient", pid, pid, {"first": first})
    return {"watchedAt": p.awareness_watched_at, "first": first}


@router.post("/screenings/{sid}/care/steps/{step_id}")
async def care_step(sid: uuid.UUID, step_id: str, body: CareStepIn, c: Ctx = Depends(ctx)):
    """The ASHA ticks (or unticks) a roadmap step during a visit. Recorded with who and when."""
    from sqlalchemy import delete, select

    from ...domain import careplan
    from ...models import CareProgress, Screening

    if step_id not in careplan.STEPS:
        raise HTTPException(404, "unknown step")
    async with c.session() as us:
        scr = await us.get(Screening, sid)
        if scr is None:
            raise HTTPException(404, "screening not found")
        await c.can("timeline:read", {"patient_id": str(scr.patient_id)})
    async with request_session(c.p.user_id, "system") as s:
        existing = (await s.execute(select(CareProgress).where(CareProgress.screening_id == sid,
                                                               CareProgress.step_id == step_id))).scalars().first()
        if body.done and existing is None:
            s.add(CareProgress(screening_id=sid, patient_id=scr.patient_id, step_id=step_id,
                               done_by=uuid.UUID(c.p.user_id)))
        elif not body.done and existing is not None:
            await s.execute(delete(CareProgress).where(CareProgress.id == existing.id))
        await c.audit(s, "care.step", "screening", sid, scr.patient_id, {"step": step_id, "done": body.done})
    return {"step": step_id, "done": body.done}


# ───────────────────────── map tiles via our server (OpenStreetMap tile policy + privacy) ─────────────────────────
@router.get("/tiles/{z}/{x}/{y}.png", include_in_schema=False)
async def map_tile(z: int, x: int, y: int):
    """OpenStreetMap tiles fetched by this server with a proper app identification and cached for 7 days, as the
    OSM tile usage policy asks. The health worker's browser never contacts OpenStreetMap directly. Public (map
    images only, no patient data) - <img> tags cannot send a login token."""
    from fastapi import Response

    from ...services import nearby

    if not (0 <= z <= 19 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise HTTPException(404, "no such tile")
    key = f"tile:v1:{z}:{x}:{y}"
    try:
        import redis.asyncio as aredis

        r = aredis.from_url(get_settings().redis_url, socket_timeout=2)
        data = await r.get(key)
    except Exception:  # noqa: BLE001
        r, data = None, None
    if data is None:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": nearby.USER_AGENT}) as h:
            resp = await h.get(f"https://tile.openstreetmap.org/{z}/{x}/{y}.png")
        if resp.status_code != 200:
            raise HTTPException(502, "map tile unavailable")
        data = resp.content
        if r is not None:
            try:
                await r.set(key, data, ex=7 * 24 * 3600)
            except Exception:  # noqa: BLE001
                pass
    if r is not None:
        await r.aclose()
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "public, max-age=604800"})
