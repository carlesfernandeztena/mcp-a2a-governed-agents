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
         "evidence": [{"ref": "TEL-5123-2026-10-01", "claim": "-74.0 °C, recovery 45 min"},
                      {"ref": "MAN-CX80-E47", "claim": "normal current + slow recovery = worn gasket"}], "advice": []}
MANUAL = ("search_manuals", {"query": "E-47"})


async def main():
    sc1 = script(("get_instrument_context", {"serial": "5123"}), MANUAL,
                 ("propose_parts_order", {"serial": "5123", "part_number": "GK-80-A"}),   # plausible-wrong: refused
                 ("propose_parts_order", {"serial": "5123", "part_number": "GK-80-B"}), ("final", FINAL))
    r, trace = await triage("SN 5123 E-47", "yusuf", model=sc1)
    d = r.dump()
    assert [p["part_number"] for p in d["parts"]] == ["GK-80-B"] and d["approval"]["state"] == "pending" and d["urgency"] == "routine", d
    assert (d["visit"]["engineer"], d["visit"]["start"], d["visit"]["within_sla"]) == ("mariona", "2026-10-05T14:00:00+02:00", True), d
    print("SC1 ok (visit over A2A)", trace)

    # SC8: the scheduling agent is down → the proposal stands, without a visit, flagged
    import agents.triage.agent as triage_module
    real, triage_module.SCHEDULING_URL = triage_module.SCHEDULING_URL, "http://localhost:8299/"
    try:
        r, _ = await triage("SN 5123 E-47", "yusuf", model=script(("get_instrument_context", {"serial": "5123"}), MANUAL,
                                                                   ("propose_parts_order", {"serial": "5123", "part_number": "GK-80-B"}), ("final", FINAL)))
    finally:
        triage_module.SCHEDULING_URL = real
    assert "visit" not in r.dump() and r.dump()["flags"] == ["scheduling_unavailable"] and r.dump()["status"] == "proposal", r.dump()
    print("SC8 scheduling down ok")

    r, _ = await triage("SN 7001", "yusuf", model=script(("get_instrument_context", {"serial": "7001"}), ("final", FINAL)))
    assert r.dump()["status"] == "denied" and r.dump()["denial"]["reason"] == "territory"
    print("SC4 deny ok")

    r, _ = await triage("order", "consuelo", "quick-lookup", model=script(("final", FINAL)))
    assert r.dump()["denial"] == {"reason": "tier", "enforced_at": "harness"}      # uncertified composition never runs
    print("SC5 tier ok")

    # The run is pinned to the first freezer: proposing 80-A "for 3210" can't dodge the revision check on 5123 (L4-01)
    r, _ = await triage("SN 5123", "yusuf", model=script(("get_instrument_context", {"serial": "5123"}), MANUAL,
                                                          ("propose_parts_order", {"serial": "3210", "part_number": "GK-80-A"}), ("final", FINAL)))
    assert r.dump()["parts"] == [] and r.dump()["status"] == "escalate", r.dump()
    print("serial pin ok")

    # A made-up citation is caught at answer time and the model fixes it (the G2 check, run as a guardrail)
    bad = FINAL | {"evidence": FINAL["evidence"] + [{"ref": "SRV-9999", "claim": "invented"}]}
    r, trace = await triage("SN 5123", "yusuf", model=script(("get_instrument_context", {"serial": "5123"}), MANUAL, ("final", bad), ("final", FINAL)))
    from harness import audit
    [ans] = [e for e in audit.read(trace) if e["action"] == "answered"]
    assert [e["ref"] for e in r.dump()["evidence"]] == ["TEL-5123-2026-10-01", "MAN-CX80-E47"] and len(ans["self_corrections"]) == 1, ans["self_corrections"]
    print("self-correction ok")

    # No context call → the validator makes the model look it up before answering
    r, _ = await triage("SN 5123", "yusuf", model=script(("final", FINAL), ("get_instrument_context", {"serial": "5123"}), MANUAL, ("final", FINAL)))
    assert r.dump()["samples_at_risk"] is False
    print("must look up first ok")

    # A diagnosis without the manual section it comes from: the hint makes the model search and cite it
    r, trace = await triage("SN 5123", "yusuf", model=script(("get_instrument_context", {"serial": "5123"}),
                                                              ("final", FINAL | {"evidence": FINAL["evidence"][:1]}), MANUAL, ("final", FINAL)))
    [ans] = [e for e in audit.read(trace) if e["action"] == "answered"]
    assert "MAN-CX80-E47" in [e["ref"] for e in r.dump()["evidence"]] and len(ans["self_corrections"]) == 1, ans
    print("diagnosis cites its manual section ok")


if __name__ == "__main__":
    asyncio.run(main())
