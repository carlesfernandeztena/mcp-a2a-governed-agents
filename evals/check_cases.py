"""Consistency check: every eval case points at things that really exist in the data.

Run after any change to data/ or cases.jsonl:  python evals/check_cases.py
"""
import csv, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"
rows = lambda f: list(csv.DictReader(open(D / f)))

people = {p["id"] for p in json.load(open(D / "people.json"))}
serials = {r["serial"] for r in rows("instruments.csv")}
parts = {r["part_number"] for r in rows("parts_catalog.csv")}
slots = {(r["engineer"], r["start"]) for r in rows("calendar.csv")}
record_ids = ({r["id"] for f in ("instruments.csv", "service_records.csv", "parts_catalog.csv", "telemetry.csv") for r in rows(f)}
              | set(re.findall(r"^## (MAN-[\w-]+)", open(D / "manual_cryonix80.md").read(), re.M)))
rules = set(re.findall(r"\*\*(R-[A-Z]{3}-\d)\*\*", open(ROOT / "docs" / "DEMO_SCENARIOS.md").read()))
agents = {"triage-agent", "quick-lookup"}

cases = [json.loads(l) for l in open(ROOT / "evals" / "cases.jsonl")]
errors = []
def check(ok, msg):
    if not ok: errors.append(msg)

check(len(cases) == 30, f"expected 30 cases (14 core + 16 variations), found {len(cases)}: deleting cases must not make certification easier")
check(len({c["id"] for c in cases}) == len(cases), "duplicate case ids")
for c in cases:
    check(bool(c["gates"]), f"{c['id']}: counts toward no gate")
    cid = c["id"]
    check(c["user"] in people, f"{cid}: unknown user {c['user']}")
    check(c["agent"] in agents, f"{cid}: unknown agent {c['agent']}")
    for s in re.findall(r"SN (\d+)", c["input"]):
        check(s in serials or c.get("unknown_instrument"), f"{cid}: unknown serial {s}")
    if "variant_of" in c:
        check(c["variant_of"] in {x["id"] for x in cases}, f"{cid}: variant of unknown case")
    for r in c["rules"]:
        check(r in rules, f"{cid}: unknown rule {r}")
    check(set(c["gates"]) <= {"G1", "G2", "G3"}, f"{cid}: unknown gate")
    exp, bad = c["expected"], c["must_not"]
    check(not set(c.get("absent", [])) & set(exp), f"{cid}: field both expected and absent")
    for p in exp.get("parts[].part_number", []) + bad.get("parts[].part_number", []):
        check(p in parts, f"{cid}: unknown part {p}")
    check(not set(exp.get("parts[].part_number", [])) & set(bad.get("parts[].part_number", [])), f"{cid}: part both expected and forbidden")
    if exp.get("visit.engineer"):
        check((exp["visit.engineer"], exp["visit.start"]) in slots, f"{cid}: expected visit is not a free slot")
    for ref in c["must_cite"] + bad.get("evidence[].ref", []):
        check(any(i.startswith(ref) for i in record_ids), f"{cid}: no record matches {ref}")

covered = {r for c in cases for r in c["rules"]}
core = [c for c in cases if "variant_of" not in c]
print(f"{len(cases)} cases checked ({len(core)} core, {len(cases) - len(core)} variations), {len(errors)} errors")
print("Core cases without a variation:", ", ".join(sorted({c['id'] for c in core if not c['id'].startswith('V')} - {c.get('variant_of') for c in cases})) or "none")
print("Rules not exercised by an eval case (tested elsewhere):", ", ".join(sorted(rules - covered)))
for e in errors: print("ERROR", e)
assert not errors
