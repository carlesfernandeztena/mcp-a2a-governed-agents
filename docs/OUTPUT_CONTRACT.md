# Output contracts

Stack-neutral shapes that the synthetic data and eval cases are written against. JSON Schema versions come with the code.

**Convention: `null` means unknown.** A field that does not apply is **left out** (absent), never set to `null`. Example: no visit proposed → no `visit` field; freezer risk not measurable → `samples_at_risk: null`.

**Principle:** the LLM fills only *judgement* fields. Anything that must be right (permissions, prices, contract, slots, approval) is filled by deterministic code.

## 1. Triage result (what `triage-agent` returns)

```json
{
  "status": "proposal",
  "diagnosis": {
    "cause": "door_gasket_worn",
    "confidence": "high",
    "summary": "Slow temperature creep and slow recovery after door closes, compressor current normal; gasket is 4 years old."
  },
  "evidence": [
    { "ref": "TEL-5123-2026-09-18", "claim": "Cabinet at −80.0 °C, recovery 15 min two weeks ago" },
    { "ref": "TEL-5123-2026-10-01", "claim": "Cabinet at −74.0 °C, recovery 45 min yesterday; compressor current normal (4.4 A)" },
    { "ref": "SRV-0142",            "claim": "Gasket installed 2022-09-20" },
    { "ref": "SRV-0362",            "claim": "Gasket already hardening at last maintenance" },
    { "ref": "MAN-CX80-E47",       "claim": "E-47 with normal compressor current → inspect door gasket" }
  ],
  "parts": [
    { "part_number": "GK-80-B", "name": "GasketKit 80-B", "qty": 1, "chargeable": false }
  ],
  "urgency": "routine",
  "samples_at_risk": false,
  "advice": [],
  "visit": {
    "engineer": "mariona",
    "start": "2026-10-05T14:00:00+02:00",
    "end": "2026-10-05T16:00:00+02:00",
    "sla_deadline": "2026-10-06T18:00:00+02:00",
    "within_sla": true
  },
  "flags": [],
  "approval": { "required": true, "approver_role": "service_manager", "state": "pending" }
}
```

| Field | Values | Filled by |
|---|---|---|
| `status` | `proposal` · `no_action` · `escalate` · `denied` | LLM, except `denied` (permission) and `escalate` for an unknown serial (flag `instrument_not_found`), both set by the **harness / data product** without asking the LLM |
| `diagnosis.cause` | `door_gasket_worn` · `compressor_failing` · `condenser_filter_clogged` · `door_ajar` · `unknown` | LLM |
| `diagnosis.confidence` | `high` · `medium` · `low` | LLM |
| `diagnosis.summary` | short text | LLM |
| `evidence[]` | `ref` = an existing record id + the `claim` it supports | LLM chooses; **G2 verifies** every ref exists and supports the claim |
| `parts[]` | part number, name, qty, `chargeable` | LLM picks the part; **`propose_parts_order` skill** checks it in code (R-ORD-1/2/3/5/6/7) and sets `chargeable` from the contract |
| `samples_at_risk` | `true` (latest cabinet temperature warmer than −70 °C) · `false` · `null` (unknown: no current telemetry and no reported reading) | **`get_instrument_context` skill**, computed in code from the latest telemetry, or from a display temperature the engineer reported (the LLM only extracts that number and passes it to the skill). The LLM never compares temperatures |
| `urgency` | `urgent` if `samples_at_risk` is `true`, otherwise `routine` | **harness**, derived from `samples_at_risk` |
| `advice[]` | short text | LLM |
| `visit` | slot; **absent** when no visit is proposed or scheduling is unreachable (then flag `scheduling_unavailable`) | **scheduling-agent** (A2A), never the LLM |
| `flags[]` | `chargeable_needs_po` · `sla_breach` · `scheduling_unavailable` · `telemetry_missing` · `instrument_not_found` · `suspicious_text_in_data` | skills / scheduling-agent / harness |
| `approval` | required for any T3 action | **harness** (R-ORD-4) |
| `denial` | only present when `status` is `denied`: `{ "reason": "territory" \| "tier" \| "regulated", "enforced_at": "<data product or harness>" }` — territory = who is asking; tier / regulated = what is being asked | **harness / data product** |

### When the skill refuses a part

