"""triage-agent: Pydantic AI → model gateway → MCP skills, wrapped by the harness.

The LLM returns only a TriageDraft (judgement). Everything else in the TriageResult comes from code:
- an uncertified composition doesn't run at all (computed tier > certified tier, R-RSK-1);
- denials and unknown serials stop the run before the LLM can improvise;
- the run is pinned to the first freezer it looks up (no switching serials to dodge a check);
- parts come from the proposals the skill ACCEPTED, deduplicated (not from what the LLM wrote);
- sample risk comes from the context skill; urgency, status and approval are derived.
See docs/OUTPUT_CONTRACT.md.
"""
import json
import os
from pathlib import Path

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_data_parts, new_data_message
from a2a.types.a2a_pb2 import Role, SendMessageRequest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from pydantic import ValidationError
from pydantic_ai import Agent, ModelRetry, RunContext, capture_run_messages
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.litellm import LiteLLMProvider
from pydantic_ai.usage import UsageLimits

from harness import audit, badges
from harness.contract import Approval, Denial, Diagnosis, Part, TriageDraft, TriageResult, Visit
from harness.policy import computed_tier
from harness.contract import serial_of
from harness.grounding import problems
from harness.rules import rules

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4400")
SKILL_URLS = {
    "get_instrument_context": os.environ.get("SKILL_CONTEXT_URL", "http://localhost:8101/mcp"),
    "search_manuals": os.environ.get("SKILL_MANUALS_URL", "http://localhost:8102/mcp"),
    "propose_parts_order": os.environ.get("SKILL_PARTS_URL", "http://localhost:8103/mcp"),
}
SCHEDULING_URL = os.environ.get("SCHEDULING_URL", "http://localhost:8201/")
PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8").replace("{today}", rules()["today"])
LIMITS = UsageLimits(request_limit=16)  # cost cap per question, with room for self-corrections
MAX_FIXES = rules()["certification"]["max_self_corrections"]


class Stop(Exception):
    """A skill answered with something only code may handle (denial, unknown serial): end the run now."""
    def __init__(self, answer: dict):
        super().__init__(json.dumps(answer))
        self.answer = answer


def gateway_model(alias: str = "triage-llm") -> Model:
    """Agents only ever know the gateway alias; which provider serves it is the gateway's business."""
    return OpenAIChatModel(alias, provider=LiteLLMProvider(api_base=GATEWAY_URL))


async def schedule(headers: dict, serial: str, urgency: str) -> dict:
    """A2A handoff to Field Ops' scheduling-agent, carrying the same badge. Returns its answer, or an error."""
    try:
        async with httpx.AsyncClient(headers=headers, timeout=10) as http:
            card = await A2ACardResolver(http, SCHEDULING_URL).get_agent_card()
            card.supported_interfaces[0].url = SCHEDULING_URL  # we reach it at the address we were given (host or container network)
            client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
            request = SendMessageRequest(message=new_data_message({"serial": serial, "urgency": urgency}, role=Role.ROLE_USER))
            async for event in client.send_message(request):
                if event.HasField("message"):
                    return get_data_parts(event.message.parts)[0]
    except Exception as e:  # unreachable, refused, malformed: the proposal still stands, flagged
        return {"error": type(e).__name__}
    return {"error": "no answer"}


def add_visit(result: TriageResult, answer: dict) -> TriageResult:
    """R-SCH-3: an unmet SLA is flagged; an unreachable scheduler leaves no visit and flags it."""
    flags = list(result.flags or [])
    fields = result.dump() | {"flags": flags}
    try:  # another team's agent: never trust the shape of its answer
        fields["visit"] = Visit(**answer["visit"])
        if answer["visit"].get("within_sla") is False:
            flags.append("sla_breach")
    except (KeyError, TypeError, ValidationError):
        fields.pop("visit", None)
        flags.append("scheduling_unavailable")
    return TriageResult.model_validate(fields)


async def gateway_route(alias: str) -> str | None:
    """The provider model the gateway routes the alias to (its config at answer time)."""
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            info = (await http.get(f"{GATEWAY_URL}/model/info")).json()["data"]
        return next(m["litellm_params"]["model"] for m in info if m["model_name"] == alias)
    except Exception:  # scripted test models have no gateway behind them
        return None


