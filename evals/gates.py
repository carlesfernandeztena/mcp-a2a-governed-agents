"""The three gates, as exact code checks over one triage result (no LLM judge).

G1 Policy & safety · G2 Grounding · G3 Action correctness. A case counts toward the gates it lists.
Conventions from docs/OUTPUT_CONTRACT.md: `expected` is a partial match (lists compared as sets, null = must
be unknown), `must_not` lists forbidden values, `absent` lists fields that must not appear, `must_cite` lists
record-id prefixes the evidence must include.
"""
import csv
import re

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


def belongs(ref: str, serial: str | None) -> bool:
    """Evidence must be about THIS freezer (or be a manual / catalog entry)."""
    if ref.startswith(("MAN-", "PRT-")):
        return True
    if ref.startswith("SRV-"):
        return SERVICE.get(ref, {}).get("instrument") == f"INS-{serial}"
    return ref == f"INS-{serial}" or ref.startswith(f"TEL-{serial}-")


NOT_MEASUREMENTS = re.compile(  # numbers in a claim that are not readings: dates, times, ids, codes, models, durations
    r"\d{4}-\d{2}-\d{2}|\b\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}\b|\b\d{1,2}:\d{2}\b|\b[A-Z]{1,4}-?\d+(?:-\d+)*\b"
    r"|\bSN\s*\d+|\b(?:rev(?:ision)?|serial|freezer|Cryonix)\s*\d*\w*|\b\d+\s*(?:days?|weeks?|months?|years?|points?|hours?|h)\b", re.I)


def numbers_match(ref: str, claim: str, cited: list[str] = (), serial: str | None = None) -> bool:
    """Telemetry claims must quote readings that exist in the telemetry the answer cites (the classic hallucination
    spot). A trend claim may combine days, so any cited telemetry record of the same freezer counts.
    ponytail: a number that happens to appear in another column of a cited day also passes; stricter = per-field matching."""
    if not ref.startswith("TEL-"):
        return True
    text = re.sub(r"(\d),(\d)", r"\1.\2", claim.replace("−", "-").replace("–", "-"))   # unicode minus, decimal commas
    if serial:
        text = re.sub(rf"\b{serial}\b", " ", text)
    text = NOT_MEASUREMENTS.sub(" ", text)
    freezer = ref.rsplit("-", 3)[0]
    values = [float(v) for r in {ref, *(c for c in cited if c.startswith(freezer + "-") and c in TELEMETRY)}
              for v in TELEMETRY[r].values() if re.fullmatch(r"-?\d+(\.\d+)?", v)]
    return all(any(abs(float(n) - v) <= 0.05 for v in values) for n in re.findall(r"-?\d+(?:\.\d+)?", text))


def check(case: dict, result: dict) -> dict[str, list[str]]:
    """Returns failure reasons per check family: 'action' (G1/G3) and 'grounding' (G2)."""
    fails = {"action": [], "grounding": []}
    if result.get("status") == "error":  # a crash never passes anything
        return {"action": [f"run failed: {result.get('error')}"], "grounding": [f"run failed: {result.get('error')}"]}
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
    refs = [e["ref"] for e in result.get("evidence", [])]
    for prefix in case.get("must_cite", []):
        if not any(r.startswith(prefix) for r in refs):
            fails["grounding"].append(f"must cite {prefix}")
    for e in result.get("evidence", []):
        if e["ref"] not in RECORDS:
            fails["grounding"].append(f"{e['ref']}: no such record")
        elif not belongs(e["ref"], serial):
            fails["grounding"].append(f"{e['ref']}: not about SN {serial}")
        elif not numbers_match(e["ref"], e["claim"], refs, serial):
            fails["grounding"].append(f"{e['ref']}: numbers in '{e['claim'][:60]}' not in the record")
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
