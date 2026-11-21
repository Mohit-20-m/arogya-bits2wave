"""Health probes and server resource readings, shared by the admin page and the worker's minute-by-minute recorder.

The worker stores every probe (service_checks) and a resource sample (host_samples), so uptime, latency and
incidents shown to the administrator are measured history, not a snapshot.
"""
from __future__ import annotations

import os
import shutil
import time

import httpx
from sqlalchemy import text

from .. import storage
from ..config import get_settings

SERVICES = [
    ("api", "API gateway"),
    ("postgres", "PostgreSQL (data, RLS, audit chain)"),
    ("opa", "OPA policy engine"),
    ("inference", "AI inference (EfficientNetV2-S, ONNX Runtime)"),
    ("keycloak", "Keycloak identity"),
    ("vault", "Vault secrets"),
    ("redis", "Job queue (Redis)"),
    ("storage", "Object storage (photos)"),
]
STATE_TEXT = {"operational": "Responding normally", "degraded": "Responding slowly or partly",
              "down": "Not reachable - work is queued or refused safely"}


def _urls() -> dict:
    cfg = get_settings()
    return {"opa": f"{cfg.opa_url}/health", "inference": f"{cfg.inference_url}/ready",
            "keycloak": f"{cfg.keycloak_internal_url}/realms/{cfg.keycloak_realm}" if cfg.auth_mode == "keycloak"
            else None,
            "vault": f"{cfg.vault_addr}/v1/sys/health",
            "api": f"{os.environ.get('OS_SELF_URL', 'http://api:8000')}/api/health"}


def probe_all(session) -> list[dict]:
    """Synchronous probes (worker). Returns [{id, name, state, latency_ms}]."""
    cfg = get_settings()
    urls = _urls()
    out = []
    with httpx.Client(timeout=4) as h:
        for sid, name in SERVICES:
            t0, state = time.perf_counter(), "operational"
            try:
                if sid == "postgres":
                    session.execute(text("SELECT 1"))
                elif sid == "redis":
                    import redis

                    r = redis.from_url(cfg.redis_url, socket_timeout=2)
                    r.ping()
                    r.close()
                elif sid == "storage":
                    storage.client().head_bucket(Bucket=cfg.bucket_images)
                elif urls.get(sid):
                    resp = h.get(urls[sid])
                    state = "operational" if resp.status_code < 500 else "degraded"
                else:
                    state = "degraded"
            except Exception:  # noqa: BLE001
                state = "down"
            out.append({"id": sid, "name": name, "state": state,
                        "latency_ms": round((time.perf_counter() - t0) * 1000)})
    return out


def _meminfo() -> dict:
    vals = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                vals[k] = int(v.strip().split()[0])
    except OSError:
        pass
    return vals


def host_reading() -> dict:
    """CPU (1-minute load relative to cores), memory and disk use of the machine running the containers."""
    try:
        load1 = os.getloadavg()[0]
    except OSError:
        load1 = None
    cpus = os.cpu_count() or 1
    mem = _meminfo()
    mem_pct = None
    if mem.get("MemTotal"):
        mem_pct = round(100 * (1 - mem.get("MemAvailable", mem.get("MemFree", 0)) / mem["MemTotal"]), 1)
    try:
        du = shutil.disk_usage("/")
        disk_pct = round(100 * du.used / du.total, 1)
    except OSError:
        disk_pct = None
    return {"cpu_pct": None if load1 is None else round(min(100.0, 100 * load1 / cpus), 1),
            "mem_pct": mem_pct, "disk_pct": disk_pct, "load1": load1}