def _as_dict(result) -> dict:
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {}
    return {}


def _context(calls: list[tuple[str, dict, dict]]) -> dict | None:
    return next((r for name, _, r in calls if name == "get_instrument_context" and "instrument" in r), None)


def runtime_problems(draft: TriageDraft, calls: list[tuple[str, dict, dict]], serial: str | None) -> list[str]:
    """Grounding problems in a draft, judged only against records the skills returned in this run. Required
    citations follow from facts code already knows: fresh telemetry must be cited; samples at risk must cite the
    manual's samples-at-risk section; a diagnosis must cite the manual section it comes from."""
    records, required = {}, []
    if section := rules()["diagnosis"]["cause_sections"].get(draft.diagnosis.cause):
        required.append(section)
    for name, args, r in calls:
        if name == "get_instrument_context" and "instrument" in r:
            records[r["instrument"]["id"]] = r["instrument"]
            records |= {x["id"]: x for x in r["service_records"] + r["telemetry"]}
            if r.get("latest_telemetry"):
                required.append(f"TEL-{serial}")
            if r.get("samples_at_risk") is True:
                required.append("MAN-CX80-SAMPLES")
        elif name == "search_manuals":
            records |= {s["id"]: f"{s['title']} {s['text']}" for s in r.get("sections", [])}
        elif name == "propose_parts_order":
            if r.get("accepted"):
                records[f"PRT-{r['proposal']['part_number']}"] = r["proposal"]
            elif r.get("reason") not in (None, "not_in_catalog"):  # a refused catalog part was still looked up
                records[f"PRT-{args['part_number']}"] = {"refused": r["reason"]}
    found = problems([e.model_dump() for e in draft.evidence], records, serial, list(dict.fromkeys(required)))
    found += [f"call search_manuals('{m}') and cite that section" for m in required if f"must cite {m}" in found and m not in records]
    return found


def assemble(draft: TriageDraft | None, calls: list[tuple[str, dict, dict]], stop: dict | None = None) -> TriageResult:
    """Harness post-processing: build the result from the LLM draft plus what the skills returned."""
    if stop and "denied" in stop:
        return TriageResult(status="denied", denial=Denial(**stop["denied"]), parts=[])
    if stop and stop.get("flag") == "instrument_not_found":
        return TriageResult(status="escalate", parts=[], flags=["instrument_not_found"],
                            diagnosis=Diagnosis(cause="unknown", confidence="low", summary="No freezer with that serial in the installed base."))
    context = _context(calls)
    flags = list(dict.fromkeys(f for _, _, r in calls for f in r.get("flags", [])))
    accepted = {r["proposal"]["part_number"]: r["proposal"] for name, _, r in calls if name == "propose_parts_order" and r.get("accepted")}
    parts = [Part(part_number=p["part_number"], name=p["name"], qty=p["qty"], chargeable=p["chargeable"]) for p in accepted.values()]
    # Status is a rule, not an opinion: an accepted part is a proposal; no telemetry or a "proposal" without
    # any accepted part means the case needs a human (R-DGN-6).
    if parts:
        status = "proposal"
    elif draft.status == "proposal" or {"telemetry_missing", "reported_reading_conflicts"} & set(flags):
        status = "escalate"
    else:
        status = draft.status
    at_risk = context["samples_at_risk"] if context else None
    fields = {"status": status, "diagnosis": draft.diagnosis, "evidence": draft.evidence, "advice": draft.advice, "parts": parts,
              "samples_at_risk": at_risk, "urgency": "urgent" if at_risk is True else "routine"}
    if parts:
        fields["approval"] = Approval(required=True, approver_role="service_manager", state="pending")
    if flags:
        fields["flags"] = flags
    return TriageResult(**fields)


