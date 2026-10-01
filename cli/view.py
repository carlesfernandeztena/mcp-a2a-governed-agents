"""Clean views over the audit log (the log stays the full record; these only choose what to show).
Used by `demo view`, `demo follow`, `demo registry` and `demo promotions` (cli/__main__.py)."""
import json
import time
from collections import defaultdict

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from harness import audit, badges
from harness.policy import computed_tier, skill_tier

console = Console()
COLOR = {"denied": "bold red", "refused": "yellow", "failed": "bold red", "proposed": "green", "proposed_visit": "green",
         "approved": "bold green", "rejected": "bold red", "submission_stubbed": "magenta", "not_found": "yellow",
         "answered": "cyan", "question": "bold", "served": "green"}


def model_of(e: dict) -> str:
    alias = e.get("model_alias") or ""
    if alias.startswith("function:"):
        return "scripted test model"
    return f"{alias} → {e.get('gateway_route') or e.get('provider_model') or 'route not recorded'}"


def line(e: dict) -> str:
    """One readable line per event. Every value from the log is escaped: the log is the truth, never markup."""
    s = {k: escape(str(v)) for k, v in e.items() if not isinstance(v, (dict, list))}
    a, c, who = e["action"], s["component"], s.get("user", "—")
    if a == "question":
        return f"[bold]{who}[/] asks via [bold]{s['agent']}[/] v{s['agent_version']}: “{s['question']}”"
    if a == "denied":
        return f"{c} → DENIED: {s.get('reason', '')} {s.get('serial', '')}  {s.get('detail', '')}".rstrip()
    if a == "refused":
        what = " ".join(s.get(k, "") for k in ("part_number", "reason", "rule") if s.get(k))
        return f"{c} → refused {what} (by/for {who}) {s.get('detail', '')}".rstrip()
    if a == "not_found":
        return f"{c} → not found {s.get('serial', '')}{s.get('part_number', '')}"
    if a == "proposed":
        p = e["proposal"]
        return f"{c} → proposed {escape(p['part_number'])} ×{p['qty']}, €{p['price_eur']}{' (chargeable)' if p['chargeable'] else ''}, pending approval (skill v{s.get('skill_version')})"
    if a == "proposed_visit":
        v = e.get("visit", {})
        return f"{c} (A2A) → visit {escape(str(v.get('engineer', '—')))} {escape(str(v.get('start', '')))}  within SLA: {v.get('within_sla', 'n/a')}"
    if a == "answered":
        down = (e.get("scheduling") or {}).get("error")   # the A2A hop failed: say so where the hop would have been
        return (f"{c} → [bold]{escape(e['result']['status'])}[/] · model {escape(model_of(e))} · tokens {escape(str(e.get('tokens')))}"
                + (f"\n[red]scheduling-agent (A2A) unreachable: {escape(down)}[/]" if down else ""))
    if a == "failed":
        return f"{c} → FAILED: {s.get('error', '')} · model {escape(model_of(e))}"
    if a in ("approved", "rejected"):
        return f"{c} → {a} by {who} ({s.get('proposal_id', '')})"
    if a == "served":
        extra = {k: e[k] for k in ("samples_at_risk", "flags") if k in e and e[k] not in (None, [])}
        return f"{c} → served {escape(str(extra)) if extra else ''}".rstrip()
    return f"{c} → {escape(a)} {s.get('proposal_id', '')}"


def tree(events: list[dict]) -> Tree:
    """One line per decision; consecutive data-product reads collapse into one 'data seen' line."""
    t, reads = Tree(f"trace {escape(events[0]['trace'])}"), []

    def flush():
        if reads:
            counts = defaultdict(set)
            for r in reads:
                counts[r.split("-")[0]].add(r)
            t.add("[dim]data products → " + escape("  ".join(f"{k} {', '.join(sorted(v)) if len(v) <= 3 else f'×{len(v)}'}" for k, v in counts.items())) + "[/]")
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
    q = next((e for e in events if e["action"] == "question"), {})
    outcome = next((e for e in events if e["component"] == "triage-agent" and e["action"] in ("answered", "denied", "failed")), None)
    result = (outcome or {}).get("result", {})
    seen = defaultdict(set)
    for e in events:
        for r in e.get("records", []):
            seen[r.split("-")[0]].add(r)
    if outcome is None:
        decision = "—"
    elif outcome["action"] == "failed":
        decision = f"failed: {outcome.get('error')}"
    else:
        decision = result.get("status", "—") + (f" ({result['denial']['reason']} @ {result['denial']['enforced_at']})" if "denial" in result else "")
    approval = next((e for e in events if e["action"] in ("approved", "rejected")), None)
    rows = [("User", q.get("user", "n/a")), ("Agent", f"{q['agent']} v{q['agent_version']}, acting for {q['user']}" if q else "n/a"),
            ("What it saw", "  ".join(f"{k}: {len(v)}" for k, v in sorted(seen.items())) or "—"),
            ("Which model", model_of(outcome) if outcome and outcome["action"] != "denied" else "— (stopped before the model)" if outcome else "—"),
            ("Decision", decision),
            ("Parts", ", ".join(p["part_number"] for p in result.get("parts", [])) or "—"),
            ("Flags", ", ".join(result.get("flags", [])) or "—"),
            ("Approval", f"{approval['action']} by {approval['user']}" if approval else "pending" if result.get("approval") else "—")]
    table = Table.grid(padding=(0, 2))
    for k, v in rows:
        table.add_row(f"[bold]{k}[/]", escape(str(v)))
    return Panel(table, title="Audit card", expand=False)


