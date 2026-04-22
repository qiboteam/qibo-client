"""UI rendering functions for quota and job information.

This module provides functions for rendering quota information and job lists
using tabulate and Rich UI components.
"""

import tabulate
from rich import box
from rich.panel import Panel
from rich.table import Table

from .settings import USE_RICH_UI, console


def _quota_rows(projectquotas: list[dict]) -> list[tuple]:
    """Extract quota details into a flat tuple format for table rendering.

    Args:
        projectquotas: List of project quota dictionaries

    Returns:
        List of tuples containing quota details
    """
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


def _jobs_rows(jobs: list[dict], fmt) -> list[tuple]:
    """Extract job details into a flat tuple format for table rendering.

    Args:
        jobs: List of job dictionaries
        fmt: Function to format datetime strings

    Returns:
        List of tuples containing job details
    """
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


def render_quota(disk_quota: dict, projectquotas: list[dict]) -> None:
    """Render quota information using Rich UI or fallback logging.

    Args:
        disk_quota: Disk quota information dictionary
        projectquotas: List of project quota dictionaries
    """
    if not USE_RICH_UI:
        from ..config_logging import logger

        msg = (
            f"User: {disk_quota['user']['email']}\n"
            f"Disk quota left [KBs]: {disk_quota['kbs_left']:.2f} / {disk_quota['kbs_max']:.2f}\n"
        )
        msg += tabulate.tabulate(
            _quota_rows(projectquotas),
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
        logger.info(msg)
        return

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
    for col in [
        "Project",
        "Device",
        "Qubits",
        "Type",
        "Description",
        "Status",
        "Time Left [s]",
        "Shots Left",
        "Jobs Left",
    ]:
        table.add_column(col)

    for t in projectquotas:
        p = t["partition"]
        status_color = "green" if p["status"] == "available" else "red"
        table.add_row(
            t["project"],
            p["name"],
            str(p["max_num_qubits"]),
            p["hardware_type"],
            p["description"] or "-",
            f"[{status_color}]{p['status']}[/{status_color}]",
            f"{t['seconds_left']:.0f}",
            str(t["shots_left"]),
            str(t["jobs_left"]),
        )

    console.print(
        Panel(table, title="Quota Information", subtitle=quota_text, expand=False)
    )


def render_jobs(user: str, jobs: list[dict], fmt) -> None:
    """Render job information using Rich UI or fallback logging.

    Args:
        user: Email address of the user
        jobs: List of job dictionaries
        fmt: Function to format datetime strings
    """
    if not USE_RICH_UI:
        from ..config_logging import logger

        msg = f"User: {user}\n" + tabulate.tabulate(
            _jobs_rows(jobs, fmt),
            headers=["Pid", "Created At", "Updated At", "Status", "Results"],
        )
        logger.info(msg)
        return

    table = Table(
        title=f"Jobs for {user}",
        show_header=True,
        header_style="bold magenta",
        box=box.SIMPLE_HEAVY,
        title_style="bold green",
    )
    for col in ["PID", "Created At", "Updated At", "Status", "Results"]:
        table.add_column(col)

    for job in jobs:
        color = "green" if job["status"] == "success" else "red"
        table.add_row(
            job["pid"],
            fmt(job["created_at"]),
            fmt(job["updated_at"]),
            f"[{color}]{job['status']}[/{color}]",
            job["result_path"] or "-",
        )

    console.print(Panel(table, title="Job Information", expand=False))
