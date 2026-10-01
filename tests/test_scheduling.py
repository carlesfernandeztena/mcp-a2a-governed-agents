"""Scheduling rules R-SCH-0..3 (pure code, no A2A transport) and the triage harness's visit handling."""
from agents.scheduling.agent import deadline, earliest_slot, propose_visit
from agents.triage.agent import add_visit
from harness.contract import TriageResult


def test_deadlines_count_business_days_from_friday():
    assert deadline("gold", "routine").isoformat() == "2026-10-06T18:00:00+02:00"    # Fri + 2 business days = Tue
    assert deadline("silver", "routine").isoformat() == "2026-10-09T18:00:00+02:00"  # + 5 = next Fri
    assert deadline("gold", "urgent").isoformat() == "2026-10-05T18:00:00+02:00"     # next business day = Mon
    assert deadline("none", "urgent") is None                                         # no contract, no SLA


def test_only_engineers_of_the_sites_country():
    assert earliest_slot("ES")["engineer"] == "mariona"     # Nate's earlier Boston slot is never offered
    assert earliest_slot("NO")["engineer"] == "sven"


def test_eval_visits():
    gold_es = {"contract_tier": "gold", "country": "ES"}
    assert propose_visit(gold_es, "routine") == {"engineer": "mariona", "start": "2026-10-05T14:00:00+02:00", "end": "2026-10-05T16:00:00+02:00",
                                                 "sla_deadline": "2026-10-06T18:00:00+02:00", "within_sla": True}
    fjord = propose_visit({"contract_tier": "gold", "country": "NO"}, "urgent")
    assert (fjord["engineer"], fjord["start"], fjord["within_sla"]) == ("sven", "2026-10-06T09:00:00+02:00", False)   # L4-06
    no_contract = propose_visit({"contract_tier": "none", "country": "ES"}, "routine")
    assert "sla_deadline" not in no_contract and "within_sla" not in no_contract                                      # L4-04


def test_breach_and_unreachable_scheduler_are_flagged():
    r = TriageResult(status="proposal", flags=["chargeable_needs_po"])
    add_visit(r, {"visit": {"engineer": "sven", "within_sla": False}})
    assert r.dump()["flags"] == ["chargeable_needs_po", "sla_breach"]
    r = TriageResult(status="proposal")
    add_visit(r, {"error": "ConnectError"})
    assert "visit" not in r.dump() and r.dump()["flags"] == ["scheduling_unavailable"]
