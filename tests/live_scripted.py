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
    print("SC1 ok", trace)

    r, _ = await triage("SN 7001", "yusuf", model=script(("get_instrument_context", {"serial": "7001"}), ("final", FINAL)))
    assert r.dump()["status"] == "denied" and r.dump()["denial"]["reason"] == "territory"
    print("SC4 deny ok")

    r, _ = await triage("order", "consuelo", "quick-lookup", model=script(("final", FINAL)))
    assert r.dump()["denial"] == {"reason": "tier", "enforced_at": "harness"}      # uncertified composition never runs
    print("SC5 tier ok")

    # The run is pinned to the first freezer: proposing 80-A "for 3210" can't dodge the revision check on 5123 (L4-01)
    r, _ = await triage("SN 5123", "yusuf", model=script(("get_instrument_context", {"serial": "5123"}),
                                                          ("propose_parts_order", {"serial": "3210", "part_number": "GK-80-A"}), ("final", FINAL)))
    assert r.dump()["parts"] == [] and r.dump()["status"] == "escalate", r.dump()
    print("serial pin ok")

    # No context call → the validator makes the model look it up before answering
    r, _ = await triage("SN 5123", "yusuf", model=script(("final", FINAL), ("get_instrument_context", {"serial": "5123"}), ("final", FINAL)))
    assert r.dump()["samples_at_risk"] is False
    print("must look up first ok")


if __name__ == "__main__":
    asyncio.run(main())
