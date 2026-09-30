# Synthetic data

Everything here is fictional and derived from the rules in `../docs/DEMO_SCENARIOS.md`. No real company, customer or patient data.

- **Frozen "today" = Fri 2 Oct 2026** (R-SCH-0). All history ends on or before 1 Oct.
- **Data files hold only what a real system would hold.** Why each record exists (its rule and eval case) lives in `WHY.md`, a human-only file the agent never reads: it can't leak what isn't there.
- **Eval cases live in `../evals/`**, not here: they are the answer key and are never served to the agent.
- **Empty cell = none / not applicable** (no error code, no part replaced, no alarm). Unknown values never appear as empty cells; missing telemetry days are simply missing rows.
- **One freezer per eval case**: each freezer has exactly one story, so the world never contradicts itself.

| File | Data product | Record prefix | Rows |
|---|---|---|---|
| `WHY.md` | Human-only notes: why each record exists (never served to the agent) | — | — |
| `people.json` | People directory (identity stub input) | — | 6 |
| `instruments.csv` | Installed base: freezer, site, revision, contract | `INS-` | 11 |
| `service_records.csv` | Service history: installs, maintenance, repairs, customer reports | `SRV-` | 22 |
| `telemetry.csv` | Daily sensor summary, 18 Sep – 1 Oct | `TEL-` | 144 |
| `parts_catalog.csv` | Parts catalog: part, which revisions it fits, price | `PRT-` | 4 |
| `calendar.csv` | Engineer free slots, Mon 5 – Fri 23 Oct (2-hour slots, local time) | — | 19 |
| `manual_cryonix80.md` | Technical documentation: 7 sections, cited by section id | `MAN-` | 7 |
| `generate_telemetry.py` | Deterministic generator for `telemetry.csv` (stories + alarm thresholds) | — | — |

## Telemetry stories

| Freezer | Story | Signature (first → last day) |
|---|---|---|
| 5123, 3210 | Worn gasket (rev B / rev A twins) | −80 → −74 °C, recovery 15 → 45 min, current normal 4.2 → 4.4 A |
| 3355, 5477 | Worn gasket | −80 → −75 °C, same signature |
| 5710 | Worn gasket, gone further | −78 → −69 °C → samples at risk |
| 5600, 7001 | Mild gasket drift (never readable by Yusuf's agent) | −80 → −76 °C |
| 5301 | Failing compressor | −76.5 → −68 °C, duty 95 → 100 %, current 5.0 → 6.8 A |
| 5188 | Clogged condenser filter | condenser 38 → 52 °C, cabinet ≈ −79 °C |
| 5230 | Healthy; door open 40 min on 1 Oct | E-31 on the last day only |
| 5402 | Slight drift, then **no data from 22 Sep** (gateway swap) | 4 rows only |

**Alarm thresholds** (same values will appear in the manual): E-47 daily mean > −77 °C · E-21 condenser > 48 °C · E-31 one door opening > 10 min.
