"""Approve (or reject) a parts proposal as a human (R-ACC-2, R-ORD-4). Only a service manager may approve.

    uv run python -m cli.approve P-<trace>-GK-80-B --as grant
    uv run python -m cli.approve P-<trace>-GK-80-B --as yusuf      # refused: engineers propose, managers approve
"""
import argparse

from harness import audit, badges


def decide(proposal_id: str, user: str, approve: bool = True) -> dict:
    badge = badges.verify(badges.user_badge(user))  # a human decision: the person's own badge, no agent
    events = [e for e in audit.read() if e.get("proposal", {}).get("proposal_id") == proposal_id or e.get("proposal_id") == proposal_id]
    proposed = next((e for e in events if e["action"] == "proposed"), None)
    if proposed is None:
        return {"error": "unknown proposal"}
    trace = proposed["trace"]
    if badge["role"] != "service_manager":
        audit.write(trace, "approvals", "refused", badge, proposal_id=proposal_id, detail=f"{user} is {badge['role']}, approval needs service_manager")
        return {"refused": f"{user} is a {badge['role']}; only a service manager approves (R-ACC-2)"}
    if any(e["action"] in ("approved", "rejected") for e in events):
        return {"error": "already decided"}
    action = "approved" if approve else "rejected"
    audit.write(trace, "approvals", action, badge, proposal_id=proposal_id)
    if approve:
        # STUB: ERP submission. A real deployment sends the order to the ERP (e.g. SAP) here, idempotently,
        # with retries and reconciliation. The demo records what would have been sent and stops.
        audit.write(trace, "erp", "submission_stubbed", badge, proposal_id=proposal_id, order=proposed["proposal"])
    return {"proposal_id": proposal_id, "state": action, "by": user}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("proposal_id")
    p.add_argument("--as", dest="user", default="grant")
    p.add_argument("--reject", action="store_true")
    a = p.parse_args()
    print(decide(a.proposal_id, a.user, not a.reject))
