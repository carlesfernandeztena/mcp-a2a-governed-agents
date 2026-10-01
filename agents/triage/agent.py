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
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_data_parts, new_data_message
from a2a.types.a2a_pb2 import Role, SendMessageRequest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from pydantic_ai import Agent, ModelRetry, capture_run_messages
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.litellm import LiteLLMProvider
from pydantic_ai.usage import UsageLimits

from harness import audit, badges
from harness.contract import Approval, Denial, Diagnosis, Part, TriageDraft, TriageResult, Visit
from harness.policy import computed_tier
from harness.rules import rules

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
SKILL_URLS = {
    "get_instrument_context": os.environ.get("SKILL_CONTEXT_URL", "http://localhost:8101/mcp"),
    "search_manuals": os.environ.get("SKILL_MANUALS_URL", "http://localhost:8102/mcp"),
    "propose_parts_order": os.environ.get("SKILL_PARTS_URL", "http://localhost:8103/mcp"),
}
SCHEDULING_URL = os.environ.get("SCHEDULING_URL", "http://localhost:8201/")
PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8").replace("{today}", rules()["today"])
LIMITS = UsageLimits(request_limit=10)  # cost cap per question


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
            client = await ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create_from_url(SCHEDULING_URL)
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
    if "visit" in answer:
        fields["visit"] = Visit(**answer["visit"])
        if answer["visit"].get("within_sla") is False:
            flags.append("sla_breach")
    else:
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
    elif draft.status == "proposal" or "telemetry_missing" in flags:
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
                 trace: str | None = None) -> tuple[TriageResult, str]:
    trace = trace or audit.new_trace()
    token = badges.exchange(badges.user_badge(user), badges.agent_badge(agent_id))
    badge = badges.verify(token)
    model = model or gateway_model()
    alias = getattr(model, "model_name", str(model))
    audit.write(trace, "triage-agent", "question", badge, question=question)

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
            pinned.setdefault("serial", str(serial))
            if str(serial) != pinned["serial"]:
                return {"error": "serial_mismatch", "detail": f"this run is about SN {pinned['serial']}; ask a new question for another freezer"}
        result = _as_dict(await call_tool(name, args))
        calls.append((name, args, result))
        if "denied" in result or result.get("flag") == "instrument_not_found":
            raise Stop(result)
        return result

    toolsets = [MCPToolset(Client(StreamableHttpTransport(url, headers=headers)), process_tool_call=watch)
                for skill, url in SKILL_URLS.items() if skill in entry["manifest"]]
    agent = Agent(model, output_type=TriageDraft, instructions=PROMPT, toolsets=toolsets)

    @agent.output_validator
    def looked_it_up(draft: TriageDraft) -> TriageDraft:
        if _context(calls) is None:
            raise ModelRetry("Call get_instrument_context for the freezer first; answer only from what it returns.")
        return draft

    draft, stop = None, None
    with capture_run_messages() as messages:
        try:
            draft = (await agent.run(question, usage_limits=LIMITS)).output
        except Stop as s:
            stop = s.answer
        except Exception as e:
            audit.write(trace, "triage-agent", "failed", badge, model_alias=alias, error=f"{type(e).__name__}: {e}")
            raise
    responses = [m for m in messages if isinstance(m, ModelResponse)]
    result = assemble(draft, calls, stop)
    if result.parts:  # a visit is proposed by Field Ops' agent over A2A — code decides when, never the LLM
        result = add_visit(result, await schedule(headers, pinned["serial"], result.urgency))
    audit.write(trace, "triage-agent", "answered", badge, model_alias=alias, gateway_route=await gateway_route(alias),
                answered_by=responses[-1].model_name if responses else None,
                tokens={"in": sum(r.usage.input_tokens for r in responses), "out": sum(r.usage.output_tokens for r in responses)},
                tools=[{"skill": n, "args": a} for n, a, _ in calls], result=result.dump())
    return result, trace
