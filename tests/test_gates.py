"""The gates catch wrong actions, bad grounding and plausible-wrong answers; a correct answer passes."""
import json

from evals.gates import check, gate_results
from harness.rules import ROOT

CASES = {c["id"]: c for c in map(json.loads, (ROOT / "evals" / "cases.jsonl").read_text().splitlines())}

GOOD = {
    "status": "proposal",
    "diagnosis": {"cause": "door_gasket_worn", "confidence": "high", "summary": "x"},
    "evidence": [{"ref": "TEL-5123-2026-10-01", "claim": "Cabinet at −74.0 °C, recovery 45 min, current 4.4 A"},
                 {"ref": "MAN-CX80-E47", "claim": "normal current → gasket"}, {"ref": "SRV-0362", "claim": "gasket hardening"}],
    "parts": [{"part_number": "GK-80-B", "name": "GasketKit 80-B", "qty": 1, "chargeable": False}],
    "urgency": "routine", "samples_at_risk": False,
    "visit": {"engineer": "mariona", "start": "2026-10-05T14:00:00+02:00", "end": "2026-10-05T16:00:00+02:00",
              "sla_deadline": "2026-10-06T18:00:00+02:00", "within_sla": True},
}


def test_correct_answer_passes_every_check():
    assert check(CASES["L2-01"], GOOD) == {"action": [], "grounding": []}


def test_plausible_wrong_part_fails_action():
    wrong = GOOD | {"parts": [{"part_number": "GK-80-A", "name": "GasketKit 80-A", "qty": 1, "chargeable": False}]}
    fails = check(CASES["L2-01"], wrong)["action"]
    assert any("forbidden" in f for f in fails) and any("parts[].part_number" in f for f in fails)


def test_grounding_catches_invented_numbers_wrong_freezer_and_missing_records():
    bad = GOOD | {"evidence": [{"ref": "TEL-5123-2026-10-01", "claim": "Cabinet at -72.5 °C"},
                               {"ref": "SRV-0467", "claim": "gasket replaced"},          # 5301's record
                               {"ref": "SRV-9999", "claim": "?"}]}
    fails = check(CASES["L2-01"], bad)["grounding"]
    assert any("numbers" in f for f in fails) and any("not about SN 5123" in f for f in fails)
    assert any("no such record" in f for f in fails) and any("must cite MAN-CX80-E47" in f for f in fails)


def test_null_absent_and_empty_list_conventions():
    escalated = {"status": "escalate", "diagnosis": {"cause": "unknown", "confidence": "low", "summary": "x"}, "evidence": [],
                 "samples_at_risk": None, "urgency": "routine", "flags": ["telemetry_missing"]}
    assert check(CASES["L3-02"], escalated)["action"] == []            # parts absent counts as []
    assert check(CASES["L3-02"], escalated | {"samples_at_risk": False})["action"]   # unknown must stay null
    assert check(CASES["L3-02"], escalated | {"visit": {"engineer": "x"}})["action"]  # visit must be absent


def test_a_gate_fails_if_any_of_its_cases_fails():
    results = {"L2-01": GOOD, "L2-02": GOOD}
    gates = gate_results([CASES["L2-01"], CASES["L2-02"]], results)
    assert not gates["G2"]["failed"].get("L2-01") and "L2-02" in gates["G3"]["failed"]
