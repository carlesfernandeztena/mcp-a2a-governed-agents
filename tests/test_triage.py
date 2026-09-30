"""Harness post-processing: the result is built from the LLM draft plus what the skills returned."""
from agents.triage.agent import assemble
from harness.contract import TriageDraft

draft = TriageDraft.model_validate({
    "status": "proposal",
    "diagnosis": {"cause": "door_gasket_worn", "confidence": "high", "summary": "Worn gasket."},
    "evidence": [{"ref": "TEL-5123-2026-10-01", "claim": "-74.0 °C"}],
    "advice": [],
})
context = ("get_instrument_context", {"serial": "5123"}, {"instrument": {"id": "INS-5123"}, "samples_at_risk": False, "flags": []})
accepted = ("propose_parts_order", {"serial": "5123", "part_number": "GK-80-B"},
            {"accepted": True, "proposal": {"part_number": "GK-80-B", "name": "GasketKit 80-B", "qty": 1, "chargeable": False}, "flags": []})
refused = ("propose_parts_order", {"serial": "5123", "part_number": "GK-80-A"}, {"accepted": False, "reason": "wrong_revision", "rule": "R-ORD-1"})


def test_parts_come_from_accepted_proposals_not_from_the_llm():
    r = assemble(draft, [context, refused, accepted]).dump()
    assert [p["part_number"] for p in r["parts"]] == ["GK-80-B"]
    assert r["approval"] == {"required": True, "approver_role": "service_manager", "state": "pending"}
    assert (r["urgency"], r["samples_at_risk"]) == ("routine", False)


def test_urgency_follows_sample_risk_and_unknown_stays_null():
    at_risk = ("get_instrument_context", {}, {"instrument": {}, "samples_at_risk": True, "flags": []})
    assert assemble(draft, [at_risk]).dump()["urgency"] == "urgent"
    unknown = ("get_instrument_context", {}, {"instrument": {}, "samples_at_risk": None, "flags": ["telemetry_missing"]})
    r = assemble(draft, [unknown]).dump()
    assert r["samples_at_risk"] is None and r["urgency"] == "routine" and r["flags"] == ["telemetry_missing"]
    assert "approval" not in r and r["parts"] == []


def test_denial_and_unknown_serial_are_decided_by_code():
    denied = assemble(None, [], {"denied": {"reason": "territory", "enforced_at": "dataproducts/instruments"}}).dump()
    assert denied["status"] == "denied" and denied["denial"]["reason"] == "territory" and "diagnosis" not in denied
    missing = assemble(None, [], {"flag": "instrument_not_found"}).dump()
    assert missing["status"] == "escalate" and missing["flags"] == ["instrument_not_found"] and missing["diagnosis"]["cause"] == "unknown"


def test_chargeable_flag_travels_from_the_skill():
    charged = ("propose_parts_order", {}, {"accepted": True, "proposal": {"part_number": "GK-80-A", "name": "GasketKit 80-A", "qty": 1, "chargeable": True},
                                           "flags": ["chargeable_needs_po"]})
    r = assemble(draft, [context, charged]).dump()
    assert r["flags"] == ["chargeable_needs_po"] and r["parts"][0]["chargeable"] is True
