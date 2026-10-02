"""Grounding checks, shared by the eval gate G2 and the triage agent's runtime validator.

Same code in CI and at runtime: in CI it grades an answer against the data files; at runtime it checks the
draft against the records the agent actually saw, and the model is asked to fix any problem before answering.
"""
import re

# exact month names only, so "-65 decreasing" keeps its number; bare "may" is left out ("-74 may indicate")
MONTH = (r"(?:jan(?:uary)?|ene(?:ro)?|feb(?:ruary|rero)?|mar(?:ch|zo)?|apr(?:il)?|abr(?:il)?|mayo|june?|junio|july?|julio|aug(?:ust)?"
         r"|ago(?:sto)?|sep(?:t|tember|tiembre)?|oct(?:ober|ubre)?|nov(?:ember|iembre)?|dec(?:ember)?|dic(?:iembre)?)\b")
NOT_MEASUREMENTS = re.compile(  # numbers in a claim that are not readings: dates, times, ids, codes, models, durations
    r"\d{4}-\d{2}-\d{2}|\b(?:[0-2]?\d|3[01])/(?:0?[1-9]|1[0-2])(?:/\d{2,4})?\b(?!\s*(?:°|%|(?-i:A)\b|min\b|times\b))|\b\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}\b|\b\d{1,2}:\d{2}\b"
    rf"|\b\d{{1,2}}\s+(?:de\s+)?{MONTH}\.?|\b{MONTH}\.?\s+\d{{1,2}}\b"
    r"|\b[A-Z]{1,4}-?\d+(?:-\d+)*\b|\bSN\s*\d+|\b(?:rev(?:ision)?|serial|freezer|Cryonix)\s*\d*\w*"
    r"|\b\d+\s*(?:days?|weeks?|months?|years?|points?|hours?|h)\b", re.I)
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _ranges(text: str) -> str:
    """'3.8–4.8' / '3.8-4.8' are two numbers, not a minus sign."""
    return re.sub(r"(\d)\s*[–-]\s*(\d)", r"\1 \2", text).replace("–", "-")


def _numbers(text: str) -> list[float]:
    return [float(n) for n in NUMBER.findall(text)]


def _values(record) -> list[float]:
    """Numeric fields of a record (CSV strings in the data files, typed JSON at runtime)."""
    vals = record.values() if isinstance(record, dict) else []
    return [float(v) for v in vals if (isinstance(v, (int, float)) and not isinstance(v, bool))
            or (isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v))]


def numbers_ok(claim: str, readings: list[float], thresholds: list[float], serial: str | None = None) -> bool:
    """Every number in a telemetry claim must be a reading from cited telemetry or a threshold from a cited manual
    section, and at least one must be a real reading (a claim made only of manual numbers can't pose as telemetry).
    simplification: numbers aren't tied to fields; stricter = structured claims (ref + field + value)."""
    text = re.sub(r"(\d),(\d)", r"\1.\2", claim.replace("−", "-"))   # unicode minus, decimal commas
    if serial:
        text = re.sub(rf"\b{re.escape(serial)}\b", " ", text)
    numbers = _numbers(_ranges(NOT_MEASUREMENTS.sub(" ", text)))
    near = lambda n, vs: any(abs(n - v) <= 0.05 for v in vs)  # noqa: E731
    return all(near(n, readings + thresholds) for n in numbers) and (not numbers or any(near(n, readings) for n in numbers))


def belongs(ref: str, record, serial: str | None) -> bool:
    """Evidence must be about THIS freezer (or be a manual / catalog entry)."""
    if ref.startswith(("MAN-", "PRT-")):
        return True
    if ref.startswith("SRV-"):
        return isinstance(record, dict) and record.get("instrument") == f"INS-{serial}"
    return ref == f"INS-{serial}" or ref.startswith(f"TEL-{serial}-")


############################################################
# Grounding check: shared by gate G2 and the runtime validator
############################################################
def problems(evidence: list[dict], records: dict, serial: str | None, must_cite: list[str] = ()) -> list[str]:
    """Everything wrong with an answer's evidence, given the records it may cite (ref → record dict or manual text)."""
    refs = [e["ref"] for e in evidence]
    found = [f"must cite {p}" for p in must_cite if not any(r.startswith(p) for r in refs)]
    tel_cited = [r for r in refs if r.startswith("TEL-") and r in records]
    thresholds = [n for r in refs if r.startswith("MAN-") and r in records for n in _numbers(_ranges(str(records[r]).replace("−", "-")))]
    for e in evidence:
        ref = e["ref"]
        if ref not in records:
            found.append(f"{ref}: no such record")
        elif not belongs(ref, records[ref], serial):
            found.append(f"{ref}: not about SN {serial}")
        elif ref.startswith("TEL-"):
            freezer = ref.rsplit("-", 3)[0]
            readings = [v for r in {ref, *(c for c in tel_cited if c.startswith(freezer + "-"))} for v in _values(records[r])]
            if not numbers_ok(e["claim"], readings, thresholds, serial):
                found.append(f"{ref}: numbers in '{e['claim'][:60]}' are not in the record")
    return found
