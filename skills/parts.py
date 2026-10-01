"""Skill `propose_parts_order` (T3): the LLM proposes a part; code checks it against the records and
has the last word (R-ORD-1/2/3/5/6/7). A wrong diagnosis or an injected instruction can never become
a wrong order. An accepted proposal still waits for Grant's approval (R-ORD-4)."""
import os
from datetime import date

from mcp.server.mcpserver import Context, MCPServer

from harness.rules import rules
from skills._skill import Call, blocked, latest_fresh, run, seg, today

VERSION = os.environ.get("PARTS_SKILL_VERSION", "1.0")
mcp = MCPServer("parts", instructions="Propose a parts order; every proposal is checked against the records.")


def revision_of(instrument: dict) -> str:
    if VERSION == "0.4":
        # Deliberate regression for demo scene SC7: v0.4 "saves a lookup" by deriving the revision from the
        # serial, with the boundary wrong (5500 instead of 5000). The eval gates must block this build.
        return "A" if int(instrument["serial"]) <= 5500 else "B"
    return instrument["revision"]


def evidence(latest: dict | None) -> set[str]:
    """R-ORD-7: which parts the latest telemetry justifies. No current telemetry → nothing."""
    if not latest:
        return set()
    d = rules()["diagnosis"]
    shown = set()
    if latest["compressor_current_a"] >= d["compressor_current_min_a"]:
        shown.add("compressor")
    elif latest["cabinet_temp_c"] > d["e47_daily_mean_above_c"]:
        shown.add("gasket")
    if latest["condenser_temp_c"] > d["e21_condenser_above_c"]:
        shown.add("filter")
    return shown


def check(part: dict | None, instrument: dict, records: list[dict], latest: dict | None, qty: int) -> tuple[str, str] | None:
    """Returns (reason, rule) for a refusal, or None if the proposal is acceptable. Order = cheapest check first."""
    if part is None:
        return "not_in_catalog", "R-ORD-2"
    if revision_of(instrument) not in part["fits_revisions"]:
        return "wrong_revision", "R-ORD-1"
    if qty < 1 or qty > rules()["ordering"]["max_qty_per_part"]:  # R-ORD-5 covers any quantity outside 1..max
        return "quantity_over_limit", "R-ORD-5"
    window = rules()["diagnosis"]["recent_replacement_days"]
    if any(part["part_number"] in r.get("parts_replaced", []) and (today() - date.fromisoformat(r["date"])).days <= window for r in records):
        return "replaced_recently", "R-ORD-6"
    if rules()["ordering"]["evidence"].get(part["part_number"]) not in evidence(latest):
        return "evidence_missing", "R-ORD-7"
    return None


def chargeable(instrument: dict) -> bool:
    """R-ORD-3: no contract, or an expired one, means the customer pays."""
    end = instrument.get("contract_end")
    return instrument["contract_tier"] == "none" or not end or date.fromisoformat(end) < today()


def propose(call: Call, serial: str, part_number: str, qty: int = 1) -> dict:
    r = call.get(f"/instruments/{seg(serial)}")
    if stop := blocked(r):
        return stop
    instrument = r.json()
    p = call.get(f"/parts/{seg(part_number)}")
    if p.status_code != 404:
        p.raise_for_status()  # a catalog outage is an error, never "not in catalog"
    part = p.json() if p.status_code == 200 else None
    records = call.data("/service-records", serial=serial)
    latest = latest_fresh(call.data("/telemetry", serial=serial))

    if refusal := check(part, instrument, records, latest, qty):
        reason, rule = refusal
        call.log("refused", serial=serial, part_number=part_number, qty=qty, reason=reason, rule=rule, skill_version=VERSION)
        return {"accepted": False, "reason": reason, "rule": rule}

    pays = chargeable(instrument)
    proposal = {"proposal_id": f"P-{call.trace}-{part['part_number']}", "serial": instrument["serial"], "part_number": part["part_number"], "name": part["name"],
                "qty": qty, "price_eur": part["price_eur"], "chargeable": pays, "state": "pending_approval"}
    call.log("proposed", skill_version=VERSION, proposal=proposal)
    return {"accepted": True, "proposal": proposal, "flags": ["chargeable_needs_po"] if pays else []}


@mcp.tool()
def propose_parts_order(serial: str, part_number: str, ctx: Context, qty: int = 1) -> dict:
    """Propose ordering a part for one freezer. Code checks catalog, revision, quantity, recent replacements and
    telemetry evidence; a refusal returns the reason and the rule id. Accepted proposals wait for manager approval."""
    return run(propose, "propose_parts_order", ctx, serial=serial, part_number=part_number, qty=qty)


if __name__ == "__main__":
    mcp.run("streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", 8103)))
