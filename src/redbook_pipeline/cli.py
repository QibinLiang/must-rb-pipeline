"""CLI entry point using Typer."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import load_settings
from .pipeline import Pipeline, SKILL_REGISTRY

app = typer.Typer(name="redbook", help="📹 Paper introduction video generation pipeline")
console = Console()


@app.command()
def run(
    pdf: Path = typer.Argument(..., help="Input PDF file path"),
    output_dir: Path = typer.Option(Path("outputs"), "-o", "--output", help="Output directory"),
    job_id: Optional[str] = typer.Option(None, "--job-id", help="Custom job ID"),
    from_step: Optional[str] = typer.Option(None, "--from", help="Resume from specific step"),
    only: Optional[str] = typer.Option(None, "--only", help="Run only one step (for debugging)"),
    force: bool = typer.Option(False, "-f", "--force", help="Force re-run"),
):
    """Run the full pipeline: PDF -> PPT + Video."""
    settings = load_settings()
    pipeline = Pipeline(settings=settings, output_base=output_dir)
    result = pipeline.run(
        pdf_path=pdf,
        job_id=job_id,
        start_from=from_step,
        only=only,
        force=force,
    )
    console.print(f"\n✅ [bold green]Done! Output: {result}[/bold green]")


@app.command()
def resume(
    job_id: str = typer.Argument(..., help="Job ID to resume"),
    from_step: Optional[str] = typer.Option(None, "--from", help="Resume from specific step"),
    force: bool = typer.Option(False, "-f", "--force", help="Force re-run"),
):
    """Resume a previously interrupted pipeline."""
    settings = load_settings()
    pipeline = Pipeline(settings=settings)

    # Load metadata to get pdf_path
    import json
    meta_path = Path("outputs") / job_id / "00_meta.json"
    if not meta_path.exists():
        console.print(f"❌ [red]Job not found: {job_id}[/red]")
        raise typer.Exit(1)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pdf_path = Path(meta["pdf_path"])

    result = pipeline.run(
        pdf_path=pdf_path,
        job_id=job_id,
        start_from=from_step,
        force=force,
    )
    console.print(f"\n✅ [bold green]Resumed job complete! Output: {result}[/bold green]")


@app.command()
def status(job_id: str = typer.Argument(..., help="Job ID to check")):
    """Check the status of each step for a job."""
    work_dir = Path("outputs") / job_id
    if not work_dir.exists():
        console.print(f"❌ [red]Job not found: {job_id}[/red]")
        raise typer.Exit(1)

    table = Table(title=f"Job Status: {job_id}")
    table.add_column("Step", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Output", style="dim")

    for skill_name in SKILL_REGISTRY:
        skill_cls = SKILL_REGISTRY[skill_name]
        skill = skill_cls(job_id=job_id, work_dir=work_dir, config={})
        done = skill.is_done()
        status_str = "✅ Done" if done else "⏳ Pending"
        output_name = skill.output_path.name if done else "-"
        table.add_row(skill_name, status_str, output_name)

    console.print(table)


@app.command()
def list_jobs():
    """List all jobs in the output directory."""
    output_dir = Path("outputs")
    if not output_dir.exists():
        console.print("No jobs found.")
        return

    table = Table(title="Jobs")
    table.add_column("Job ID", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Created", style="dim")

    for job_dir in sorted(output_dir.iterdir()):
        if not job_dir.is_dir() or job_dir.name.startswith("."):
            continue
        meta_path = job_dir / "00_meta.json"
        status = "unknown"
        created = "-"
        if meta_path.exists():
            import json
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            status = meta.get("status", "unknown")
            created = meta.get("created_at", "-")[:19]
        table.add_row(job_dir.name, status, created)

    console.print(table)


def main():
    app()


if __name__ == "__main__":
    main()
