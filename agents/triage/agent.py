"""triage-agent: Pydantic AI → model gateway → MCP skills, wrapped by the harness.

The LLM returns only a TriageDraft (judgement). Everything else in the TriageResult comes from code:
denials and unknown serials stop the run before the LLM can improvise; parts come from the proposals the
skill accepted (not from what the LLM wrote); sample risk comes from the context skill; urgency and
approval are derived. See docs/OUTPUT_CONTRACT.md.
"""
import json
import os
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.litellm import LiteLLMProvider

from harness import audit, badges
from harness.contract import Approval, Denial, Diagnosis, Part, TriageDraft, TriageResult

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
SKILL_URLS = {
    "get_instrument_context": os.environ.get("SKILL_CONTEXT_URL", "http://localhost:8101/mcp"),
    "search_manuals": os.environ.get("SKILL_MANUALS_URL", "http://localhost:8102/mcp"),
    "propose_parts_order": os.environ.get("SKILL_PARTS_URL", "http://localhost:8103/mcp"),
}
PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")


class Stop(Exception):
    """A skill answered with something only code may handle (denial, unknown serial): end the run now."""
    def __init__(self, answer: dict):
        super().__init__(json.dumps(answer))
        self.answer = answer


def gateway_model(alias: str = "triage-llm") -> Model:
    """Agents only ever know the gateway alias; which provider serves it is the gateway's business."""
    return OpenAIChatModel(alias, provider=LiteLLMProvider(api_base=GATEWAY_URL))


def _as_dict(result) -> dict:
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {}
    return {}


def assemble(draft: TriageDraft | None, calls: list[tuple[str, dict, dict]], stop: dict | None = None) -> TriageResult:
    """Harness post-processing: build the result from the LLM draft plus what the skills returned."""
    if stop and "denied" in stop:
        return TriageResult(status="denied", denial=Denial(**stop["denied"]), parts=[])
    context = next((r for name, _, r in reversed(calls) if name == "get_instrument_context" and "instrument" in r), None)
    flags = list(dict.fromkeys(f for _, _, r in calls for f in r.get("flags", [])))
    if stop and stop.get("flag") == "instrument_not_found":
        return TriageResult(status="escalate", parts=[], flags=["instrument_not_found"],
                            diagnosis=Diagnosis(cause="unknown", confidence="low", summary="No freezer with that serial in the installed base."))
    accepted = [r["proposal"] for name, _, r in calls if name == "propose_parts_order" and r.get("accepted")]
    parts = [Part(part_number=p["part_number"], name=p["name"], qty=p["qty"], chargeable=p["chargeable"]) for p in accepted]
    result = TriageResult(status=draft.status, diagnosis=draft.diagnosis, evidence=draft.evidence, advice=draft.advice, parts=parts)
    if context is not None:
        result.samples_at_risk = context["samples_at_risk"]
        result.urgency = "urgent" if context["samples_at_risk"] is True else "routine"
    if parts:
        result.approval = Approval(required=True, approver_role="service_manager", state="pending")
    if flags:
        result.flags = flags
    return result


async def triage(question: str, user: str, agent_id: str = "triage-agent", model: Model | None = None,
                 trace: str | None = None) -> tuple[TriageResult, str]:
    trace = trace or audit.new_trace()
    token = badges.exchange(badges.user_badge(user), badges.agent_badge(agent_id))
    badge = badges.verify(token)
    headers = {"Authorization": f"Bearer {token}", "X-Trace-Id": trace}
    calls: list[tuple[str, dict, dict]] = []

    async def watch(ctx, call_tool, name, args):
        result = _as_dict(await call_tool(name, args))
        calls.append((name, args, result))
        if "denied" in result or result.get("flag") == "instrument_not_found":
            raise Stop(result)
        return result

    manifest = badges.registry()[agent_id]["manifest"]
    toolsets = [MCPToolset(Client(StreamableHttpTransport(url, headers=headers)), process_tool_call=watch)
                for skill, url in SKILL_URLS.items() if skill in manifest]
    model = model or gateway_model()
    agent = Agent(model, output_type=TriageDraft, instructions=PROMPT, toolsets=toolsets)
    audit.write(trace, "triage-agent", "question", badge, question=question)

    draft, stop, answered_by, usage = None, None, None, None
    try:
        run = await agent.run(question)
        draft, answered_by, usage = run.output, run.response.model_name, run.usage
    except Stop as s:
        stop = s.answer
    result = assemble(draft, calls, stop)
    audit.write(trace, "triage-agent", "answered", badge, model_alias=getattr(model, "model_name", str(model)),
                answered_by=answered_by, tokens={"in": usage.input_tokens, "out": usage.output_tokens} if usage else None,
                tools=[{"skill": n, "args": a} for n, a, _ in calls], result=result.dump())
    return result, trace
