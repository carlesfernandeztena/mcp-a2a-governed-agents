"""Clean views over the audit log (the log stays the full record; these only choose what to show).

    uv run python -m cli.view                # last question: trace tree + audit card
    uv run python -m cli.view <trace>        # a specific trace
    uv run python -m cli.view --promotions   # promotion decisions from the eval gates
    uv run python -m cli.view --registry     # manifests, computed vs certified tier (who may run)
    uv run python -m cli.view <trace> --raw  # every audit line, unfiltered
"""
import argparse
import json
from collections import defaultdict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from harness import audit, badges
from harness.policy import computed_tier, skill_tier

console = Console()
COLOR = {"denied": "bold red", "refused": "yellow", "failed": "bold red", "proposed": "green", "proposed_visit": "green",
         "approved": "bold green", "submission_stubbed": "magenta", "not_found": "yellow", "answered": "cyan", "question": "bold"}


def line(e: dict) -> str:
    a, c = e["action"], e["component"]
    if a == "question":
        return f"[bold]{e['user']}[/] asks via [bold]{e['agent']}[/] v{e['agent_version']}: “{e['question']}”"
    if a == "read":
        return f"{c} → {len(e['records'])} record(s) {', '.join(e['records'][:3])}{'…' if len(e['records']) > 3 else ''}"
    if a == "denied":
        return f"{c} → DENIED: {e.get('reason')}  ({e.get('detail', '')})"
    if a == "refused":
        return f"{c} → refused {e.get('part_number', '')} {e.get('reason', '')} {e.get('rule', '')} {e.get('detail', '')}".rstrip()
    if a == "proposed":
        p = e["proposal"]
        return f"{c} → proposed {p['part_number']} ×{p['qty']}, €{p['price_eur']}{' (chargeable)' if p['chargeable'] else ''}, pending approval [{e.get('skill_version')}]"
    if a == "proposed_visit":
        v = e.get("visit", {})
        return f"{c} (A2A) → visit {v.get('engineer', '—')} {v.get('start', '')}  within SLA: {v.get('within_sla', 'n/a')}"
    if a == "answered":
        r = e["result"]
        return f"{c} → [bold]{r['status']}[/] · model {e['model_alias']} → {e.get('gateway_route') or 'scripted'} · tokens {e.get('tokens')}"
    if a == "served":
        extra = {k: e[k] for k in ("samples_at_risk", "flags") if k in e and e[k] not in (None, [])}
        return f"{c} → served {extra if extra else ''}".rstrip()
    return f"{c} → {a} {e.get('proposal_id', '')}"


def tree(events: list[dict]) -> Tree:
    """One line per decision; consecutive data-product reads collapse into one 'data seen' line."""
    t, reads = Tree(f"trace {events[0]['trace']}"), []

    def flush():
        if reads:
            counts = defaultdict(set)
            for r in reads:
                counts[r.split("-")[0]].add(r)
            t.add("[dim]data products → " + "  ".join(f"{k} {', '.join(sorted(v)) if len(v) <= 3 else f'×{len(v)}'}" for k, v in counts.items()) + "[/]")
            reads.clear()

    for e in events:
        if e["action"] == "read":
            reads.extend(e["records"])
            continue
        if e["action"] == "served" and e["component"] == "skills/search_manuals":
            continue  # the data line already says which sections
        flush()
        t.add(f"[{COLOR.get(e['action'], 'white')}]{line(e)}[/]")
    flush()
    return t


def card(events: list[dict]) -> Panel:
    q = next((e for e in events if e["action"] == "question"), events[0])
    ans = next((e for e in events if e["action"] == "answered"), None)
    seen = defaultdict(set)
    for e in events:
        for r in e.get("records", []):
            seen[r.split("-")[0]].add(r)
    rows = [("Who", q.get("user")), ("On behalf of", f"{q.get('agent')} v{q.get('agent_version')}"),
            ("What it saw", "  ".join(f"{k}: {len(v)}" for k, v in sorted(seen.items())) or "—"),
            ("Which model", f"{ans['model_alias']} → {ans.get('gateway_route') or 'scripted'}" if ans else "—"),
            ("Decision", (ans["result"]["status"] + (f" ({ans['result']['denial']['reason']})" if "denial" in ans["result"] else "")) if ans else "—"),
            ("Parts", ", ".join(p["part_number"] for p in ans["result"].get("parts", [])) if ans else "—"),
            ("Approved by", next((e["user"] for e in events if e["action"] == "approved"), "pending" if ans and ans["result"].get("approval") else "—"))]
    table = Table.grid(padding=(0, 2))
    for k, v in rows:
        table.add_row(f"[bold]{k}[/]", str(v))
    return Panel(table, title="Audit card", expand=False)


def registry() -> None:
    """SC5: each agent's manifest, the tier computed from it (R-RSK-1), the tier it is certified for, and whether it runs."""
    table = Table(title="Registry: computed vs certified tier (R-RSK-1)")
    for col in ("Agent", "Owner", "Manifest", "Computed", "Certified", "Runs?"):
        table.add_column(col)
    for name, a in badges.registry().items():
        computed = computed_tier(a["manifest"])
        runs = computed <= a["certified_tier"]
        table.add_row(f"{name} v{a['version']}", a["owner"], "\n".join(f"{s} (T{skill_tier(s)})" for s in a["manifest"]),
                      f"T{computed}", f"T{a['certified_tier']}", "[green]yes[/]" if runs else "[red]no — denied until promoted[/]")
    console.print(table)


def promotions() -> None:
    table = Table(title="Promotion decisions (R-CRT-1)")
    for col in ("When", "Candidate", "G1", "G2", "G3", "Decision"):
        table.add_column(col)
    for e in [e for e in audit.read() if e["action"] == "promotion"][-8:]:
        cells = ["[green]PASS[/]" if not e["gates"][g]["failed"] else f"[red]FAIL ({len(e['gates'][g]['failed'])})[/]" for g in ("G1", "G2", "G3")]
        table.add_row(e["ts"], e["candidate"], *cells, "[green]CERTIFIED[/]" if e["decision"] == "certified" else "[red]BLOCKED[/]")
    console.print(table)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("trace", nargs="?")
    p.add_argument("--promotions", action="store_true")
    p.add_argument("--registry", action="store_true")
    p.add_argument("--raw", action="store_true")
    a = p.parse_args()
    if a.promotions or a.registry:
        promotions() if a.promotions else registry()
        raise SystemExit
    trace = a.trace or next(e["trace"] for e in reversed(audit.read()) if e["action"] == "question")
    events = audit.read(trace)
    if a.raw:
        for e in events:
            console.print_json(json.dumps(e, ensure_ascii=False))
    else:
        console.print(tree(events))
        console.print(card(events))
