import tarfile
from contextlib import contextmanager
from pathlib import Path

import fixs
import jsf
import pytest
import responses
import utils_test_qibo_client as utils

from qibo_client import QiboJobStatus, exceptions, qibo_job

ARCHIVE_NAME = "file.tar.gz"


@pytest.mark.parametrize(
    "status, expected_result",
    [
        ("queueing", QiboJobStatus.QUEUEING),
        ("pending", QiboJobStatus.PENDING),
        ("running", QiboJobStatus.RUNNING),
        ("postprocessing", QiboJobStatus.POSTPROCESSING),
        ("success", QiboJobStatus.SUCCESS),
        ("error", QiboJobStatus.ERROR),
        ("done", None),
        ("invalid", None),
    ],
)
def test_convert_str_to_job_status(status, expected_result):
    result = qibo_job.convert_str_to_job_status(status)
    assert result == expected_result


@pytest.fixture
def archive_path(monkeypatch, tmp_path: Path):
    archive_path = tmp_path / ARCHIVE_NAME

    @contextmanager
    def mock_named_tmp(delete: bool = False):
        io_stream = archive_path.open("wb")
        try:
            yield io_stream
        finally:
            io_stream.close()

    monkeypatch.setattr(
        "qibo_client.qibo_job.tempfile.NamedTemporaryFile", mock_named_tmp
    )
    return archive_path


def test__write_stream_to_tmp_file_with_simple_text_stream(
    archive_path, tmp_path: Path
):
    """
    The test contains the following checks:

    - a new temporary file is created to a specific direction
    - the content of the temporary file contains equals the one given
    """
    stream = [b"line1\n", b"line2\n"]

    assert not archive_path.is_file()

    result_path = qibo_job._write_stream_to_tmp_file(stream)

    assert result_path == archive_path
    assert result_path.is_file()
    assert result_path.read_bytes() == b"".join(stream)


def test__write_stream_to_tmp_file_with_archive(archive_path: Path):
    """
    The test contains the following checks:

    - a new temporary archive is created to a specific direction
    - load the archive in memory and check that the members and the contents
    match with the expected ones
    """
    stream, members, members_contents = utils.get_in_memory_fake_archive_stream()

    assert not archive_path.is_file()

    result_path = qibo_job._write_stream_to_tmp_file(stream)

    assert result_path == archive_path
    assert result_path.is_file()

    with tarfile.open(result_path, "r:gz") as archive:
        result_members = sorted(archive.getnames())
        assert result_members == members
        for member, member_content in zip(members, members_contents):
            with archive.extractfile(member) as result_member:
                result_content = result_member.read()
            assert result_content == member_content


def test__extract_archive_to_folder_with_non_archive_input(tmp_path):
    file_path = tmp_path / "file.txt"
    file_path.write_text("test content")

    with pytest.raises(tarfile.ReadError):
        qibo_job._extract_archive_to_folder(file_path, tmp_path)


def test__extract_archive_to_folder_with_success(monkeypatch, tmp_path: Path):
    results_base_folder = tmp_path / "results"
    results_base_folder.mkdir()
    archive_path = tmp_path / ARCHIVE_NAME
    monkeypatch.setattr(
        "qibo_client.qibo_job.constants.RESULTS_BASE_FOLDER", results_base_folder
    )
    members, members_contents = utils.create_fake_archive(archive_path)

    qibo_job._extract_archive_to_folder(archive_path, results_base_folder)

    result_members = []
    result_members_contents = []
    for member_path in sorted(results_base_folder.iterdir()):
        result_members.append(member_path.name)
        result_members_contents.append(member_path.read_bytes())

    assert result_members == members
    assert result_members_contents == members_contents


def test__save_and_unpack_stream_response_to_folder(monkeypatch, tmp_path: Path):
    results_base_folder = tmp_path / "results"
    results_base_folder.mkdir()
    archive_path = tmp_path / ARCHIVE_NAME
    monkeypatch.setattr(
        "qibo_client.qibo_job.constants.RESULTS_BASE_FOLDER", results_base_folder
    )

    stream, _, _ = utils.get_in_memory_fake_archive_stream()

    assert not archive_path.is_file()

    qibo_job._save_and_unpack_stream_response_to_folder(stream, results_base_folder)

    # the archive should have been removed
    assert not archive_path.is_file()


