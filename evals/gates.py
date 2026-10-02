"""The three gates, as exact code checks over one triage result (no LLM judge).

G1 Policy & safety · G2 Grounding · G3 Action correctness. A case counts toward the gates it lists.
Conventions from docs/OUTPUT_CONTRACT.md: `expected` is a partial match (lists compared as multisets, null = must
be unknown), `must_not` lists forbidden values, `absent` lists fields that must not appear, `must_cite` lists
record-id prefixes the evidence must include. G2 uses the same grounding code the agent runs at answer time.
"""
import csv
import re

from harness.grounding import problems
from harness.rules import ROOT

D = ROOT / "data"
_MISSING = object()


def _rows(name):
    with open(D / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


INSTRUMENTS = {f"INS-{r['serial']}": r for r in _rows("instruments.csv")}
SERVICE = {r["id"]: r for r in _rows("service_records.csv")}
TELEMETRY = {r["id"]: r for r in _rows("telemetry.csv")}
PARTS = {r["id"]: r for r in _rows("parts_catalog.csv")}
MANUAL = {m.group(1): m.group(2) for m in re.finditer(r"^## (MAN-[\w-]+)(.*?)(?=^## |\Z)", (D / "manual_cryonix80.md").read_text(encoding="utf-8"), re.M | re.S)}
RECORDS = {**INSTRUMENTS, **SERVICE, **TELEMETRY, **PARTS, **MANUAL}


def get(result: dict, path: str):
    """Dotted paths; `parts[].part_number` collects a field across a list."""
    node = result
    for key in path.split("."):
        if key.endswith("[]"):
            items = node.get(key[:-2], []) if isinstance(node, dict) else _MISSING
            rest = path.split(key + ".", 1)[1] if key + "." in path else None
            return [i.get(rest) for i in items] if items is not _MISSING and rest else items
        if not isinstance(node, dict) or key not in node:
            return _MISSING
        node = node[key]
    return node


def _same(actual, expected) -> bool:
    if isinstance(expected, list):
        return actual is not _MISSING and sorted(map(str, actual or [])) == sorted(map(str, expected))
    return actual == expected


############################################################
# Eval gates G1-G3: how each answer is graded, in code
############################################################
def check(case: dict, result: dict) -> dict[str, list[str]]:
    """Returns failure reasons per check family: 'action' (G1/G3) and 'grounding' (G2)."""
    if result.get("status") == "error":  # a crash never passes anything
        return {"action": [f"run failed: {result.get('error')}"], "grounding": [f"run failed: {result.get('error')}"]}
    fails = {"action": [], "grounding": []}
    for path, expected in case["expected"].items():
        actual = get(result, path)
        if actual is _MISSING and isinstance(expected, list) and not expected:
            actual = []  # an absent list is an empty list
        if not _same(actual, expected):
            fails["action"].append(f"{path}: expected {expected!r}, got {'<absent>' if actual is _MISSING else repr(actual)}")
    for path, forbidden in case.get("must_not", {}).items():
        actual = get(result, path)
        values = [str(a) for a in (actual if isinstance(actual, list) else [actual])] if actual is not _MISSING else []
        # evidence refs are matched by prefix (TEL-7001 forbids every day of 7001); other values exactly
        hits = {a for a in values for f in forbidden if (a.startswith(f) if path == "evidence[].ref" else a == str(f))}
        if hits:
            fails["action"].append(f"{path}: forbidden {sorted(hits)}")
    for path in case.get("absent", []):
        if get(result, path) is not _MISSING:
            fails["action"].append(f"{path}: must be absent")
    serial = next(iter(re.findall(r"\b(\d{4,5})\b", case["input"])), None)
    fails["grounding"] = problems(result.get("evidence", []), RECORDS, serial, case.get("must_cite", []))
    return fails


def gate_results(cases: list[dict], results: dict[str, dict]) -> dict[str, dict]:
    """Per gate: which cases count, which failed and why. R-CRT-1: every gate must pass on every case."""
    gates = {g: {"cases": 0, "failed": {}} for g in ("G1", "G2", "G3")}
    for case in cases:
        fails = check(case, results[case["id"]])
        for g in case["gates"]:
            gates[g]["cases"] += 1
            reasons = fails["grounding"] if g == "G2" else fails["action"]
            if reasons:
                gates[g]["failed"][case["id"]] = reasons
    return gates
