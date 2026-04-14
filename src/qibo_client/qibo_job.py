import importlib.metadata as im
import time
import typing as T
from enum import Enum

import qibo
from rich.live import Live

version = im.version(__package__)

from . import constants
from .config_logging import logger
from .ui.job_frontend import (
    LiveOuter,
    UISlots,
    build_final_banner,
    build_status_panel,
    log_status_non_tty,
)
from .ui.settings import USE_RICH_UI, console
from .utils import QiboApiRequest


# -----------------------------
# Helpers
# -----------------------------
def convert_str_to_job_status(status: str):
    return next((s for s in QiboJobStatus if s.value == status), None)


class QiboJobStatus(Enum):
    QUEUEING = "queueing"
    PENDING = "pending"
    RUNNING = "running"
    POSTPROCESSING = "postprocessing"
    SUCCESS = "success"
    ERROR = "error"


# -----------------------------
# QiboJob
# -----------------------------
class QiboJob:
    def __init__(
        self,
        pid: str,
        base_url: str,
        headers: T.Dict[str, str] | None = None,
        circuit: T.Optional[qibo.Circuit] = None,
        nshots: T.Optional[int] = None,
        device: T.Optional[str] = None,
    ):
        self.base_url = base_url
        self.headers = headers
        self.pid = pid
        self.circuit = circuit
        self.nshots = nshots
        self.device = device

        self._status: T.Optional[QiboJobStatus] = None
        # convenience fields (populated on refresh/status)
        self.queue_position: T.Optional[int] = None
        self.seconds_to_job_start: T.Optional[int | float] = None
        self.queue_last_update: T.Optional[str] = None

        self._preamble: T.Optional[object] = None

    # ---- server I/O ----
    def _snapshot(self) -> T.Dict:
        """Fetch current job snapshot from the webapp."""
        url = self.base_url + f"/api/jobs/{self.pid}/"
        resp = QiboApiRequest.get(
            url,
            headers=self.headers,
            timeout=constants.TIMEOUT,
            keys_to_check=["status"],
        )
        return resp.json()

    def refresh(self):
        """Refreshes job information from server (no results download)."""
        info = self._snapshot()
        if info:
            self._update_job_info(info)

    def _update_job_info(self, info: T.Dict):
        self.circuit = info.get("circuit")
        self.nshots = info.get("nshots")
        pq = info.get("projectquota") or {}
        part = pq.get("partition") or {}
        self.device = part.get("name", self.device)
        self._status = convert_str_to_job_status(info["status"])

        # live queue info
        self.queue_position = info.get("queue_position")
        self.seconds_to_job_start = info.get("etd_seconds")
        self.queue_last_update = info.get("queue_last_update")

    # ---- convenience ----
    def status(self) -> QiboJobStatus:
        info = self._snapshot()
        self._status = convert_str_to_job_status(info["status"])
        self.queue_position = info.get("queue_position", info.get("job_queue_position"))
        self.seconds_to_job_start = info.get(
            "etd_seconds", info.get("seconds_to_job_start")
        )
        self.queue_last_update = info.get("queue_last_update")
        return self._status

    def running(self) -> bool:
        if self._status is None:
            self.refresh()
        return self._status is QiboJobStatus.RUNNING

    def success(self) -> bool:
        if self._status is None:
            self.refresh()
        return self._status is QiboJobStatus.SUCCESS

    # ---- main wait loop ----
    def result(
        self, wait: float = 0.5, verbose: bool = True
    ) -> T.Optional[qibo.result.QuantumState]:
        """Poll server until completion, then reconstruct result from snapshot data."""
        snapshot, job_status = self._wait_for_response_to_get_request(wait, verbose)

        if job_status == QiboJobStatus.ERROR:
            logger.error(
                "Job exited with error\n\nStdout:\n%s\n\nStderr:\n%s",
                snapshot.get("stdout", "-"),
                snapshot.get("stderr", "-"),
            )
            return None

        circuit = qibo.Circuit.from_dict(snapshot["circuit"])
        frequencies = snapshot.get("frequencies")
        if circuit.measurements:
            qubits = circuit.measurements[-1].qubits
            return qibo.result.MeasurementOutcomes.from_frequencies(
                frequencies, qubits=qubits, nqubits=circuit.nqubits
            )
        return qibo.result.MeasurementOutcomes.from_frequencies(
            frequencies, nqubits=circuit.nqubits
        )

    def _wait_for_response_to_get_request(
        self, seconds_between_checks: T.Optional[int] = None, verbose: bool = True
    ) -> T.Tuple[T.Dict, QiboJobStatus]:
        """Poll the job until completion; return (download_response, final_status)."""
        if seconds_between_checks is None:
            seconds_between_checks = constants.SECONDS_BETWEEN_CHECKS

        # Gentle hint when not verbose
        is_job_unfinished = self.status() not in (
            QiboJobStatus.SUCCESS,
            QiboJobStatus.ERROR,
        )
        if not verbose and is_job_unfinished:
            logger.info("Please wait until your job is completed...")

        url = self.base_url + f"/api/jobs/{self.pid}/"
        # Only show Rich Live in an interactive TTY or Jupyter with ipywidgets.
        use_live = verbose and USE_RICH_UI

        # Render policy: don't update during POSTPROCESSING so previous panel stays visible
        def _render(status: QiboJobStatus, qpos, etd):
            if status == QiboJobStatus.POSTPROCESSING:
                return None
            return build_status_panel(status.name, qpos, etd)

        # Small wrapper to fetch status + live fields
        def _fetch_snapshot() -> (
            tuple[QiboJobStatus, T.Optional[int], T.Optional[int | float], T.Dict]
        ):
            payload = QiboApiRequest.get(
                url, headers=self.headers, timeout=constants.TIMEOUT
            ).json()
            status = convert_str_to_job_status(payload["status"])
            qpos = payload.get("queue_position", payload.get("job_queue_position"))
            etd = payload.get("etd_seconds", payload.get("seconds_to_job_start"))
            return status, qpos, etd, payload

        # --- Live (TTY) branch ---
        if use_live:
            status0, qpos0, etd0, _ = _fetch_snapshot()

            # Compose a single renderable from named slots.
            # You can add more slots later (e.g., "header", "footer") without changing Live plumbing.
            ui = UISlots(order=("header", "status", "footer"))
            title = f"Qibo client version {version}"
            ui.set("header", self._preamble)
            ui.set("status", build_status_panel(status0.name, qpos0, etd0))

            outer = LiveOuter(title, ui)

            with Live(
                outer,
                refresh_per_second=12,
                console=console,
                transient=False,
                vertical_overflow="visible",
            ) as live:
                start_ts = time.perf_counter()
                while True:
                    job_status, qpos, etd, payload = _fetch_snapshot()

                    renderable = _render(job_status, qpos, etd)
                    if renderable is not None:
                        # Swap the status slot in place
                        ui.set("status", renderable)
                        live.refresh()

                    if job_status in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
                        elapsed = time.perf_counter() - start_ts

                        # Replace the status slot with a compact final banner
                        ui.set(
                            "status",
                            build_final_banner(
                                job_status.name,
                                pid=self.pid,
                                device=self.device,
                                elapsed_seconds=elapsed,
                            ),
                        )
                        live.refresh()
                        return payload, job_status

                    time.sleep(seconds_between_checks)

        last_status: T.Optional[str] = None
        printed_pending_with_info = False

        if verbose and is_job_unfinished:
            logger.info("🚀 Starting qibo client...")
            logger.info("📬 Job posted on %s with pid, %s", self.device, self.pid)

        while True:
            job_status, qpos, etd, payload = _fetch_snapshot()

            # controlled, non-spam logging (prints each status once; PENDING upgraded once)
            last_status, printed_pending_with_info = log_status_non_tty(
                verbose=verbose,
                last_status=last_status,
                printed_pending_with_info=printed_pending_with_info,
                job_status=job_status.name,
                qpos=qpos,
                etd=etd,
            )

            if job_status in (QiboJobStatus.SUCCESS, QiboJobStatus.ERROR):
                if verbose:
                    logger.info("Job COMPLETED")
                return payload, job_status

            time.sleep(seconds_between_checks)

    def delete(self) -> str:
        url = self.base_url + f"/api/jobs/{self.pid}/"
        response = QiboApiRequest.delete(
            url, headers=self.headers, timeout=constants.TIMEOUT
        )
        return response
