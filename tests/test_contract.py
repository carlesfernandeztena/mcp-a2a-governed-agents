"""The contract models accept the documented example and enforce the conventions."""
import json
import re
from pathlib import Path

from pydantic import ValidationError

from harness.contract import TriageDraft, TriageResult

doc = (Path(__file__).parent.parent / "docs" / "OUTPUT_CONTRACT.md").read_text()
example = json.loads(re.search(r"```json\n(\{\n  \"status\".*?\n\})\n```", doc, re.S).group(1))


def test_documented_example_round_trips():
    assert TriageResult.model_validate(example).dump() == example


def test_llm_cannot_deny():
    draft = {"diagnosis": {"cause": "unknown", "confidence": "low", "summary": "x"}, "evidence": []}
    TriageDraft.model_validate({"status": "escalate", **draft})
    try:
        TriageDraft.model_validate({"status": "denied", **draft})
        raise AssertionError("the LLM must not be able to return 'denied'")
    except ValidationError:
        pass


def test_null_means_unknown_absent_means_not_applicable():
    unknown = TriageResult(status="escalate", samples_at_risk=None).dump()
    assert "samples_at_risk" in unknown and unknown["samples_at_risk"] is None
    assert "visit" not in unknown and "denial" not in unknown