FAKE_PID = "fakePid"
FAKE_URL = "http://fake.endpoint.com"
FAKE_CIRCUIT = "fakeCircuit"
FAKE_NSHOTS = 10
FAKE_DEVICE = "fakeDevice"
FAKE_NUM_QUBITS = 8
FAKE_HARDWARE_TYPE = "fakeHardwareType"
FAKE_DESCRIPTION = "fakeDescription"
FAKE_STATUS = "fakeStatus"
BASE_JOB_STATUS = QiboJobStatus.SUCCESS
BASE_JOB_STATUS_STR = "success"
FAKE_RESULT = "fakeResult"


class TestQiboJob:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        self.obj = qibo_job.QiboJob(FAKE_PID, FAKE_URL)
        yield

    @pytest.fixture
    @responses.activate
    def refresh_job(self):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = jsf.JSF(fixs.JOB_SCHEMA).generate()
        response_json["circuit"] = FAKE_CIRCUIT
        response_json["nshots"] = FAKE_CIRCUIT
        response_json.update(
            {
                "circuit": FAKE_CIRCUIT,
                "nshots": FAKE_NSHOTS,
                "status": BASE_JOB_STATUS_STR,
            }
        )
        response_json["projectquota"]["partition"].update(
            {
                "name": FAKE_DEVICE,
                "max_num_qubits": FAKE_NUM_QUBITS,
                "hardware_type": FAKE_HARDWARE_TYPE,
                "description": None,
                "status": FAKE_STATUS,
            }
        )
        responses.add(responses.GET, endpoint, status=200, json=response_json)
        self.obj.refresh()

    def test_init_method(self):
        assert self.obj.pid == FAKE_PID
        assert self.obj.base_url == FAKE_URL
        assert self.obj.circuit is None
        assert self.obj.nshots is None
        assert self.obj.device is None
        assert self.obj._status is None

    def test_refresh_with_success(self, refresh_job):
        assert self.obj.circuit == FAKE_CIRCUIT
        assert self.obj.nshots == FAKE_NSHOTS
        assert self.obj.device == FAKE_DEVICE
        assert self.obj._status == BASE_JOB_STATUS

    @responses.activate
    def test_refresh_with_invalid_pid(self):
        invalid_pid = "invalidPid"
        self.obj.pid = invalid_pid
        endpoint = FAKE_URL + f"/api/jobs/{invalid_pid}/"
        response_json = {"detail": f"Invalid job pid, got {invalid_pid}"}
        responses.add(responses.GET, endpoint, status=404, json=response_json)

        with pytest.raises(exceptions.QiboApiError) as err:
            self.obj.refresh()

        assert str(err.value) == response_json["detail"]

    @pytest.mark.parametrize(
        "status, expected_result",
        [
            ("queueing", QiboJobStatus.QUEUEING),
            ("pending", QiboJobStatus.PENDING),
            ("running", QiboJobStatus.RUNNING),
            ("postprocessing", QiboJobStatus.POSTPROCESSING),
            ("success", QiboJobStatus.SUCCESS),
            ("error", QiboJobStatus.ERROR),
        ],
    )
    @responses.activate
    def test_status(self, status, expected_result):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = {"status": status}
        responses.add(responses.GET, endpoint, status=200, json=response_json)

        result = self.obj.status()

        assert result == expected_result

    @pytest.mark.parametrize(
        "status, expected_result",
        [
            (QiboJobStatus.QUEUEING, False),
            (QiboJobStatus.PENDING, False),
            (QiboJobStatus.RUNNING, True),
            (QiboJobStatus.POSTPROCESSING, False),
            (QiboJobStatus.SUCCESS, False),
            (QiboJobStatus.ERROR, False),
        ],
    )
    def test_running_with_cached_results(
        self, status: QiboJobStatus, expected_result: bool
    ):
        self.obj._status = status
        result = self.obj.running()
        assert result == expected_result

    @pytest.mark.parametrize(
        "status, expected_result",
        [
            (QiboJobStatus.QUEUEING, False),
            (QiboJobStatus.PENDING, False),
            (QiboJobStatus.RUNNING, True),
            (QiboJobStatus.POSTPROCESSING, False),
            (QiboJobStatus.SUCCESS, False),
            (QiboJobStatus.ERROR, False),
        ],
    )
    def test_running_without_cached_results(
        self, monkeypatch, status: QiboJobStatus, expected_result: bool
    ):
        assert self.obj._status is None

        def change_obj_status_to():
            self.obj._status = status

        monkeypatch.setattr(self.obj, "refresh", change_obj_status_to)
        result = self.obj.running()
        assert result == expected_result

    @pytest.mark.parametrize(
        "status, expected_result",
        [
            (QiboJobStatus.QUEUEING, False),
            (QiboJobStatus.PENDING, False),
            (QiboJobStatus.RUNNING, False),
            (QiboJobStatus.POSTPROCESSING, False),
            (QiboJobStatus.SUCCESS, True),
            (QiboJobStatus.ERROR, False),
        ],
    )
    def test_success_with_cached_results(
        self, status: QiboJobStatus, expected_result: bool
    ):
        self.obj._status = status
        result = self.obj.success()
        assert result == expected_result

    @pytest.mark.parametrize(
        "status, expected_result",
        [
            (QiboJobStatus.QUEUEING, False),
            (QiboJobStatus.PENDING, False),
            (QiboJobStatus.RUNNING, False),
            (QiboJobStatus.POSTPROCESSING, False),
            (QiboJobStatus.SUCCESS, True),
            (QiboJobStatus.ERROR, False),
        ],
    )
    def test_success_without_cached_results(
        self, monkeypatch, status: QiboJobStatus, expected_result: bool
    ):
        assert self.obj._status is None

        def change_obj_status_to():
            self.obj._status = status

        monkeypatch.setattr(self.obj, "refresh", change_obj_status_to)
        result = self.obj.success()
        assert result == expected_result

    @responses.activate
    def test_result_handles_tarfile_readerror(self, monkeypatch, refresh_job):
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        responses.add(
            responses.GET,
            info_endpoint,
            json={"status": "success"},
            status=200,
        )

        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, endpoint, status=200)

        def raise_tarfile_readerror(*args):
            raise tarfile.ReadError()

        monkeypatch.setattr(
            "qibo_client.qibo_job._save_and_unpack_stream_response_to_folder",
            raise_tarfile_readerror,
        )
        result = self.obj.result()
        assert result is None

    @responses.activate
    def test_result_with_job_status_error(self, monkeypatch, refresh_job):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, endpoint, status=200)

        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = jsf.JSF(fixs.JOB_SCHEMA).generate()
        response_json["status"] = "error"
        responses.add(
            responses.GET,
            info_endpoint,
            json=response_json,
            status=200,
        )

        monkeypatch.setattr(
            "qibo_client.qibo_job._save_and_unpack_stream_response_to_folder",
            lambda *args: "ok",
        )
        result = self.obj.result()
        assert result is None

    @responses.activate
    def test_result_with_job_status_success(self, monkeypatch, refresh_job):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, endpoint, status=200)

        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        responses.add(
            responses.GET,
            info_endpoint,
            json={"status": "success"},
            status=200,
        )

        monkeypatch.setattr(
            "qibo_client.qibo_job._save_and_unpack_stream_response_to_folder",
            lambda *args: "ok",
        )

        monkeypatch.setattr(
            "qibo_client.qibo_job.qibo.result.load_result",
            lambda x: FAKE_RESULT,
        )
        result = self.obj.result()
        assert result == FAKE_RESULT

    @pytest.mark.parametrize(
        "status, expected_job_status",
        [
            ("success", QiboJobStatus.SUCCESS),
            ("error", QiboJobStatus.ERROR),
        ],
    )
    @responses.activate
    def test_wait_for_response_to_get_request_simple(
        self, monkeypatch, caplog, status, expected_job_status
    ):

        monkeypatch.setattr("qibo_client.qibo_job.constants.TIMEOUT", 2)

        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"

        failed_attempts = 3
        for _ in range(failed_attempts):
            responses.add(
                responses.GET,
                info_endpoint,
                status=200,
                json={"status": "running"},
            )

        responses.add(
            responses.GET,
            info_endpoint,
            status=200,
            json={"status": status},
        )

        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        response_json = {"detail": "output"}
        responses.add(
            responses.GET,
            endpoint,
            json=response_json,
            status=200,
        )

        response, job_status = self.obj._wait_for_response_to_get_request(1e-4, False)

        assert job_status == expected_job_status
        assert response.json() == response_json
        assert len(responses.calls) == 1 + failed_attempts + 1

        # first call is to status
        assert responses.calls[0].request.url == info_endpoint

        # other calls are to result
        for i in range(failed_attempts):
            r = responses.calls[i].request
            assert r.url == info_endpoint

        expected_logs = ["Please wait until your job is completed..."]
        assert caplog.messages == expected_logs

    @pytest.mark.parametrize(
        "status",
        ["success", "error"],
    )
    @responses.activate
    def test_wait_for_response_to_get_request_verbose(
        self, monkeypatch, caplog, status
    ):
        monkeypatch.setattr("qibo_client.qibo_job.constants.TIMEOUT", 2)
        monkeypatch.setattr(
            "qibo_client.qibo_job.constants.SECONDS_BETWEEN_CHECKS", 1e-4
        )

        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, endpoint, status=200)

        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        statuses_list = [
            "queueing",
            "queueing",
            "pending",
            "running",
            "postprocessing",
            status,
        ]
        for s in statuses_list:
            response_json = {
                "status": s,
                "seconds_to_job_start": 300,
                "job_queue_position": 1,
            }
            responses.add(
                responses.GET,
                endpoint,
                json=response_json,
                status=200,
            )
        self.obj._wait_for_response_to_get_request(verbose=True)

        expected_logs = [
            "> Starting qibo client...",
            "> Job posted on None with pid, fakePid",
            "* Job QUEUEING",
            "* Job PENDING -> position in queue: 1, max ETD: 0:05:00",
            "> Job RUNNING",
            "+ Job SUCCESS" if status == "success" else "x Job ERROR",
            "Job COMPLETED",
        ]
        assert caplog.messages == expected_logs

    @responses.activate
    def test_delete(self):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = {"detail": f"Job {FAKE_PID} deleted"}
        responses.add(responses.DELETE, endpoint, status=200, json=response_json)

        response = self.obj.delete()
        assert response.json() == response_json