async def triage(question: str, user: str, agent_id: str = "triage-agent", model: Model | None = None,
                 trace: str | None = None, eval_case: str | None = None) -> tuple[TriageResult, str]:
    trace = trace or audit.new_trace()
    token = badges.exchange(badges.user_badge(user), badges.agent_badge(agent_id))
    badge = badges.verify(token)
    model = model or gateway_model()
    alias = getattr(model, "model_name", str(model))
    audit.write(trace, "triage-agent", "question", badge, question=question, **({"eval_case": eval_case} if eval_case else {}))

    entry = badges.registry()[agent_id]
    if computed_tier(entry["manifest"]) > entry["certified_tier"]:
        # R-RSK-1: the composition now touches a higher tier than it was certified for → it doesn't run until promoted
        result = TriageResult(status="denied", denial=Denial(reason="tier", enforced_at="harness"), parts=[])
        audit.write(trace, "triage-agent", "denied", badge, reason="tier",
                    detail=f"manifest computes to T{computed_tier(entry['manifest'])}, certified T{entry['certified_tier']}", result=result.dump())
        return result, trace

    headers = {"Authorization": f"Bearer {token}", "X-Trace-Id": trace}
    calls: list[tuple[str, dict, dict]] = []
    pinned: dict = {}

    async def watch(ctx, call_tool, name, args):
        serial = args.get("serial")
        if serial is not None:
            serial = serial_of(serial)
            pinned.setdefault("serial", serial)
            if serial != pinned["serial"]:
                return {"error": "serial_mismatch", "detail": f"this run is about SN {pinned['serial']}; ask a new question for another freezer"}
        result = _as_dict(await call_tool(name, args))
        calls.append((name, args, result))
        if "denied" in result or result.get("flag") == "instrument_not_found":
            raise Stop(result)
        return result

    toolsets = [MCPToolset(Client(StreamableHttpTransport(url, headers=headers)), process_tool_call=watch)
                for skill, url in SKILL_URLS.items() if skill in entry["manifest"]]
    agent = Agent(model, output_type=TriageDraft, instructions=PROMPT, toolsets=toolsets, retries={"output": MAX_FIXES + 2})
    corrections: list[list[str]] = []
    unresolved: list[str] = []

    @agent.output_validator
    def grounded(ctx: RunContext, draft: TriageDraft) -> TriageDraft:
        """The G2 checks, at answer time, against the records this run actually saw. A fix never spends the last
        retry: when fixes run out, the draft goes out flagged grounding_unverified and the gates judge it."""
        if _context(calls) is None and ctx.retry < ctx.max_retries:
            raise ModelRetry("Call get_instrument_context for the freezer first; answer only from what it returns.")
        found = runtime_problems(draft, calls, pinned.get("serial"))
        if found and len(corrections) < MAX_FIXES and ctx.retry < ctx.max_retries:
            corrections.append(found)
            raise ModelRetry("Fix your evidence before answering:\n- " + "\n- ".join(found))
        unresolved[:] = found
        return draft

    draft, stop = None, None
    with capture_run_messages() as messages:
        try:
            draft = (await agent.run(question, usage_limits=LIMITS)).output
        except Stop as s:
            stop = s.answer
        except Exception as e:
            audit.write(trace, "triage-agent", "failed", badge, model_alias=alias, error=f"{type(e).__name__}: {e}", self_corrections=corrections)
            raise
    responses = [m for m in messages if isinstance(m, ModelResponse)]
    result = assemble(draft, calls, stop)
    if unresolved and not stop:  # fixes ran out: say so in the answer, never pass it off as verified
        result = TriageResult.model_validate(result.dump() | {"flags": [*(result.flags or []), "grounding_unverified"]})
    scheduling = None
    if result.parts:  # a visit is proposed by Field Ops' agent over A2A — code decides when, never the LLM
        scheduling = await schedule(headers, pinned["serial"], result.urgency)
        result = add_visit(result, scheduling)
    audit.write(trace, "triage-agent", "answered", badge, model_alias=alias, gateway_route=await gateway_route(alias),
                answered_by=responses[-1].model_name if responses else None,
                tokens={"in": sum(r.usage.input_tokens for r in responses), "out": sum(r.usage.output_tokens for r in responses)},
                tools=[{"skill": n, "args": a} for n, a, _ in calls], scheduling=scheduling,
                self_corrections=corrections, unresolved_grounding=unresolved, result=result.dump())
    return result, trace
