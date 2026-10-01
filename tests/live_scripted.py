"""Full chain with a scripted model (no LLM, no API cost): agent → MCP skills → data products → harness.
Needs the services running (docker compose up, or locally). Run: uv run python -m tests.live_scripted"""
import asyncio

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agents.triage.agent import triage


def script(*steps):
    """A fake LLM that makes the given tool calls in order, then returns the final draft."""
    def model(messages, info: AgentInfo):
        i = sum(isinstance(m, ModelResponse) for m in messages)
        name, args = steps[i]
        return ModelResponse(parts=[ToolCallPart(name if name != "final" else info.output_tools[0].name, args)])
    return FunctionModel(model)


FINAL = {"status": "proposal", "diagnosis": {"cause": "door_gasket_worn", "confidence": "high", "summary": "Worn gasket."},
         "evidence": [{"ref": "TEL-5123-2026-10-01", "claim": "-74.0 °C, recovery 45 min"}], "advice": []}


async def main():
    sc1 = script(("get_instrument_context", {"serial": "5123"}), ("search_manuals", {"query": "E-47"}),
                 ("propose_parts_order", {"serial": "5123", "part_number": "GK-80-A"}),   # plausible-wrong: refused
                 ("propose_parts_order", {"serial": "5123", "part_number": "GK-80-B"}), ("final", FINAL))
    r, trace = await triage("SN 5123 E-47", "yusuf", model=sc1)
    d = r.dump()
    assert [p["part_number"] for p in d["parts"]] == ["GK-80-B"] and d["approval"]["state"] == "pending" and d["urgency"] == "routine", d
    assert (d["visit"]["engineer"], d["visit"]["start"], d["visit"]["within_sla"]) == ("mariona", "2026-10-05T14:00:00+02:00", True), d
    print("SC1 ok (visit over A2A)", trace)

    r, _ = await triage("SN 7001", "yusuf", model=script(("get_instrument_context", {"serial": "7001"}), ("final", FINAL)))
    assert r.dump()["status"] == "denied" and r.dump()["denial"]["reason"] == "territory"
    print("SC4 deny ok")

    r, _ = await triage("order", "consuelo", "quick-lookup", model=script(("propose_parts_order", {"serial": "5123", "part_number": "GK-80-B"}), ("final", FINAL)))
    assert r.dump()["denial"]["reason"] == "tier"
    print("SC5 tier ok")


if __name__ == "__main__":
    asyncio.run(main())