def test_extract_archive_to_folder_fallback(monkeypatch, tmp_path):
    """Test _extract_archive_to_folder falls back when filter param is not supported."""
    import io
    import tarfile

    # Create a valid tar.gz archive
    archive_path = tmp_path / "test.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        data = b"hello world"
        info = tarfile.TarInfo(name="test.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    dest = tmp_path / "output"
    dest.mkdir()

    # Monkey-patch extractall to simulate Python < 3.12 (no filter support)
    original_extractall = tarfile.TarFile.extractall
    call_count = [0]

    def fake_extractall(self, path=".", members=None, **kwargs):
        call_count[0] += 1
        if "filter" in kwargs:
            raise TypeError("extractall() got unexpected keyword argument 'filter'")
        return original_extractall(self, path, members=members)

    monkeypatch.setattr(tarfile.TarFile, "extractall", fake_extractall)

    qibo_job._extract_archive_to_folder(archive_path, dest)
    assert (dest / "test.txt").exists()
    assert call_count[0] == 2  # first call raises, second succeeds


class TestLiveTTYBranch:
    """Cover qibo_job.py lines 214-334: the Live (Rich UI) polling branch."""

    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        self.obj = qibo_job.QiboJob(FAKE_PID, FAKE_URL, device=FAKE_DEVICE)
        # Force the live branch
        monkeypatch.setattr("qibo_client.qibo_job.USE_RICH_UI", True)
        monkeypatch.setattr("qibo_client.qibo_job.constants.TIMEOUT", 2)

    @responses.activate
    def test_live_branch_immediate_success(self, monkeypatch):
        """Job already SUCCESS on first fetch -> enters live branch, renders final banner, returns."""
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # Initial fetch
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        # Loop fetch
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        # Download
        download_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(
            responses.GET, download_endpoint, json={"data": "result"}, status=200
        )

        # Use a non-interactive console to avoid TTY issues
        from rich.console import Console

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        response, job_status = self.obj._wait_for_response_to_get_request(
            1e-4, verbose=True
        )
        assert job_status == qibo_job.QiboJobStatus.SUCCESS
        assert response.json() == {"data": "result"}

    @responses.activate
    def test_live_branch_polls_then_success(self, monkeypatch):
        """Job transitions PENDING -> SUCCESS in the live branch."""
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # Initial fetch
        responses.add(
            responses.GET,
            info_endpoint,
            json={"status": "pending", "queue_position": 2, "etd_seconds": 60},
            status=200,
        )
        # Loop fetch 1: still pending
        responses.add(
            responses.GET,
            info_endpoint,
            json={"status": "pending", "queue_position": 1, "etd_seconds": 30},
            status=200,
        )
        # Loop fetch 2: success
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        # Download
        download_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, download_endpoint, json={"data": "ok"}, status=200)

        from rich.console import Console

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        response, job_status = self.obj._wait_for_response_to_get_request(
            1e-4, verbose=True
        )
        assert job_status == qibo_job.QiboJobStatus.SUCCESS

    @responses.activate
    def test_live_branch_error(self, monkeypatch):
        """Job ERROR in live branch."""
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        responses.add(
            responses.GET, info_endpoint, json={"status": "error"}, status=200
        )
        responses.add(
            responses.GET, info_endpoint, json={"status": "error"}, status=200
        )
        download_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(
            responses.GET, download_endpoint, json={"data": "err"}, status=200
        )

        from rich.console import Console

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        response, job_status = self.obj._wait_for_response_to_get_request(
            1e-4, verbose=True
        )
        assert job_status == qibo_job.QiboJobStatus.ERROR

    @responses.activate
    def test_live_branch_postprocessing_then_success(self, monkeypatch):
        """Cover _render returning None for POSTPROCESSING (lines 214-216)."""
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # Initial: running
        responses.add(
            responses.GET, info_endpoint, json={"status": "running"}, status=200
        )
        # Loop 1: postprocessing (should skip render update)
        responses.add(
            responses.GET, info_endpoint, json={"status": "postprocessing"}, status=200
        )
        # Loop 2: success
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        download_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, download_endpoint, json={"data": "ok"}, status=200)

        from rich.console import Console

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        response, job_status = self.obj._wait_for_response_to_get_request(
            1e-4, verbose=True
        )
        assert job_status == qibo_job.QiboJobStatus.SUCCESS

    @responses.activate
    def test_live_branch_with_circuit(self, monkeypatch):
        """Cover circuit panel and show_circuit=True path (lines 264-271)."""
        import qibo

        circ = qibo.Circuit(2)
        circ.add(qibo.gates.H(0))
        self.obj.circuit = circ.raw

        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        download_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, download_endpoint, json={"data": "ok"}, status=200)

        from rich.console import Console

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        response, job_status = self.obj._wait_for_response_to_get_request(
            1e-4, verbose=True, show_circuit=True
        )
        assert job_status == qibo_job.QiboJobStatus.SUCCESS

    @responses.activate
    def test_live_branch_keyboard_toggle(self, monkeypatch):
        """Cover lines 293-300: keyboard 'c' toggles circuit visibility."""
        from unittest.mock import MagicMock

        import qibo

        circ = qibo.Circuit(2)
        circ.add(qibo.gates.H(0))
        self.obj.circuit = circ.raw

        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # Initial fetch: pending
        responses.add(
            responses.GET, info_endpoint, json={"status": "pending"}, status=200
        )
        # Loop 1: still pending (keyboard 'c' pressed)
        responses.add(
            responses.GET, info_endpoint, json={"status": "pending"}, status=200
        )
        # Loop 2: success
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        download_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, download_endpoint, json={"data": "ok"}, status=200)

        from rich.console import Console

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        # Mock NonBlockingKeyReader to simulate active TTY with key 'c' pressed once
        key_sequence = iter(["c", None, None, None])

        class FakeKeyReader:
            active = True

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                pass

            def get_key(self):
                return next(key_sequence, None)

        monkeypatch.setattr("qibo_client.qibo_job.NonBlockingKeyReader", FakeKeyReader)

        response, job_status = self.obj._wait_for_response_to_get_request(
            1e-4, verbose=True, show_circuit=False
        )
        assert job_status == qibo_job.QiboJobStatus.SUCCESS
