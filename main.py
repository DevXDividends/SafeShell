"""
main.py — CLI ENTRYPOINT
Ye file saare modules ko jodta hai: interceptor -> simulator -> ai_planner
-> risk_scorer -> checkpoint -> executor -> db, aur "safeshell history" /
"safeshell undo" commands deta hai.

Ye ab COMPLETE pipeline hai — sabhi 8 modules connected: koi placeholder
logic nahi bacha.
"""

import os

import typer
from rich.console import Console
from rich.table import Table

import db
from interceptor import parse_command
from risk_scorer import score_risk
from models import ImpactReport
from simulator import simulate, SimulationError
from ai_planner import generate_undo_plan
from checkpoint import create_checkpoint
from executor import execute_command
from rollback import rollback as do_rollback


def _get_simulation_root(targets: list) -> str | None:
    """
    Simulation ek DIRECTORY pe overlay mount karke hoti hai (single file pe nahi).
    Isliye agar target ek file hai, uska parent folder use karo.
    Multiple targets hone pe, sabka common parent nikaalo.
    """
    dirs = []
    for t in targets:
        abs_t = os.path.abspath(t)
        if os.path.isdir(abs_t):
            dirs.append(abs_t)
        elif os.path.exists(abs_t):
            dirs.append(os.path.dirname(abs_t))
        # Agar path exist hi nahi karta (naya file jo banega), skip karo
    if not dirs:
        return None
    common = os.path.commonpath(dirs)
    return common if os.path.isdir(common) else None

app = typer.Typer()
console = Console()


@app.command()
def run(command: str = typer.Argument(..., help="The command to run, e.g. 'rm -rf test'")):
    """
    Ek command ko SafeShell ke through chalao.
    Usage: python3 main.py run "rm -rf test_folder"
    """
    db.init_db()
    parsed = parse_command(command)

    if not parsed.is_risky:
        # Risky nahi hai, seedha chala do — bina extra drama ke
        console.print(f"[dim]Not a tracked risky command, running directly...[/dim]")
        result = execute_command(command)
        console.print(result.stdout)
        if result.stderr:
            console.print(f"[red]{result.stderr}[/red]")
        return

    # ── REAL SIMULATION (OverlayFS dry-run) ──
    sim_root = _get_simulation_root(parsed.targets)
    impact = None

    if sim_root:
        console.print(f"[dim]🔍 Simulating on {sim_root} (dry-run, real files untouched)...[/dim]")
        try:
            impact = simulate(parsed.raw, sim_root)
        except SimulationError as e:
            console.print(f"[yellow]⚠️  Simulation unavailable ({e}). Falling back to basic estimate.[/yellow]")

    if impact is None:
        # Fallback: agar simulation na chal paaye (naya file, ya sudo/overlay unavailable)
        impact = ImpactReport(
            files_deleted=len(parsed.targets) if parsed.category == "delete" else 0,
            files_modified=len(parsed.targets) if parsed.category != "delete" else 0,
            system_paths_touched=1 if parsed.touches_system_path else 0,
        )

    risk = score_risk(impact)

    console.print(f"\n[bold]⚠️  RISK ANALYSIS[/bold]")
    console.print(f"Command: {parsed.raw}")
    console.print(f"Category: {parsed.category}")
    level_color = {"CRITICAL": "red", "HIGH": "red", "MEDIUM": "yellow", "LOW": "green"}[risk["level"]]
    console.print(f"Risk Level: [{level_color}]{risk['level']}[/{level_color}] (score: {risk['score']})")
    for reason in risk["reasons"]:
        console.print(f"  - {reason}")
    if impact.affected_paths:
        console.print(f"[dim]Affected paths: {', '.join(impact.affected_paths[:5])}"
                       f"{' ...' if len(impact.affected_paths) > 5 else ''}[/dim]")

    confirmed = typer.confirm("\nProceed?")
    if not confirmed:
        console.print("[yellow]Cancelled.[/yellow]")
        raise typer.Exit()

    # ── AI/Rule-based Undo Plan (Module 3) ──
    # Simple commands -> instant rule-based plan. Compound commands (&&, ;, |) ->
    # Groq (if key set) -> Ollama (if available + user consents) -> heuristic fallback.
    undo_plan = generate_undo_plan(parsed, impact, risk["level"])
    backend = undo_plan.pop("_backend", "heuristic")
    console.print(f"[dim]🧩 Undo plan generated via [bold]{backend}[/bold] "
                   f"({len(undo_plan.get('undo_steps', []))} step(s))[/dim]")

    # ── Checkpoint lo (existing paths ka) ──
    snapshot_id = create_checkpoint(parsed.targets)
    console.print(f"[dim]📸 Checkpoint created (id: {snapshot_id})[/dim]")

    # ── DB me transaction record karo (pending) ──
    txn_id = db.create_transaction(
        command=parsed.raw,
        risk_level=risk["level"],
        risk_score=risk["score"],
        snapshot_path=snapshot_id,
        undo_plan=undo_plan,
    )

    # ── Real execution ──
    console.print("[dim]▶️  Executing...[/dim]")
    result = execute_command(parsed.raw)
    db.update_execution_status(txn_id, "success" if result.success else "failed")

    if result.success:
        console.print(f"[green]✅ Done. Transaction #{txn_id} logged.[/green]")
    else:
        console.print(f"[red]❌ Command failed. Transaction #{txn_id} logged as failed.[/red]")
        console.print(f"[red]{result.stderr}[/red]")


@app.command()
def history(limit: int = typer.Option(20, help="How many recent transactions to show")):
    """Past transactions dikhao. Usage: python3 main.py history"""
    db.init_db()
    rows = db.get_history(limit)

    if not rows:
        console.print("[dim]No transactions yet.[/dim]")
        return

    table = Table(title="SafeShell Transaction History")
    table.add_column("ID", style="cyan")
    table.add_column("Command")
    table.add_column("Risk")
    table.add_column("Status")
    table.add_column("Rolled Back")

    for row in rows:
        table.add_row(
            str(row["id"]),
            row["command"],
            row["risk_level"] or "-",
            row["execution_status"] or "-",
            "yes" if row["rolled_back"] else "no",
        )
    console.print(table)


@app.command()
def undo(transaction_id: int = typer.Argument(..., help="Transaction ID to undo")):
    """Ek transaction ko undo/rollback karo. Usage: python3 main.py undo 3"""
    db.init_db()
    console.print(f"[dim]🔄 Rolling back transaction #{transaction_id}...[/dim]")
    result = do_rollback(transaction_id)

    if result["success"]:
        console.print(f"[green]✅ {result['message']}[/green]")
    else:
        console.print(f"[red]❌ {result['message']}[/red]")


if __name__ == "__main__":
    app()