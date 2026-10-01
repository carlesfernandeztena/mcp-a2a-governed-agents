"""Harness post-processing: the result is built from the LLM draft plus what the skills returned."""
from agents.triage.agent import assemble
from harness.contract import TriageDraft


def draft(status="proposal"):
    return TriageDraft.model_validate({
        "status": status,
        "diagnosis": {"cause": "door_gasket_worn", "confidence": "high", "summary": "Worn gasket."},
        "evidence": [{"ref": "TEL-5123-2026-10-01", "claim": "-74.0 °C"}],
        "advice": [],
    })


context = ("get_instrument_context", {"serial": "5123"}, {"instrument": {"id": "INS-5123"}, "samples_at_risk": False, "flags": []})
accepted = ("propose_parts_order", {"serial": "5123", "part_number": "GK-80-B"},
            {"accepted": True, "proposal": {"serial": "5123", "part_number": "GK-80-B", "name": "GasketKit 80-B", "qty": 1, "chargeable": False}, "flags": []})
refused = ("propose_parts_order", {"serial": "5123", "part_number": "GK-80-A"}, {"accepted": False, "reason": "wrong_revision", "rule": "R-ORD-1"})


def test_parts_come_from_accepted_proposals_not_from_the_llm():
    r = assemble(draft(), [context, refused, accepted, accepted]).dump()
    assert [p["part_number"] for p in r["parts"]] == ["GK-80-B"]          # deduplicated, refused one ignored
    assert r["approval"] == {"required": True, "approver_role": "service_manager", "state": "pending"}
    assert (r["status"], r["urgency"], r["samples_at_risk"]) == ("proposal", "routine", False)


def test_status_is_derived_not_taken_from_the_llm():
    assert assemble(draft("no_action"), [context, accepted]).dump()["status"] == "proposal"   # a part was accepted
    assert assemble(draft("proposal"), [context, refused]).dump()["status"] == "escalate"     # claimed proposal, nothing accepted
    assert assemble(draft("no_action"), [context]).dump()["status"] == "no_action"


def test_urgency_follows_sample_risk_and_unknown_stays_null():
    at_risk = ("get_instrument_context", {}, {"instrument": {}, "samples_at_risk": True, "flags": []})
    assert assemble(draft(), [at_risk]).dump()["urgency"] == "urgent"
    unknown = ("get_instrument_context", {}, {"instrument": {}, "samples_at_risk": None, "flags": ["telemetry_missing"]})
    r = assemble(draft("no_action"), [unknown]).dump()
    assert r["status"] == "escalate" and r["samples_at_risk"] is None and r["urgency"] == "routine" and r["flags"] == ["telemetry_missing"]
    assert "approval" not in r and r["parts"] == []


def test_denial_and_unknown_serial_are_decided_by_code():
    denied = assemble(None, [], {"denied": {"reason": "territory", "enforced_at": "dataproducts/instruments"}}).dump()
    assert denied["status"] == "denied" and denied["denial"]["reason"] == "territory" and "diagnosis" not in denied
    missing = assemble(None, [], {"flag": "instrument_not_found"}).dump()
    assert missing["status"] == "escalate" and missing["flags"] == ["instrument_not_found"] and missing["diagnosis"]["cause"] == "unknown"


def test_runtime_grounding_checks_only_what_this_run_saw():
    from agents.triage.agent import runtime_problems
    tel = {"id": "TEL-5123-2026-10-01", "instrument": "INS-5123", "cabinet_temp_c": -74.0, "recovery_min": 45}
    ctx = ("get_instrument_context", {"serial": "5123"}, {"instrument": {"id": "INS-5123"}, "service_records": [], "telemetry": [tel],
                                                          "latest_telemetry": tel, "samples_at_risk": False, "flags": []})
    manual = ("search_manuals", {"query": "E-47"}, {"sections": [{"id": "MAN-CX80-E47", "title": "E-47", "text": "creep"}]})
    tel_only = draft()                                                   # cites TEL-5123-2026-10-01 "-74.0 °C"
    assert runtime_problems(tel_only, [ctx], "5123") == ["must cite MAN-CX80-E47", "call search_manuals('MAN-CX80-E47') and cite that section"]
    good = TriageDraft.model_validate(tel_only.model_dump() | {"evidence": [*tel_only.model_dump()["evidence"], {"ref": "MAN-CX80-E47", "claim": "gasket signs"}]})
    assert runtime_problems(good, [ctx, manual], "5123") == []          # the diagnosis cites the section it comes from
    unseen = TriageDraft.model_validate(good.model_dump() | {"evidence": [*good.model_dump()["evidence"], {"ref": "SRV-0142", "claim": "gasket fitted"}]})
    assert any("SRV-0142: no such record" in p for p in runtime_problems(unseen, [ctx, manual], "5123"))
    risky = ("get_instrument_context", {}, {**ctx[2], "samples_at_risk": True})
    found = runtime_problems(good, [risky, manual], "5123")
    assert "must cite MAN-CX80-SAMPLES" in found and any("search_manuals('MAN-CX80-SAMPLES')" in p for p in found)


def test_chargeable_flag_travels_from_the_skill():
    charged = ("propose_parts_order", {}, {"accepted": True, "proposal": {"serial": "3355", "part_number": "GK-80-A", "name": "GasketKit 80-A", "qty": 1,
                                                                          "chargeable": True}, "flags": ["chargeable_needs_po"]})
    r = assemble(draft(), [context, charged]).dump()
    assert r["flags"] == ["chargeable_needs_po"] and r["parts"][0]["chargeable"] is True
