"""scheduling-agent: Field Ops' agent behind A2A. Deterministic code, no LLM — the caller can't tell and doesn't need to.

It trusts nothing in the request except the serial and the urgency: who is asking comes from the badge (R-ACC-5),
and the freezer's country and contract come from the data products, read with that same badge.
Rules: R-SCH-0..3 (earliest free slot of an engineer covering the site's country; SLA deadline; breach flag).
"""
import csv
import os
from datetime import datetime, time, timedelta
from urllib.parse import quote

import httpx
import uvicorn
from a2a.helpers.proto_helpers import get_data_parts, new_data_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, HTTPAuthSecurityScheme, SecurityScheme
from starlette.applications import Starlette

from harness import audit, badges
from harness.policy import Denied, check_skill_call
from harness.rules import ROOT, rules

DATA_URL = os.environ.get("DATA_URL", "http://localhost:8001")
URL = os.environ.get("SCHEDULING_PUBLIC_URL", "http://localhost:8201/")


def deadline(contract_tier: str, urgency: str) -> datetime | None:
    """R-SCH-1: N business days after today, at the end of the working day. No contract → no SLA."""
    r = rules()
    if contract_tier == "none":
        return None
    days = r["scheduling"]["urgent_business_days"] if urgency == "urgent" else r["scheduling"]["sla_business_days"][contract_tier]
    d = datetime.fromisoformat(r["today"])
    while days:
        d += timedelta(days=1)
        days -= d.weekday() < 5
    return datetime.combine(d.date(), time(r["scheduling"]["deadline_hour"]), tzinfo=datetime.fromisoformat(f"{r['today']}T00:00{r['timezone']}").tzinfo)


def earliest_slot(country: str) -> dict | None:
    """R-SCH-2: only engineers covering the site's country, only real free slots, after today."""
    engineers = {p["id"] for p in badges.people().values() if p["role"] == "field_engineer" and p["country"] == country}
    with open(ROOT / "data" / "calendar.csv", encoding="utf-8", newline="") as f:
        slots = [s for s in csv.DictReader(f) if s["engineer"] in engineers]
    after = datetime.fromisoformat(f"{rules()['today']}T23:59{rules()['timezone']}")  # no same-day slots
    slots = sorted((s for s in slots if datetime.fromisoformat(s["start"]) > after), key=lambda s: datetime.fromisoformat(s["start"]))
    return slots[0] if slots else None


def propose_visit(instrument: dict, urgency: str) -> dict:
    due = deadline(instrument["contract_tier"], urgency)
    slot = earliest_slot(instrument["country"])
    visit = {}
    if slot:
        visit |= {"engineer": slot["engineer"], "start": slot["start"], "end": slot["end"]}
    if due:
        visit |= {"sla_deadline": due.isoformat(), "within_sla": bool(slot) and datetime.fromisoformat(slot["end"]) <= due}
    return visit


class Scheduler(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue) -> None:
        headers = context.call_context.state.get("headers", {})
        trace = headers.get("x-trace-id") or audit.new_trace()
        try:
            badge = badges.from_header(headers.get("authorization"))
            check_skill_call(badge, "propose_visit")
            [request] = get_data_parts(context.message.parts)
            r = httpx.get(f"{DATA_URL}/instruments/{quote(str(request['serial']), safe='')}",
                          headers={"Authorization": headers["authorization"], "X-Trace-Id": trace}, timeout=10)
            if r.status_code == 403:
                raise Denied(r.json()["detail"]["denial"]["reason"], "scheduling-agent")
            r.raise_for_status()
            answer = {"visit": propose_visit(r.json(), request.get("urgency", "routine"))}
            audit.write(trace, "scheduling-agent", "proposed_visit", badge, serial=request["serial"], **answer)
        except Denied as d:
            answer = {"denied": {"reason": d.reason, "enforced_at": d.enforced_at}}
            audit.write(trace, "scheduling-agent", "denied", None, reason=d.reason)
        except (PermissionError, ValueError, KeyError, httpx.HTTPError) as e:
            answer = {"error": type(e).__name__, "detail": str(e)}
            audit.write(trace, "scheduling-agent", "refused", None, detail=str(e))
        await event_queue.enqueue_event(new_data_message(answer, context_id=context.context_id, task_id=context.task_id))

    async def cancel(self, context: RequestContext, event_queue) -> None:
        raise NotImplementedError("visits are proposed instantly; nothing to cancel")


card = AgentCard(
    name="scheduling-agent",
    description="Field Ops: proposes a visit window within the contract SLA. Send a data part {serial, urgency}.",
    version="1.0",
    supported_interfaces=[AgentInterface(url=URL, protocol_binding="JSONRPC")],
    capabilities=AgentCapabilities(streaming=False),
    security_schemes={"badge": SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer", bearer_format="JWT"))},
    security_requirements=[{"schemes": {"badge": {"list": []}}}],
    default_input_modes=["application/json"],
    default_output_modes=["application/json"],
    skills=[AgentSkill(id="propose_visit", name="Propose a visit window", description="Earliest free slot of an engineer covering the site, checked against the SLA.", tags=["scheduling"])],
)
handler = DefaultRequestHandler(agent_executor=Scheduler(), task_store=InMemoryTaskStore(), agent_card=card)
app = Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/"))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8201, log_level="warning")
