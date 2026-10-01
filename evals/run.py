"""Eval runner: every case through the real system, three gates, one promotion decision (R-CRT-1).

    uv run python -m evals.run                                   # certified build
    SKILL_PARTS_URL=http://localhost:8113/mcp uv run python -m evals.run --candidate "1.1-rc (parts skill 0.4)"

The decision follows from the results, never from judgement in the moment: all gates pass on every case,
core and variations → CERTIFIED; anything else → BLOCKED.
"""
import argparse
import asyncio
import json
import time

from rich.console import Console
from rich.table import Table

from agents.triage.agent import triage
from evals.gates import gate_results
from harness import audit
from harness.rules import ROOT

CASES = [json.loads(line) for line in (ROOT / "evals" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]


async def run_all(cases: list[dict], parallel: int = 4) -> dict[str, dict]:
    gate = asyncio.Semaphore(parallel)

    async def one(case):
        async with gate:
            try:
                result, trace = await triage(case["input"], case["user"], case.get("agent", "triage-agent"))
                return case["id"], result.dump() | {"_trace": trace}
            except Exception as e:  # a crash is a failed case, not a crashed eval
                return case["id"], {"status": "error", "error": f"{type(e).__name__}: {e}"}

    return dict(await asyncio.gather(*(one(c) for c in cases)))


def show(gates: dict, decision: str, candidate: str, seconds: float) -> None:
    console = Console()
    table = Table(title=f"Eval gates — {candidate}")
    for col in ("Gate", "Cases", "Result", "Failures"):
        table.add_column(col)
    names = {"G1": "Policy & safety", "G2": "Grounding", "G3": "Action correctness"}
    for g, r in gates.items():
        ok = not r["failed"]
        detail = "\n".join(f"{cid}: {reasons[0]}" for cid, reasons in list(r["failed"].items())[:4])
        table.add_row(f"{g} {names[g]}", str(r["cases"]), "[green]PASS[/]" if ok else f"[red]FAIL ({len(r['failed'])})[/]", detail)
    console.print(table)
    console.print(f"Promotion decision: {'[bold green]CERTIFIED' if decision == 'certified' else '[bold red]BLOCKED'}[/]  ({seconds:.0f}s)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--candidate", default="triage-agent 1.0", help="label of the build under evaluation")
    p.add_argument("--only", nargs="*", help="run a subset of case ids (exploration only: no promotion decision)")
    a = p.parse_args()
    cases = [c for c in CASES if not a.only or c["id"] in a.only]
    start = time.time()
    results = asyncio.run(run_all(cases))
    gates = gate_results(cases, results)
    decision = "certified" if not a.only and all(not g["failed"] for g in gates.values()) else "blocked"
    out = ROOT / "evals" / "results" / f"{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"candidate": a.candidate, "decision": decision, "gates": gates, "results": results}, indent=1, ensure_ascii=False))
    if not a.only:
        audit.write(audit.new_trace(), "evals", "promotion", None, candidate=a.candidate, decision=decision,
                    gates={g: {"cases": r["cases"], "failed": sorted(r["failed"])} for g, r in gates.items()}, results_file=out.name)
    show(gates, decision if not a.only else "blocked (subset run, no decision)", a.candidate, time.time() - start)
    print(f"details: {out.relative_to(ROOT)}")
