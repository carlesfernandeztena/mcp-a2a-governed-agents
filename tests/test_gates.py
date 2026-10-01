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


def test_denied_answer_may_not_leak_any_day_of_the_denied_freezer():
    leak = {"status": "denied", "denial": {"reason": "territory", "enforced_at": "x"}, "parts": [],
            "evidence": [{"ref": "TEL-7001-2026-10-01", "claim": "-76.0 °C"}]}
    assert any("forbidden" in f for f in check(CASES["L4-02"], leak)["action"])


def test_a_crash_passes_nothing():
    crashed = {"status": "error", "error": "Timeout"}
    assert all(check(CASES["L4-08"], crashed).values())


def test_number_check_ignores_ids_codes_durations_and_reads_commas():
    from evals.gates import RECORDS, problems

    def numbers_match(ref, claim, cited, serial):
        others = [{"ref": c, "claim": ""} for c in cited if c != ref]
        return not problems([{"ref": ref, "claim": claim}] + others, RECORDS, serial)
    cited = ["TEL-5123-2026-09-18", "TEL-5123-2026-10-01"]
    assert numbers_match("TEL-5123-2026-10-01", "Freezer 5123 (Cryonix 80): E47 since 1 Oct 2026, −80.0 → -74,0 °C over 14 days", cited, "5123")
    assert not numbers_match("TEL-5123-2026-10-01", "Cabinet at -72.5 °C", cited, "5123")
    assert not numbers_match("TEL-5123-2026-10-01", "Cabinet at 74.0 °C", cited, "5123")      # sign matters
    # comparing a reading with the manual's range: the range numbers come from the cited manual section
    claim = "current 4.4 A; the manual's normal range is 3.8–4.8 A and slow recovery is above 30 min"
    assert numbers_match("TEL-5123-2026-10-01", claim, cited + ["MAN-CX80-E47"], "5123")
    assert not numbers_match("TEL-5123-2026-10-01", claim, cited, "5123")                     # without the manual cited
    assert not numbers_match("TEL-5123-2026-10-01", "compressor current 5 A", cited + ["MAN-CX80-E47"], "5123")  # manual-only number
    assert numbers_match("TEL-5123-2026-10-01", "La temperatura pasó de -80.0 °C el 18/09 a -74.0 °C el 01/10", cited, "5123")  # dd/mm dates
    assert numbers_match("TEL-5123-2026-10-01", "−80.0 °C on 18 Sept, −74.0 °C since Oct 1 (el 25 de septiembre: E-47)", cited, "5123")  # day-month dates
    assert not numbers_match("TEL-5123-2026-10-01", "recovery 44 min", cited, "5123")             # "min" is not a month


def test_a_gate_fails_if_any_of_its_cases_fails():
    results = {"L2-01": GOOD, "L2-02": GOOD}
    gates = gate_results([CASES["L2-01"], CASES["L2-02"]], results)
    assert not gates["G2"]["failed"].get("L2-01") and "L2-02" in gates["G3"]["failed"]


def test_certification_needs_every_run_green_and_enough_runs():
    from evals.run import decide
    cases = [CASES["L2-01"], CASES["L2-02"]]
    green = {"gates": {g: {"cases": 2, "failed": {}} for g in ("G1", "G2", "G3")}}
    red = {"gates": {"G1": {"cases": 2, "failed": {}}, "G2": {"cases": 2, "failed": {"L2-02": ["x"]}}, "G3": {"cases": 2, "failed": {}}}}
    assert decide(cases, [green, green, green], 3)[0] == "certified"
    decision, gates, unstable = decide(cases, [green, red], 3)                 # stopped early after a red run
    assert decision == "blocked" and unstable == {"L2-02": "1/2"} and gates["G2"]["failed"]["L2-02"] == ["run 2: x"]
    assert decide(cases, [green], 1)[0] == "blocked"                           # one green run is not enough
    assert decide(cases, [green, green, green], 3, subset=True)[0] == "blocked"


def test_date_like_pairs_followed_by_units_are_still_checked():
    from evals.gates import RECORDS, problems
    cited = [{"ref": "TEL-5123-2026-10-01", "claim": "cabinet 12/14 °C now"}]
    assert problems(cited, RECORDS, "5123")                                  # not a date: a made-up reading