def live(e: dict, evals: set) -> None:
    """One event of the live stream. Eval runs are folded: their 30 cases stay quiet, their promotion line shows."""
    if e["action"] == "question" and e.get("eval_case"):
        evals.add(e["trace"])
    if e["trace"] in evals:
        return
    if e["action"] == "question":
        console.rule(f"[dim]trace {escape(e['trace'])}[/]")
    if e["action"] == "read":
        recs = defaultdict(list)
        for r in e.get("records", []):
            recs[r.split("-")[0]].append(r)
        text = "[dim]" + escape(f"{e['component']} → " + "  ".join(" ".join(v) if len(v) <= 3 else f"{k} ×{len(v)}" for k, v in recs.items())) + "[/]"
    elif e["action"] == "promotion":
        ok = e["decision"] == "certified"
        gates = "  ".join(f"{g} {'PASS' if not r['failed'] else 'FAIL ' + str(len(r['failed']))}" for g, r in e.get("gates", {}).items())
        text = f"[{'bold green' if ok else 'bold red'}]evals → {'CERTIFIED' if ok else 'BLOCKED'}: {escape(e['candidate'])} · {escape(gates)}[/]"
    else:
        text = f"[{COLOR.get(e['action'], 'white')}]{line(e)}[/]"
    console.print(f"[dim]{escape(e['ts'][11:19])}[/] {text}")
    for fix in e.get("self_corrections") or []:
        console.print(f"[yellow]         self-corrected: {escape('; '.join(fix))[:150]}[/]")


def follow(poll: float = 0.3) -> None:
    """Tail the audit log from now on. Bytes, not text, so a half-written line from another container waits for its end."""
    pos, buf, evals = audit.LOG.stat().st_size if audit.LOG.exists() else 0, b"", set()
    console.print("[dim]live audit stream: waiting for events (Ctrl+C to stop)[/]")
    while True:
        size = audit.LOG.stat().st_size if audit.LOG.exists() else 0
        if size < pos:  # log rotated or cleared
            pos, buf = 0, b""
        if size > pos:
            with open(audit.LOG, "rb") as f:
                f.seek(pos)
                buf += f.read()
                pos = f.tell()
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                try:
                    live(json.loads(raw), evals)
                except (json.JSONDecodeError, KeyError):
                    continue
        time.sleep(poll)


def registry() -> None:
    """SC5: each agent's manifest, the tier computed from it (R-RSK-1), the tier it is certified for, and whether it runs."""
    table = Table(title="Registry: computed vs certified tier (R-RSK-1)")
    for col in ("Agent", "Owner", "Manifest", "Computed", "Certified", "Runs?"):
        table.add_column(col)
    for name, a in badges.registry().items():
        computed = computed_tier(a["manifest"])
        runs = computed <= a["certified_tier"]  # same rule the triage harness applies at run start
        table.add_row(f"{name} v{a['version']}", a["owner"], "\n".join(f"{s} (T{skill_tier(s)})" for s in a["manifest"]),
                      f"T{computed}", f"T{a['certified_tier']}", "[green]yes[/]" if runs else "[red]no — denied until promoted[/]")
    console.print(table)


def promotions() -> None:
    table = Table(title="Promotion decisions, last 8 (R-CRT-1)")
    for col in ("When", "Candidate", "G1", "G2", "G3", "Decision"):
        table.add_column(col)
    for e in [e for e in audit.read() if e["action"] == "promotion"][-8:]:
        cells = []
        for g in ("G1", "G2", "G3"):
            failed = e.get("gates", {}).get(g, {}).get("failed", [])
            cells.append("[green]PASS[/]" if not failed else f"[red]FAIL ({len(failed)})[/]")
        table.add_row(e["ts"], escape(e["candidate"]), *cells, "[green]CERTIFIED[/]" if e["decision"] == "certified" else "[red]BLOCKED[/]")
    console.print(table)


def show_trace(trace: str | None = None, raw: bool = False) -> None:
    """SC6: the trace tree and audit card of one question (default: the last one asked)."""
    trace = trace or next((e["trace"] for e in reversed(audit.read()) if e["action"] == "question"), None)
    events = audit.read(trace) if trace else []
    if not events:
        raise SystemExit("audit log is empty" if not trace else f"no such trace: {trace}")
    if raw:
        for e in events:
            console.print_json(json.dumps(e, ensure_ascii=False))
    else:
        console.print(tree(events))
        console.print(card(events))
