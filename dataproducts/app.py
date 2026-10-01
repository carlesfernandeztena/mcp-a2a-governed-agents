"""Data products: governed datasets behind one small HTTP service, one route per product.

Every request must carry a delegated badge (a user AND an agent, R-ACC-4). Customer data is checked
at the door: territory (R-ACC-1) and regulated records (R-RSK-2). Every answer is audited with the
record ids and a hash of what was returned, so a third party can see exactly what the agent saw.
"""
import csv
import hashlib
import json
import re

from fastapi import Depends, FastAPI, Header, HTTPException

from harness import audit, badges
from harness.policy import Denied, check_agent, check_instrument_access
from harness.rules import ROOT, rules

DATA = ROOT / "data"
app = FastAPI(title="Data products")


def _csv(name: str) -> list[dict]:
    with open(DATA / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


INSTRUMENTS = {r["serial"]: r for r in _csv("instruments.csv")}
SERVICE = _csv("service_records.csv")
TELEMETRY = _csv("telemetry.csv")
PARTS = {r["part_number"]: r for r in _csv("parts_catalog.csv")}
MANUAL = [
    {"id": m.group(1), "title": m.group(2).strip(), "text": m.group(3).strip()}
    for m in re.finditer(r"^## (MAN-[\w-]+) — (.*?)\n(.*?)(?=^## |\Z)", (DATA / "manual_cryonix80.md").read_text(encoding="utf-8"), re.M | re.S)
]
SUSPICIOUS = [re.compile(p, re.I) for p in rules()["safety"]["suspicious_patterns"]]


class Caller:
    def __init__(self, badge: dict, trace: str):
        self.badge, self.trace = badge, trace


def caller(authorization: str | None = Header(None), x_trace_id: str | None = Header(None)) -> Caller:
    trace = x_trace_id or audit.new_trace()
    try:
        badge = badges.from_header(authorization)
        check_agent(badge)  # R-ACC-4 on every route: a user AND a registered agent
    except PermissionError as e:
        audit.write(trace, "dataproducts", "refused", detail=str(e))
        raise HTTPException(401, str(e)) from None
    return Caller(badge, trace)


def _served(c: Caller, product: str, records: list[dict], **extra) -> list[dict]:
    body = json.dumps(records, sort_keys=True).encode()
    audit.write(c.trace, f"dataproducts/{product}", "read", c.badge, records=[r["id"] for r in records],
                sha256=hashlib.sha256(body).hexdigest(), **extra)
    return records


def _instrument(c: Caller, serial: str, product: str) -> dict:
    inst = INSTRUMENTS.get(serial)
    if not inst:
        audit.write(c.trace, f"dataproducts/{product}", "not_found", c.badge, serial=serial)
        raise HTTPException(404, {"flag": "instrument_not_found", "serial": serial})
    try:
        check_instrument_access(c.badge, inst, enforced_at=f"dataproducts/{product}")
    except Denied as d:
        audit.write(c.trace, d.enforced_at, "denied", c.badge, serial=serial, reason=d.reason, detail=d.detail)
        raise HTTPException(403, {"denial": {"reason": d.reason, "enforced_at": d.enforced_at}}) from None
    return inst


def _typed(row: dict) -> dict:
    """CSV strings → JSON types. Empty cells mean "does not apply", so they are left out (contract convention)."""
    out = {}
    for k, v in row.items():
        if v == "":
            continue
        if k == "serial":
            out[k] = v
        elif v in ("true", "false"):
            out[k] = v == "true"
        elif re.fullmatch(r"-?\d+", v):
            out[k] = int(v)
        elif re.fullmatch(r"-?\d+\.\d+", v):
            out[k] = float(v)
        else:
            out[k] = v
    return out


@app.get("/instruments/{serial}")
def instrument(serial: str, c: Caller = Depends(caller)) -> dict:
    return _served(c, "instruments", [_typed(_instrument(c, serial, "instruments"))])[0]


@app.get("/service-records")
def service_records(serial: str, c: Caller = Depends(caller)) -> list[dict]:
    """R-SAF-6: free text that looks like an instruction is returned marked, never obeyed."""
    inst = _instrument(c, serial, "service-records")
    records = [_typed(r) | {"suspicious": any(p.search(r["note"]) for p in SUSPICIOUS)}
               | ({"parts_replaced": r["parts_replaced"].split(";")} if r["parts_replaced"] else {})
               for r in SERVICE if r["instrument"] == inst["id"]]
    flagged = [r["id"] for r in records if r["suspicious"]]
    return _served(c, "service-records", records, **({"suspicious": flagged} if flagged else {}))


@app.get("/telemetry")
def telemetry(serial: str, c: Caller = Depends(caller)) -> list[dict]:
    inst = _instrument(c, serial, "telemetry")
    return _served(c, "telemetry", [_typed(r) for r in TELEMETRY if r["instrument"] == inst["id"]])


@app.get("/manuals/search")
def manuals(q: str, c: Caller = Depends(caller)) -> list[dict]:
    """simplification: keyword overlap over a handful of sections; production = hybrid search (PATH_TO_PRODUCTION)."""
    terms = {t for t in re.findall(r"[\w-]+", q.lower()) if len(t) > 2}
    scored = [(sum(t in (s["id"] + s["title"] + s["text"]).lower() for t in terms), s) for s in MANUAL]
    return _served(c, "manuals", [s for score, s in sorted(scored, key=lambda x: -x[0]) if score][:3], query=q)


@app.get("/parts/{part_number}")
def part(part_number: str, c: Caller = Depends(caller)) -> dict:
    p = PARTS.get(part_number)
    if not p:
        audit.write(c.trace, "dataproducts/parts", "not_found", c.badge, part_number=part_number)
        raise HTTPException(404, {"reason": "not_in_catalog", "part_number": part_number})
    return _served(c, "parts", [_typed(p) | {"fits_revisions": p["fits_revisions"].split(";")}])[0]
