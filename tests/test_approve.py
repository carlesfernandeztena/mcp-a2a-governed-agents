"""Approval is a human step: engineers propose, only a service manager approves (R-ACC-2, R-ORD-4)."""
from cli.approve import decide
from harness import audit, badges


def test_only_grant_approves_once_and_erp_is_stubbed():
    trace = audit.new_trace()
    badge = badges.verify(badges.exchange(badges.user_badge("yusuf"), badges.agent_badge("triage-agent")))
    pid = f"P-{trace}-GK-80-B"
    audit.write(trace, "skills/propose_parts_order", "proposed", badge, proposal={"proposal_id": pid, "part_number": "GK-80-B"})
    assert "refused" in decide(pid, "yusuf")
    assert decide(pid, "grant")["state"] == "approved"
    assert decide(pid, "grant") == {"error": "already decided"}
    actions = [e["action"] for e in audit.read(trace)]
    assert actions == ["proposed", "refused", "approved", "submission_stubbed"]
    assert decide("P-nope", "grant") == {"error": "unknown proposal"}
