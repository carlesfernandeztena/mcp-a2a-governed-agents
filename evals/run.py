"""Eval runner: every case through the real system, three gates, one promotion decision (R-CRT-1).

    uv run python -m evals.run                                   # certified build
    SKILL_PARTS_URL=http://localhost:8113/mcp uv run python -m evals.run --candidate "1.1-rc (parts skill 0.4)"

The decision follows from the results, never from judgement in the moment: all gates pass on every case,
core and variations, in every one of --repeat runs (pass^k, default 3) → CERTIFIED; anything else → BLOCKED.
"""
import argparse
import asyncio
import json
import time

from rich.console import Console
from rich.table import Table

from agents.triage.agent import GATEWAY_URL, SCHEDULING_URL, SKILL_URLS, gateway_route, triage
from evals.gates import gate_results
from harness import audit
from harness.rules import ROOT

CASES = [json.loads(line) for line in (ROOT / "evals" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]


async def run_all(cases: list[dict], parallel: int = 4) -> dict[str, dict]:
    gate = asyncio.Semaphore(parallel)

    async def one(case):
        async with gate:
            try:
                result, trace = await asyncio.wait_for(triage(case["input"], case["user"], case.get("agent", "triage-agent")), 180)
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
    p.add_argument("--repeat", type=int, default=3, help="full runs; certification needs every run green (pass^k)")
    a = p.parse_args()
    cases = [c for c in CASES if not a.only or c["id"] in a.only]
    start = time.time()
    build = {"skills": SKILL_URLS, "scheduling": SCHEDULING_URL, "gateway": GATEWAY_URL,
             "triage_llm": asyncio.run(gateway_route("triage-llm"))}   # what actually ran, not just a label
    out = ROOT / "evals" / "results" / f"{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    runs = []
    for k in range(a.repeat):  # a non-deterministic model needs repeated evidence, not one lucky green run
        results = asyncio.run(run_all(cases))
        runs.append({"results": results, "gates": gate_results(cases, results)})
        out.write_text(json.dumps({"candidate": a.candidate, "build": build, "runs": runs}, indent=1, ensure_ascii=False))  # raw as we go
    passes = {c["id"]: sum(not any(c["id"] in g["failed"] for g in run["gates"].values()) for run in runs) for c in cases}
    unstable = {cid: f"{n}/{a.repeat}" for cid, n in passes.items() if n < a.repeat}
    gates = {g: {"cases": runs[0]["gates"][g]["cases"], "failed": {cid: r for run in runs for cid, r in run["gates"][g]["failed"].items()}}
             for g in ("G1", "G2", "G3")}   # union of failures across runs
    decision = "certified" if not a.only and not unstable else "blocked"
    out.write_text(json.dumps({"candidate": a.candidate, "build": build, "repeat": a.repeat, "decision": decision,
                               "pass_rate": passes, "gates": gates, "runs": runs}, indent=1, ensure_ascii=False))
    if not a.only:
        audit.write(audit.new_trace(), "evals", "promotion", None, candidate=a.candidate, build=build, decision=decision, repeat=a.repeat,
                    unstable=unstable, gates={g: {"cases": r["cases"], "failed": sorted(r["failed"])} for g, r in gates.items()},
                    results_file=out.name)
    show(gates, decision if not a.only else "blocked (subset run, no decision)", f"{a.candidate} · pass^{a.repeat}", time.time() - start)
    if unstable:
        print("Unstable cases (passed / runs):", ", ".join(f"{cid} {r}" for cid, r in unstable.items()))
    print(f"details: {out.relative_to(ROOT)}")
