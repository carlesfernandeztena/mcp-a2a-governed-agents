"""Output contracts (docs/OUTPUT_CONTRACT.md) as Pydantic models.

Convention: `null` means unknown; a field that does not apply is left out.
Optional fields default to None but are NOT typed `| None`: Pydantic doesn't validate defaults, so a field
can be absent, yet setting it to None explicitly is rejected. Only `samples_at_risk` may be null (unknown).
Results are dumped with `exclude_unset`.
"""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def serial_of(value) -> str:
    """Engineers write 'SN 5123'; records say '5123'. Strip the label only — never 'correct' the number."""
    return re.sub(r"^\s*(?:SN|S/N|serial(?: number)?)\s*[:#]?\s*", "", str(value), flags=re.I).strip()

Cause = Literal["door_gasket_worn", "compressor_failing", "condenser_filter_clogged", "door_ajar", "unknown"]
Flag = Literal["chargeable_needs_po", "sla_breach", "scheduling_unavailable", "telemetry_missing",
               "instrument_not_found", "suspicious_text_in_data"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def dump(self) -> dict:
        return self.model_dump(mode="json", exclude_unset=True)


class Diagnosis(_Model):
    cause: Cause
    confidence: Literal["high", "medium", "low"]
    summary: str


class Evidence(_Model):
    # exactly one record id per item; a malformed ref is a validation error, so the model is asked to fix it
    ref: str = Field(pattern=r"^(INS|SRV|TEL|MAN|PRT)-[A-Z0-9-]+$", description="one record id, e.g. TEL-5123-2026-10-01")
    claim: str


class TriageDraft(_Model):
    """The only thing the LLM produces: judgement fields. It cannot deny, price, schedule or approve."""
    status: Literal["proposal", "no_action", "escalate"]
    diagnosis: Diagnosis
    evidence: list[Evidence]
    advice: list[str] = []


class Part(_Model):
    part_number: str
    name: str
    qty: int
    chargeable: bool


class Visit(_Model):
    engineer: str = None       # absent when there is no free slot at all
    start: str = None
    end: str = None
    sla_deadline: str = None   # absent when there is no contract
    within_sla: bool = None


class Approval(_Model):
    required: bool
    approver_role: str
    state: Literal["pending", "approved", "rejected"]


class Denial(_Model):
    reason: Literal["territory", "tier", "regulated"]
    enforced_at: str


class TriageResult(_Model):
    """What triage-agent returns: the LLM's draft plus every field filled by code."""
    status: Literal["proposal", "no_action", "escalate", "denied"]
    diagnosis: Diagnosis = None
    evidence: list[Evidence] = None
    parts: list[Part] = None
    urgency: Literal["routine", "urgent"] = None
    samples_at_risk: bool | None = None   # the one nullable field: null = unknown
    advice: list[str] = None
    visit: Visit = None
    flags: list[Flag] = None
    approval: Approval = None
    denial: Denial = None


