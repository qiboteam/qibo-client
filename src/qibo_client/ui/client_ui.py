import tabulate
from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..config_logging import logger
from .settings import USE_RICH_UI, console

# =====================================================================
# RENDER HELPERS (module-level, not class methods)
# =====================================================================


def _quota_rows_from_payload(projectquotas: list[dict]) -> list[tuple]:
    return [
        (
            t["project"],
            t["partition"]["name"],
            t["partition"]["max_num_qubits"],
            t["partition"]["hardware_type"],
            t["partition"]["description"],
            t["partition"]["status"],
            t["seconds_left"],
            t["shots_left"],
            t["jobs_left"],
        )
        for t in projectquotas
    ]


def _jobs_rows_from_payload(jobs: list[dict], fmt) -> list[tuple]:
    return [
        (
            job["pid"],
            fmt(job["created_at"]),
            fmt(job["updated_at"]),
            job["status"],
            job["result_path"],
        )
        for job in jobs
    ]


# ---------------- Fallback (tabulate) renderers ----------------


def render_quota_fallback(disk_quota: dict, projectquotas: list[dict]) -> None:
    message = (
        f"User: {disk_quota['user']['email']}\n"
        f"Disk quota left [KBs]: {disk_quota['kbs_left']:.2f} / {disk_quota['kbs_max']:.2f}\n"
    )
    rows = _quota_rows_from_payload(projectquotas)
    message += tabulate.tabulate(
        rows,
        headers=[
            "Project Name",
            "Device Name",
            "Qubits",
            "Type",
            "Description",
            "Status",
            "Time Left [s]",
            "Shots Left",
            "Jobs Left",
        ],
    )
    logger.info(message)


def render_jobs_fallback(user: str, jobs: list[dict], fmt) -> None:
    rows = _jobs_rows_from_payload(jobs, fmt)
    message = f"User: {user}\n" + tabulate.tabulate(
        rows, headers=["Pid", "Created At", "Updated At", "Status", "Results"]
    )
    logger.info(message)


# ---------------- Rich renderers ----------------


def render_quota_rich(disk_quota: dict, projectquotas: list[dict]) -> None:
    used = disk_quota["kbs_max"] - disk_quota["kbs_left"]
    quota_text = (
        f"[bold cyan]User:[/bold cyan] {disk_quota['user']['email']}\n"
        f"[bold cyan]Disk quota used:[/bold cyan] {used:.2f} KB / {disk_quota['kbs_max']:.2f} KB"
    )

    table = Table(
        title="Project Quotas",
        show_header=True,
        header_style="bold magenta",
        box=box.SIMPLE_HEAVY,
        title_style="bold green",
    )
    table.add_column("Project", style="cyan")
    table.add_column("Device", style="yellow")
    table.add_column("Qubits", justify="right")
    table.add_column("Type", style="bold")
    table.add_column("Description", overflow="fold")
    table.add_column("Status", style="bold")
    table.add_column(Text("Time Left [s]"), justify="right")
    table.add_column("Shots Left", justify="right")
    table.add_column("Jobs Left", justify="right")

    for t in projectquotas:
        status = t["partition"]["status"]
        status_color = "green" if status == "available" else "red"
        table.add_row(
            t["project"],
            t["partition"]["name"],
            str(t["partition"]["max_num_qubits"]),
            t["partition"]["hardware_type"],
            t["partition"]["description"],
            f"[{status_color}]{status}[/{status_color}]",
            f"{t['seconds_left']:.0f}",
            str(t["shots_left"]),
            str(t["jobs_left"]),
        )

    panel = Panel(table, title="Quota Information", subtitle=quota_text, expand=False)
    console.print(panel)


def render_jobs_rich(user: str, jobs: list[dict], fmt) -> None:
    table = Table(
        title=f"Jobs for {user}",
        show_header=True,
        header_style="bold magenta",
        box=box.SIMPLE_HEAVY,
        title_style="bold green",
    )
    table.add_column("PID", style="cyan", overflow="fold")
    table.add_column("Created At", style="yellow")
    table.add_column("Updated At", style="yellow")
    table.add_column("Status", style="bold")
    table.add_column("Results", overflow="fold")

    for job in jobs:
        status_color = "green" if job["status"] == "success" else "red"
        table.add_row(
            job["pid"],
            fmt(job["created_at"]),
            fmt(job["updated_at"]),
            f"[{status_color}]{job['status']}[/{status_color}]",
            job["result_path"],
        )

    panel = Panel(table, title="Job Information", expand=False)
    console.print(panel)


# ---------------- Renderers ----------------


def render_quota(disk_quota: dict, projectquotas: list[dict]) -> None:
    if USE_RICH_UI:
        render_quota_rich(disk_quota, projectquotas)
    else:
        render_quota_fallback(disk_quota, projectquotas)


def render_jobs(user: str, jobs: list[dict], fmt) -> None:
    if USE_RICH_UI:
        render_jobs_rich(user, jobs, fmt)
    else:
        render_jobs_fallback(user, jobs, fmt)
