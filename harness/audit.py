"""Audit and lineage: one JSON line per action, from every component, joined by trace id (R-SAF-3)."""
import json
import os
import time
import uuid
from pathlib import Path

from harness.rules import ROOT

LOG = Path(os.environ.get("AUDIT_LOG", ROOT / "audit" / "audit.jsonl"))


def new_trace() -> str:
    return uuid.uuid4().hex[:12]


def write(trace: str, component: str, action: str, badge: dict | None = None, **detail) -> dict:
    """ponytail: append-only local file; production = tamper-evident store with retention (PATH_TO_PRODUCTION)."""
    act = (badge or {}).get("act") or {}
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        "trace": trace,
        "component": component,
        "action": action,
        "user": (badge or {}).get("sub"),
        "agent": act.get("sub"),
        "agent_version": act.get("version"),
        **detail,
    }
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read(trace: str | None = None) -> list[dict]:
    if not LOG.exists():
        return []
    events = [json.loads(line) for line in LOG.read_text().splitlines()]
    return [e for e in events if trace is None or e["trace"] == trace]
