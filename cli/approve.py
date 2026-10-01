"""Approve (or reject) a parts proposal as a human (R-ACC-2, R-ORD-4). Only a service manager may approve.
`demo approve grant` (cli/__main__.py); defaults to the last proposal."""
from harness import audit, badges


def last_proposal() -> str | None:
    return next((e["proposal"]["proposal_id"] for e in reversed(audit.read()) if e["action"] == "proposed"), None)


def decide(proposal_id: str, user: str, approve: bool = True) -> dict:
    if user not in badges.people():
        return {"error": f"unknown user {user}"}
    # Part of the identity-provider stub (harness/badges.py): `--as` mints the person's badge locally; a real
    # deployment takes the approver's identity from SSO + MFA, so nobody can approve "as grant" by typing it.
    badge = badges.verify(badges.user_badge(user))  # a human decision: the person's own badge, no agent
    events = [e for e in audit.read() if e.get("proposal", {}).get("proposal_id") == proposal_id or e.get("proposal_id") == proposal_id]
    proposed = next((e for e in events if e["action"] == "proposed"), None)
    if proposed is None:
        audit.write(audit.new_trace(), "approvals", "refused", badge, proposal_id=proposal_id, detail="unknown proposal")
        return {"error": "unknown proposal"}
    trace = proposed["trace"]
    if badge["role"] != "service_manager":
        audit.write(trace, "approvals", "refused", badge, proposal_id=proposal_id, detail=f"{user} is {badge['role']}, approval needs service_manager")
        return {"refused": f"{user} is a {badge['role']}; only a service manager approves (R-ACC-2)"}
    if any(e["action"] in ("approved", "rejected") for e in events):  # simplification: read-then-write; a real store needs a transaction
        audit.write(trace, "approvals", "refused", badge, proposal_id=proposal_id, detail="already decided")
        return {"error": "already decided"}
    action = "approved" if approve else "rejected"
    audit.write(trace, "approvals", action, badge, proposal_id=proposal_id)
    if approve:
        # STUB: ERP submission. A real deployment sends the order to the ERP (e.g. SAP) here, idempotently,
        # with retries and reconciliation. The demo records what would have been sent and stops.
        audit.write(trace, "erp", "submission_stubbed", badge, proposal_id=proposal_id, order=proposed["proposal"])
    return {"proposal_id": proposal_id, "state": action, "by": user}