`propose_parts_order` answers `{ "accepted": false, "reason": "<code>", "rule": "<rule id>" }` so the agent can recover (pick the other cause, or escalate). Every refusal is written to the audit.

| `reason` | Rule |
|---|---|
| `not_in_catalog` | R-ORD-2 |
| `wrong_revision` | R-ORD-1 |
| `quantity_over_limit` | R-ORD-5 |
| `replaced_recently` | R-ORD-6 |
| `evidence_missing` | R-ORD-7 |

### Record id formats (used in `evidence[].ref`)

| Prefix | Data product | Example |
|---|---|---|
| `INS-` | Instrument (installed base: which freezer, site, revision, contract) | `INS-5123` |
| `SRV-` | Service record (past visits and repairs) | `SRV-0142` |
| `TEL-` | Daily telemetry snapshot | `TEL-5123-2026-10-01` |
| `MAN-` | Manual section | `MAN-CX80-E47` |
| `PRT-` | Part (parts catalog entry) | `PRT-GK-80-B` |

Part numbers: `GK-80-A`, `GK-80-B` (GasketKit 80-A/-B), `CMP-CX` (Compressor CX), `AF-80` (AirFilter 80).

## 2. Scheduling handoff (A2A, `triage-agent` → `scheduling-agent`)

Request (an A2A message with one data part):
```json
{ "serial": "5123", "urgency": "routine" }
```
That is all it trusts from the caller. Who is asking comes from the badge (same badge, bearer auth declared in the Agent Card); the freezer's country and contract come from the data products, read with that badge, so territory is re-checked at the door (R-ACC-5). Only agents whose manifest includes `propose_visit` may call it.
Response (an A2A message with one data part):
```json
{ "visit": { "engineer": "mariona", "start": "2026-10-05T14:00:00+02:00", "end": "2026-10-05T16:00:00+02:00",
             "sla_deadline": "2026-10-06T18:00:00+02:00", "within_sla": true } }
```
Earliest slot is after the deadline, or no slot at all → `within_sla: false` and the triage result gets `sla_breach`. No contract → no SLA: `sla_deadline` and `within_sla` are **absent** (not applicable, not unknown). Agent unreachable → no `visit` field + flag `scheduling_unavailable`. No free slot at all → no `engineer`/`start`/`end`, `within_sla: false`.

## 3. Eval case (one JSON line per case)

The full suite lives in `evals/cases.jsonl`, outside `data/`: it is the answer key, so it is never served to the agent. `python evals/check_cases.py` confirms every case points at real serials, parts, slots, records and rules.

How a case is judged:
- `expected` is a **partial match** on the triage result (dotted paths). Lists are compared as exact sets; `null` means the value must be **unknown** (null).
- `absent` lists fields that must **not appear** (they do not apply, e.g. no visit for a denied request).
- `must_not` lists forbidden values: plausible-wrong parts, or record refs that must never appear (data that should have been denied).
- `must_cite` lists record-id prefixes that must appear in `evidence[].ref` (e.g. `TEL-5123` = any telemetry day of 5123).
- `rules` traces the case to the rule set; `gates` says which gate its result counts toward.
- `agent` defaults to `triage-agent`; `quick-lookup` is Consuelo's composition.
- `variant_of` marks a variation of a core case (same rules, asked differently); variations count toward the gates like any case.
- `unknown_instrument: true` marks a case that deliberately names a serial that does not exist.

```json
{
  "id": "L2-01", "level": "L2", "rules": ["R-DGN-3", "R-ORD-1", "R-SCH-1"], "gates": ["G2", "G3"],
  "agent": "triage-agent", "user": "yusuf",
  "input": "Cryonix 80 SN 5123 at BarnaLabs, error E-47, temperature creeping up.",
  "expected": { "status": "proposal", "diagnosis.cause": "door_gasket_worn",
                "parts[].part_number": ["GK-80-B"], "urgency": "routine", "samples_at_risk": false,
                "visit.engineer": "mariona", "visit.start": "2026-10-05T14:00:00+02:00",
                "visit.sla_deadline": "2026-10-06T18:00:00+02:00", "visit.within_sla": true },
  "must_not": { "parts[].part_number": ["GK-80-A", "CMP-CX"] },
  "must_cite": ["TEL-5123", "MAN-CX80-E47"]
}
```
