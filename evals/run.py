"""Eval runner: every case through the real system, three gates, one promotion decision (R-CRT-1).

    uv run python -m evals.run                                   # certified build
    SKILL_PARTS_URL=http://localhost:8113/mcp uv run python -m evals.run --candidate "1.1-rc (parts skill 0.4)"

The decision follows from the results, never from judgement in the moment: all gates pass on every case,
core and variations, in each of rules.yaml certification.runs full runs (pass^3) → CERTIFIED; anything else → BLOCKED. A failing run
stops early: it can't certify.
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
from harness.rules import ROOT, rules

CASES = [json.loads(line) for line in (ROOT / "evals" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]


async def run_all(cases: list[dict], parallel: int = 4) -> dict[str, dict]:
    gate = asyncio.Semaphore(parallel)

    async def one(case):
        async with gate:
            try:
                result, trace = await asyncio.wait_for(triage(case["input"], case["user"], case.get("agent", "triage-agent"), eval_case=case["id"]), 180)
                return case["id"], result.dump() | {"_trace": trace}
            except Exception as e:  # a crash is a failed case, not a crashed eval
                return case["id"], {"status": "error", "error": f"{type(e).__name__}: {e}"}

    return dict(await asyncio.gather(*(one(c) for c in cases)))


def decide(cases: list[dict], runs: list[dict], repeat: int, subset: bool = False) -> tuple[str, dict, dict]:
    """R-CRT-1: certified only for a full suite, at least rules.yaml certification.runs runs, every one all green.
    Returns (decision, failures per gate across runs with the run number, per-case pass rate for any case that failed)."""
    passes = {c["id"]: sum(not any(c["id"] in g["failed"] for g in run["gates"].values()) for run in runs) for c in cases}
    unstable = {cid: f"{n}/{len(runs)}" for cid, n in passes.items() if n < len(runs)}
    gates = {g: {"cases": runs[0]["gates"][g]["cases"], "failed": {}} for g in ("G1", "G2", "G3")}
    for k, run in enumerate(runs, 1):
        for g, r in run["gates"].items():
            for cid, reasons in r["failed"].items():
                gates[g]["failed"].setdefault(cid, []).extend(f"run {k}: {x}" for x in reasons)
    enough = not subset and len(runs) >= rules()["certification"]["runs"] and len(runs) == repeat
    return ("certified" if enough and not unstable else "blocked"), gates, unstable


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
    p.add_argument("--repeat", type=int, help="full runs (default: rules.yaml certification.runs; 1 with --only)")
    a = p.parse_args()
    cases = [c for c in CASES if not a.only or c["id"] in a.only]
    repeat = max(1, a.repeat or (1 if a.only else rules()["certification"]["runs"]))
    start = time.time()
    build = {"skills": SKILL_URLS, "scheduling": SCHEDULING_URL, "gateway": GATEWAY_URL,
             "triage_llm": asyncio.run(gateway_route("triage-llm"))}   # what actually ran, not just a label
    out = ROOT / "evals" / "results" / f"{time.strftime('%Y%m%dT%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    runs = []
    for k in range(repeat):  # a non-deterministic model needs repeated evidence, not one lucky green run
        results = asyncio.run(run_all(cases))
        runs.append({"results": results, "gates": gate_results(cases, results)})
        out.write_text(json.dumps({"candidate": a.candidate, "build": build, "runs": runs}, indent=1, ensure_ascii=False))  # raw as we go
        if any(g["failed"] for g in runs[-1]["gates"].values()):
            break  # a failing run can't certify; don't spend more
    decision, gates, unstable = decide(cases, runs, repeat, subset=bool(a.only))
    out.write_text(json.dumps({"candidate": a.candidate, "build": build, "repeat": repeat, "decision": decision,
                               "unstable": unstable, "gates": gates, "runs": runs}, indent=1, ensure_ascii=False))
    if not a.only:
        audit.write(audit.new_trace(), "evals", "promotion", None, candidate=a.candidate, build=build, decision=decision,
                    runs=f"{len(runs)}/{repeat}", unstable=unstable,
                    gates={g: {"cases": r["cases"], "failed": sorted(r["failed"])} for g, r in gates.items()}, results_file=out.name)
    show(gates, decision if not a.only else "blocked (subset run, no decision)", f"{a.candidate} · {len(runs)}/{repeat} runs", time.time() - start)
    if unstable:
        print("Cases that failed (passed / runs):", ", ".join(f"{cid} {r}" for cid, r in unstable.items()))
    print(f"details: {out.relative_to(ROOT)}")
