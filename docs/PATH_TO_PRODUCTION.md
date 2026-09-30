# Path to production

What the demo fakes, simplifies or leaves out, and what a real product would need instead.
Feeds the "where I am least sure" and "year one" discussion.

Four groups:
1. **Faked on purpose** (the two declared stubs, marked `# STUB:` in the code)
2. **Made simpler** (works for real, but a smaller version; marked `ponytail:` in the code)
3. **Made up** (synthetic data and services, as the brief allows)
4. **Not built at all**

## 1. Faked on purpose (stubs)

| In the demo | In a real product | Why the demo version is enough |
|---|---|---|
| A small script hands out the login badges (signed JWT tokens) from a list of people | The company login system (Entra ID or Okta), with single sign-on, MFA, and a standard way for an agent to act "on behalf of" a person (OAuth token exchange) | The badges are real and checked at every step. Only *who hands them out* is fake. Switching = pointing to the real login system |
| When Grant approves an order, we write it to the audit log and stop | The order is sent to the business system (ERP, e.g. SAP), which reserves the part and books the cost, safely handling retries and failures | The demo is about *propose → approve → record*. Sending the order happens after all of that |

## 2. Made simpler

| In the demo | In a real product | Why the demo version is enough |
|---|---|---|
| Rules written as plain code, with their numbers in one file | A policy engine (OPA or Cedar): rules are versioned, reviewed, tested, and go through the same gates as agents | About 25 rules; an engine adds setup, not insight |
| Plain files | Real data products: owned, documented, access-controlled datasets in the company's data platform | Nothing to scale |
| Each freezer row says its site, country and territory directly | Customer account → its sites → its freezers. The customer account becomes the key that keeps customers apart in the Customer Assistant (use case A) | Every customer in the demo has one site |
| The manual is one clean text file, already split into sections with ids, searched by keywords | Real manuals are PDFs (tables, diagrams, scans, several languages and versions). A pipeline per file type extracts the text (OCR for scans), cuts it into chunks (ideally along sections), keeps a stable id per chunk for citations, and indexes it twice: as embeddings in a vector store (search by meaning) and as raw text (search by keywords). Both results are combined and re-ranked (hybrid RAG). New manual versions are re-ingested, and the audit records *which version* the agent read | Our sections are already perfect chunks with ids. The skill's promise ("give me the relevant sections, with ids") stays the same, so the real pipeline can replace it behind the same seam |
| Grant approves by typing a command | Approve in Teams / Slack / ServiceNow, with reminders and escalation | The brief gives no points for interface polish |
| Consuelo's agent is a small file listing the skills she picked | A self-service screen to build agents from certified pieces | Same reason |
| The list of skills and agents (with tier and status) is a file | A registry service that tracks versions, owners, tiers and certification | One team, a few entries |
| The audit log is a local file | Tamper-proof storage, kept for a defined period, with access control | Shows *what* is recorded; *where* is an infrastructure choice |
| All gates are exact code checks | Add checks by an AI judge and by humans (sampled) for open-ended answers; red-team testing | The critical checks must be exact anyway |
| We run the evals by hand | Gates run automatically on every change, and results update the registry | Same checks, different trigger |

## 3. Made up (synthetic data and services)

| In the demo | In a real product | Why the demo version is enough |
|---|---|---|
| Freezer with one compressor and one condenser | Real −80 °C freezers have two compressor stages ("cascade"); diagnosis would need signs for each stage | Doesn't change anything the demo shows |
| Daily telemetry summaries, generated | Live sensor data streamed from the freezers, summarised in the data platform | The agent only needs the daily summary |
| Every visit is a 2-hour slot, whatever the job; travel time, engineer skills and part delivery are ignored | Slot length from the job (a compressor swap takes a day), travel between sites, engineer certifications, and waiting for the part to arrive | Enough to show deadlines, breaches and the country filter |
| Engineer calendar with hardcoded free slots | The field-service planning system (e.g. ServiceMax, Salesforce Field Service) behind the scheduling agent | The scheduling agent is a black box to the caller either way |
| Manual, parts catalog, people and contracts as files | Each lives in its own system, owned by its team | Same shape of data |

## 4. Not built at all

- **Running it for real:** containers, separate sandbox / staging / certified environments, secrets management.
- **Model gateway limits:** authentication with per-team virtual keys (the demo gateway is open on localhost), budgets and rate limits per team, pinned model versions, fallback between providers, keeping data in the EU.
- **Operations:** service levels, alerts, on-call, cost dashboards, watching eval scores drift over time.
- **Security:** network isolation between agents and data, monitoring for prompt injection, penetration testing.
- **Compliance:** GDPR records, data retention, and the separate track for regulated instruments (T4) with validated systems and quality sign-off.
