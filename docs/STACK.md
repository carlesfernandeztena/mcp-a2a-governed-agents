# Stack

Chosen after the data was finished (D14), so the data never depended on it.

| Layer | Choice | Why |
|---|---|---|
| Language / env | Python 3.12, **uv** | Official MCP and A2A SDKs and the gateway are Python-first |
| Run everything | **docker compose** (one shared image for our services + the official LiteLLM image) | Standard, reproducible anywhere; `docker compose stop scheduling-agent` breaks a seam live |
| Model gateway | **LiteLLM Proxy** | Neutral OpenAI-style API; the agent asks for the alias `triage-llm`, one line in `gateway/litellm.yaml` picks the provider (the live swap) |
| Providers | **OpenAI** (default): `gpt-6-luna` for development, `gpt-6-sol` if Luna fails the gates. **Anthropic** `claude-sonnet-5-5` for the live swap and minimal tests | Tight budget; the eval gates decide which model is good enough |
| Agent loop | **Pydantic AI** | Model-agnostic, native MCP client, output validated against the contract as a Pydantic model |
| Skills | **MCP Python SDK**, streamable HTTP, one process each | Real seam; badge in the `Authorization` header |
| Data products | **FastAPI**, one process, one route per product, reading `data/` | Entitlement check at the data product door |
| A2A | **a2a-sdk** | Canonical; Agent Card declares bearer auth |
| Badges | **PyJWT**, RS256, locally generated keys (stub issuer) | Real signed tokens; `act` claim = agent acting for user |
| Rules | Plain Python + **`rules.yaml`** for every number and table | One place to read and change rules |
| Audit / lineage | Append-only **JSONL**, shared trace id across hops | Required by the brief; source of all views |
| Views | Terminal viewer with **rich**: trace, audit card, gate scorecard | We decide what is shown; the JSONL stays the full record |
| Eval harness | Plain Python runner over `evals/cases.jsonl` | Gates are exact code checks; an LLM judge is easy to add if ever needed |
| Human steps | CLI: `ask --as yusuf "…"`, `approve P-001 --as grant` | Minimal web UI parked: can be added later as another reader of the same JSONL |

**Harness = a small shared library every component imports** (agent runner, skills, data products): badge handling, tier checks, rules, audit writing. Pods import it instead of writing their own plumbing.

**Deterministic failing gate (G2):** candidate v0.4 ships `propose_parts_order` with a boundary bug (`serial <= 5500` instead of `< 5000`) → 5123 treated as rev A → correct GK-80-B rejected → G3 fails with any model.
