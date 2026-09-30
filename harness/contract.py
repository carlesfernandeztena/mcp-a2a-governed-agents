"""Output contracts (docs/OUTPUT_CONTRACT.md) as Pydantic models.

Convention: `null` means unknown; a field that does not apply is left out.
So results are built by setting only the fields that apply, and dumped with `exclude_unset`.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict

Cause = Literal["door_gasket_worn", "compressor_failing", "condenser_filter_clogged", "door_ajar", "unknown"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def dump(self) -> dict:
        return self.model_dump(mode="json", exclude_unset=True)


class Diagnosis(_Model):
    cause: Cause
    confidence: Literal["high", "medium", "low"]
    summary: str


class Evidence(_Model):
    ref: str      # a record id: INS-, SRV-, TEL-, MAN-, PRT-
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
    engineer: str | None = None       # absent when there is no free slot at all
    start: str | None = None
    end: str | None = None
    sla_deadline: str | None = None   # absent when there is no contract
    within_sla: bool | None = None


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
    diagnosis: Diagnosis | None = None
    evidence: list[Evidence] | None = None
    parts: list[Part] | None = None
    urgency: Literal["routine", "urgent"] | None = None
    samples_at_risk: bool | None = None   # null = unknown
    advice: list[str] | None = None
    visit: Visit | None = None
    flags: list[str] | None = None
    approval: Approval | None = None
    denial: Denial | None = None


class ScheduleRequest(_Model):
    """A2A handoff triage-agent → scheduling-agent. Who asks travels in the badge, not here."""
    serial: str
    site: str
    country: str
    contract_tier: Literal["gold", "silver", "none"]
    urgency: Literal["routine", "urgent"]
