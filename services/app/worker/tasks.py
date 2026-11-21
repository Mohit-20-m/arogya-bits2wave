"""Background tasks. Every task is idempotent and retried with exponential backoff; after the last retry the
payload is written to `dead_letters` (visible + re-playable from the admin API) - nothing is silently lost."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from celery import Task
from sqlalchemy import func, select

from .. import audit, messaging, storage
from ..config import get_settings
from ..db import system_session
from ..models import (AuditLog, AuditSnapshot, CheckIn, DeadLetter, FollowUp, Label, Medication, Message,
                      OutboxEvent, Patient, Referral, Screening, Staff, TimelineEvent, TrainingRun)
from ..observability import DEAD_LETTERS, OUTBOX_LAG, log
from ..resilience import backoff_delay
from ..services import mlops, monitoring, pipeline
from ..services.notify import notify_staff, queue_sms, queue_voice
from .celery_app import celery_app


class ReliableTask(Task):
    max_retries = 6
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 900
    retry_jitter = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        try:
            with system_session() as s:
                s.add(DeadLetter(task_name=self.name, payload={"args": list(args), "kwargs": kwargs},
                                 error=f"{type(exc).__name__}: {exc}"[:4000], attempts=self.request.retries + 1))
            log.error("task_dead_lettered", task=self.name, error=str(exc)[:300])
        except Exception as e:  # noqa: BLE001
            log.error("dead_letter_write_failed", error=str(e))


def _task(name, **kw):
    return celery_app.task(name=name, base=ReliableTask, bind=True, **kw)


# ───────────────────────── screening ─────────────────────────
@_task("os.process_screening")
def process_screening(self, screening_id: str, trigger: str = "initial", attempt: int = 0,
                      run_inference: bool = True):
    with system_session() as s:
        return pipeline.process_screening(s, screening_id, trigger=trigger, run_inference=run_inference,
                                          attempt=attempt)


@_task("os.retake_timeout")
def retake_timeout(self, screening_id: str):
    with system_session() as s:
        return pipeline.retake_timeout(s, screening_id)


@_task("os.referral_after_review")
def referral_after_review(self, screening_id: str, verdict: str, review_id: str | None = None):
    with system_session() as s:
        return pipeline.referral_after_review(s, screening_id, verdict, review_id)


@_task("os.reevaluate_patient")
def reevaluate_patient(self, patient_id: str, trigger: str = "timeline_update"):
    with system_session() as s:
        scr = s.execute(select(Screening).where(Screening.patient_id == patient_id)
                        .order_by(Screening.captured_at.desc())).scalars().first()
        if scr is None:
            return {"status": "no_screening"}
        if scr.status == "received":
            # photos are still being uploaded: the submit runs the full AI + rules pipeline, which already reads this
            # timeline update. Deciding now (rules only) would move the screening on and the AI would never run.
            return {"status": "waiting_for_submit", "screening_id": str(scr.id)}
        return pipeline.process_screening(s, scr.id, trigger=trigger, run_inference=False)


# ───────────────────────── messaging ─────────────────────────
@_task("os.send_message")
def send_message(self, message_id: str):
    with system_session() as s:
        m = s.get(Message, message_id)
        if m is None or m.status in ("sent", "delivered", "sandbox", "blocked"):
            return {"status": "skip"}
        reason = messaging.guard(s, m)
        if reason:                                   # safety guard: never text an unexpected number in real mode
            m.status, m.error = "blocked", reason
            log.warning("message_blocked", message=str(m.id), reason=reason)
            return {"status": "blocked", "reason": reason}
        try:
            messaging.deliver(m)
        except Exception as e:
            m.status, m.error = "failed", str(e)[:500]
            raise
        return {"status": m.status}


@_task("os.dispatch_checkins")
def dispatch_checkins(self):
    now = datetime.now(timezone.utc)
    n = 0
    with system_session() as s:
        due = s.execute(select(CheckIn).where(CheckIn.status == "scheduled", CheckIn.scheduled_for <= now)
                        .limit(200).with_for_update(skip_locked=True)).scalars().all()
        for ci in due:
            p = s.get(Patient, ci.patient_id)
            if ci.channel == "voice":
                queue_voice(s, p.phone, ci.id, p.language, patient_id=p.id)
            else:
                queue_sms(s, p.phone, "checkin_sms", p.language, patient_id=p.id, related={"checkin_id": str(ci.id)})
            ci.status, ci.sent_at = "sent", now
            n += 1
        # check-ins unanswered for 5 days expire; ASHA is told so she can visit
        for ci in s.execute(select(CheckIn).where(CheckIn.status == "sent",
                                                  CheckIn.sent_at <= now - timedelta(days=5))).scalars():
            ci.status, ci.response = "expired", "no_answer"
    return {"sent": n}


# ───────────────────────── OCR ─────────────────────────
@_task("os.ocr_medication")
def ocr_medication(self, medication_id: str):
    from ..domain.medicines import match_medicine, ocr_image

    cfg = get_settings()
    with system_session() as s:
        m = s.get(Medication, medication_id)
        if m is None or not m.photo_key or m.status == "ocr_done":
            return {"status": "skip"}
        text_ = ocr_image(storage.get_bytes(cfg.bucket_images, m.photo_key))
        m.ocr_text = text_[:4000]
        hit = match_medicine(text_) or (match_medicine(m.name_entered) if m.name_entered else None)
        if hit:
            m.name_matched, m.category, m.masks_symptoms, m.match_score = hit["name"], hit["category"], \
                hit["masks_symptoms"], hit["score"]
        m.status = "ocr_done"
        if m.timeline_event_id:
            ev = s.get(TimelineEvent, m.timeline_event_id)
            if ev:
                ev.summary = f"Medicine recorded: {m.name_matched or m.name_entered or 'unidentified'}"
                ev.data = {**ev.data, "ocr": hit or {}, "masks_symptoms": m.masks_symptoms}
        audit.record_sync(s, "system", "system", "medication.ocr", "medication", m.id, m.patient_id,
                          {"matched": m.name_matched, "masks": m.masks_symptoms})
        if m.masks_symptoms:     # a symptom-masking medicine changes the facts -> re-evaluate risk
            from ..outbox import emit_sync

            emit_sync(s, "patient.reevaluate", {"patient_id": str(m.patient_id), "trigger": "medication"},
                      dedupe_key=f"reeval:med:{m.id}")
        return {"status": "ok", "match": hit}


# ───────────────────────── reminders ─────────────────────────
@_task("os.followup_reminders")
def followup_reminders(self):
    today = date.today()
    out = {"notified": 0, "missed": 0}
    with system_session() as s:
        for fu in s.execute(select(FollowUp).where(FollowUp.status == "scheduled",
                                                   FollowUp.due_on <= today + timedelta(days=3))).scalars():
            p = s.get(Patient, fu.patient_id)
            scr = s.get(Screening, fu.screening_id)
            notify_staff(s, scr.worker_id if scr else None, "staff_followup_due",
                         related={"patient_id": str(p.id), "followup_id": str(fu.id)},
                         due=fu.due_on.strftime("%d %b"), patient=p.display_id, reason=fu.reason)
            queue_sms(s, p.phone, "followup_due", p.language, patient_id=p.id, due=fu.due_on.strftime("%d %b"))
            fu.status = "notified"
            out["notified"] += 1
        for fu in s.execute(select(FollowUp).where(FollowUp.status == "notified",
                                                   FollowUp.due_on < today - timedelta(days=14))).scalars():
            fu.status = "missed"
            out["missed"] += 1
    return out


@_task("os.referral_overdue")
def referral_overdue(self):
    from ..models import Facility

    today = date.today()
    n = 0
    with system_session() as s:
        for r in s.execute(select(Referral).where(Referral.status.in_(["pending", "booked"]),
                                                  Referral.due_by < today)).scalars():
            outcome = r.outcome or {}
            if outcome.get("overdue_notified") == today.isoformat():
                continue
            p = s.get(Patient, r.patient_id)
            scr = s.get(Screening, r.screening_id)
            fac = s.get(Facility, r.facility_id)
            notify_staff(s, scr.worker_id if scr else None, "staff_referral_overdue",
                         related={"referral_id": str(r.id)}, patient=p.display_id,
                         facility=fac.name if fac else "clinic", due=r.due_by.strftime("%d %b"))
            r.outcome = {**outcome, "overdue_notified": today.isoformat()}
            n += 1
    return {"overdue": n}


# ───────────────────────── MLOps ─────────────────────────
@_task("os.index_model")
def index_model(self, force: bool = False):
    with system_session() as s:
        return mlops.index_model_artifacts(s, force=force)


@celery_app.task(name="os.retrain_head", bind=True, max_retries=0)
def retrain_head(self, run_id: str, exclude_noncommercial: bool = False):
    error = None
    try:
        with system_session() as s:
            return mlops.retrain_head(s, run_id, exclude_noncommercial)
    except Exception as e:  # noqa: BLE001 - record failure on the run instead of retrying
        error = f"{type(e).__name__}: {e}"
        log.warning("retrain_failed", run=run_id, error=error[:300])
    with system_session() as s:
        run = s.get(TrainingRun, run_id)
        run.status, run.error, run.finished_at = "failed", error[:2000], datetime.now(timezone.utc)
    return {"status": "failed", "error": error}


@_task("os.retrain_if_enough_labels")
def retrain_if_enough_labels(self):
    cfg = get_settings()
    with system_session() as s:
        last = s.execute(select(func.max(TrainingRun.created_at))).scalar()
        q = select(func.count()).select_from(Label).where(Label.status == "active",
                                                          Label.consent_ai_training.is_(True))
        if last:
            q = q.where(Label.created_at > last)
        new = s.execute(q).scalar()
        if new < cfg.retrain_min_new_labels:
            return {"status": "waiting", "new_labels": new}
        run = TrainingRun(trigger="auto_labels", params={"new_labels": new})
        s.add(run)
        s.flush()
        rid = str(run.id)
    return retrain_head.apply(args=[rid]).get()


@_task("os.auto_rollback_check")
def auto_rollback_check(self):
    with system_session() as s:
        return mlops.auto_rollback_check(s)


@_task("os.drift_report")
def drift_report(self):
    with system_session() as s:
        res = monitoring.drift_report(s)
        if res.get("alert"):
            for lead in s.execute(select(Staff).where(Staff.role.in_(["clinical_lead", "admin"]))).scalars():
                notify_staff(s, lead.id, "staff_model_alert", detail=f"data drift detected: {res['metrics']}")
        return res


@_task("os.fairness_report")
def fairness_report(self):
    with system_session() as s:
        return monitoring.fairness_report(s)


# ───────────────────────── audit snapshot (WORM) ─────────────────────────
@_task("os.audit_snapshot")
def audit_snapshot(self, day: str | None = None):
    cfg = get_settings()
    d = date.fromisoformat(day) if day else date.today() - timedelta(days=1)
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    with system_session() as s:
        if s.execute(select(AuditSnapshot).where(AuditSnapshot.day == d)).scalars().first():
            return {"status": "exists"}
        rows = s.execute(select(AuditLog).where(AuditLog.ts >= start, AuditLog.ts < start + timedelta(days=1))
                         .order_by(AuditLog.id)).scalars().all()
        lines = [json.dumps({"id": r.id, "ts": r.ts.isoformat(), "actor_id": r.actor_id, "actor_role": r.actor_role,
                             "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id,
                             "patient_id": r.patient_id, "details": r.details, "prev_hash": r.prev_hash,
                             "hash": r.hash}, default=str) for r in rows]
        verify = audit.verify_chain_sync(s)
        payload = ("\n".join(lines) + "\n").encode()
        key = f"audit/{d.isoformat()}.jsonl"
        until = storage.retain_until(cfg.audit_retention_days)
        storage.put_bytes(cfg.bucket_audit, key, payload, "application/x-ndjson", retain_until=until)
        s.add(AuditSnapshot(day=d, first_id=rows[0].id if rows else None, last_id=rows[-1].id if rows else None,
                            head_hash=rows[-1].hash if rows else verify["head_hash"], object_key=key,
                            retain_until=until))
        return {"status": "ok", "rows": len(rows), "chain_ok": verify["ok"], "key": key}


# ───────────────────────── FHIR (optional HAPI server) ─────────────────────────
@_task("os.fhir_push")
def fhir_push(self, kind: str, id: str):
    cfg = get_settings()
    if not cfg.hapi_url:
        return {"status": "disabled"}
    import httpx

    from ..domain import fhir
    from ..models import Decision

    with system_session() as s:
        if kind == "ServiceRequest":
            obj = s.get(Referral, id)
            res = fhir.service_request(obj) if obj else None
            extra = [fhir.patient(s.get(Patient, obj.patient_id))] if obj else []
        elif kind == "DiagnosticReport":
            scr = s.get(Screening, id)
            dec = s.get(Decision, scr.decision_id) if scr and scr.decision_id else None
            res = fhir.diagnostic_report(scr, dec) if scr else None
            extra = ([fhir.patient(s.get(Patient, scr.patient_id))] + fhir.observations(scr)) if scr else []
        else:
            return {"status": "unsupported"}
    if res is None:
        return {"status": "missing"}
    from ..resilience import breaker

    for r in extra + [res]:
        breaker("hapi", 3, 60).call(lambda r=r: httpx.put(f"{cfg.hapi_url}/{r['resourceType']}/{r['id']}",
                                                          json=r, timeout=10).raise_for_status())
    return {"status": "pushed", "count": len(extra) + 1}


# ───────────────────────── ops metrics ─────────────────────────
@_task("os.ops_metrics")
def ops_metrics(self):
    with system_session() as s:
        pending = s.execute(select(func.count()).select_from(OutboxEvent)
                            .where(OutboxEvent.published_at.is_(None))).scalar()
        dl = s.execute(select(func.count()).select_from(DeadLetter).where(DeadLetter.resolved.is_(False))).scalar()
    OUTBOX_LAG.set(pending)
    DEAD_LETTERS.set(dl)
    return {"outbox_pending": pending, "dead_letters": dl}


# ───────────────────────── real system metrics ─────────────────────────
@_task("os.record_health")
def record_health(self):
    """Every minute: probe every service and sample server resources, so uptime, latency and incidents on the admin
    dashboard are measured history. Admins get an in-app alert when a service goes down or recovers, and when the
    disk passes 80%. Keeps 35 days of history."""
    from sqlalchemy import delete, text as sql

    from ..models import HostSample, ServiceCheck, Staff, SystemSetting
    from ..services import health

    now = datetime.now(timezone.utc)
    with system_session() as s:
        prev = {r[0]: r[1] for r in s.execute(sql(
            "SELECT DISTINCT ON (service) service, state FROM service_checks ORDER BY service, checked_at DESC"))}
        probes = health.probe_all(s)
        for p in probes:
            s.add(ServiceCheck(service=p["id"], state=p["state"], latency_ms=p["latency_ms"]))
        host = health.host_reading()
        s.add(HostSample(**host))
        admins = [a.id for a in s.execute(select(Staff).where(Staff.role == "admin")).scalars()]
        for p in probes:
            before = prev.get(p["id"])
            if before is None or before == p["state"]:
                continue
            if p["state"] == "down":
                detail = f"{p['name']} is DOWN (was {before})"
            elif before == "down":
                detail = f"{p['name']} recovered ({p['state']})"
            else:
                continue
            for a in admins:
                notify_staff(s, a, "staff_system_alert", related={"service": p["id"]}, detail=detail)
            log.warning("service_state_change", service=p["id"], before=before, after=p["state"])
        if host.get("disk_pct") and host["disk_pct"] >= 80:
            key = "alert:disk"
            last = s.get(SystemSetting, key)
            last_at = datetime.fromisoformat(last.value["at"]) if last else None
            if last_at is None or now - last_at > timedelta(hours=24):
                for a in admins:
                    notify_staff(s, a, "staff_system_alert", related={"resource": "disk"},
                                 detail=f"disk {host['disk_pct']}% full - free space or enlarge the volume")
                if last:
                    last.value = {"at": now.isoformat()}
                else:
                    s.add(SystemSetting(key=key, value={"at": now.isoformat()}))
        if now.minute == 0:                                  # hourly clean-up: keep 35 days
            cutoff = now - timedelta(days=35)
            s.execute(delete(ServiceCheck).where(ServiceCheck.checked_at < cutoff))
            s.execute(delete(HostSample).where(HostSample.sampled_at < cutoff))
    return {"services": {p["id"]: p["state"] for p in probes}, **{k: v for k, v in host.items() if v is not None}}


# ───────────────────────── DPDP storage limitation ─────────────────────────
@_task("os.data_retention")
def data_retention(self):
    """Nightly: delete patient messages and mouth photos that are no longer needed (periods are settings). Photos of
    patients who agreed to AI training are kept for that purpose until they withdraw. Every run is audited."""
    from sqlalchemy import text as sql

    from ..models import ScreeningImage

    cfg = get_settings()
    now = datetime.now(timezone.utc)
    with system_session() as s:
        msgs = s.execute(sql("DELETE FROM messages WHERE patient_id IS NOT NULL AND channel <> 'in_app' "
                             "AND created_at < now() - make_interval(days => :d)"),
                         {"d": cfg.retention_message_days}).rowcount
        old = s.execute(sql("""
            SELECT i.id FROM screening_images i JOIN screenings sc ON sc.id = i.screening_id
            WHERE sc.captured_at < now() - make_interval(days => :d) AND coalesce(i.upload_status, '') <> 'deleted'
              AND NOT EXISTS (SELECT 1 FROM consents c WHERE c.patient_id = sc.patient_id AND c.purpose = 'ai_training'
                              AND c.granted AND c.withdrawn_at IS NULL)
            LIMIT 5000"""), {"d": cfg.retention_photo_days}).scalars().all()
        for iid in old:
            img = s.get(ScreeningImage, iid)
            storage.delete(cfg.bucket_images, img.object_key)
            img.upload_status = "deleted"
        audit.record_sync(s, "system", "system", "retention.run", "system", None, None,
                          {"messages_deleted": msgs, "photos_deleted": len(old),
                           "message_days": cfg.retention_message_days, "photo_days": cfg.retention_photo_days,
                           "at": now.isoformat()})
    return {"messages_deleted": msgs, "photos_deleted": len(old)}


# ───────────────────────── hospital map: keep real hospital data warm ─────────────────────────
@_task("os.warm_nearby")
def warm_nearby(self):
    """Pre-load real hospitals (OpenStreetMap) and road times for every village, so the map opens instantly."""
    import asyncio

    from ..models import Village
    from ..services import nearby

    with system_session() as s:
        villages = [(v.name, v.lat, v.lon) for v in s.execute(select(Village)).scalars()]

    async def run():
        out = {}
        todo = list(villages)
        for attempt in range(2):                       # second pass for villages the busy servers refused
            failed = []
            for name, lat, lon in todo:
                try:
                    await one(name, lat, lon, out)
                except Exception as e:  # noqa: BLE001
                    out[name] = f"failed: {str(e)[:60]}"
                    failed.append((name, lat, lon))
                await asyncio.sleep(5)                 # be polite to the free public servers
            if not failed:
                break
            todo = failed
            await asyncio.sleep(90)
        return out

    async def one(name, lat, lon, out):
        places = await nearby.places_near(lat, lon)
        for p in places:
            p["crowKm"] = nearby.haversine_km(lat, lon, p["lat"], p["lon"])
        places.sort(key=lambda p: p["crowKm"])
        await nearby.travel_times(lat, lon, places[:60])
        out[name] = len(places)

    return asyncio.run(run())
