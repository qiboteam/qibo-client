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
    stream = [b"line1\n", b"line2\n"]
    assert not archive_path.is_file()
    result_path = qibo_job._write_stream_to_tmp_file(stream)
    assert result_path == archive_path
    assert result_path.is_file()
    assert result_path.read_bytes() == b"".join(stream)


def test__write_stream_to_tmp_file_with_archive(archive_path: Path):
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
    assert not archive_path.is_file()


FAKE_PID = "fakePid"
FAKE_URL = "http://fake.endpoint.com"
FAKE_CIRCUIT = {"fake": "circuit"}
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
        response_json["nshots"] = FAKE_NSHOTS
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
        assert response_json["detail"] in str(err.value)

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
    @responses.activate
    def test_running_with_cached_results(self, status, expected_result):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        responses.add(
            responses.GET, endpoint, status=200, json={"status": status.name.lower()}
        )
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
    @responses.activate
    def test_success_with_cached_results(self, status, expected_result):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        responses.add(
            responses.GET, endpoint, status=200, json={"status": status.name.lower()}
        )
        result = self.obj.success()
        assert result == expected_result

    @responses.activate
    def test_result_handles_tarfile_readerror(self, monkeypatch, refresh_job):
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
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
        responses.add(
            responses.GET, info_endpoint, json={"status": "error"}, status=200
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
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        monkeypatch.setattr(
            "qibo_client.qibo_job._save_and_unpack_stream_response_to_folder",
            lambda *args: "ok",
        )
        monkeypatch.setattr(
            "qibo_client.qibo_job.qibo.result.load_result", lambda x: FAKE_RESULT
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
        for _ in range(failed_attempts + 1):
            responses.add(
                responses.GET, info_endpoint, status=200, json={"status": "running"}
            )
        responses.add(responses.GET, info_endpoint, status=200, json={"status": status})
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, endpoint, json={"detail": "output"}, status=200)

        response, job_status = self.obj._wait_for_response_to_get_request(1e-4, False)
        assert job_status == expected_job_status

    @pytest.mark.parametrize("status", ["success", "error"])
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
            responses.add(responses.GET, endpoint, json=response_json, status=200)

        self.obj._wait_for_response_to_get_request(verbose=True)
        log_text = "".join(caplog.messages)
        assert "* Job QUEUEING" in log_text
        assert "max ETD: 0:05:00" in log_text
        assert "> Job RUNNING" in log_text
        assert "Job COMPLETED" in log_text

    @responses.activate
    def test_delete(self):
        endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        response_json = {"detail": f"Job {FAKE_PID} deleted"}
        responses.add(responses.DELETE, endpoint, status=200, json=response_json)
        response = self.obj.delete()
        assert response.json() == response_json


def test_extract_archive_to_folder_fallback(monkeypatch, tmp_path):
    import io
    import tarfile

    archive_path = tmp_path / "test.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        data = b"hello world"
        info = tarfile.TarInfo(name="test.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    dest = tmp_path / "output"
    dest.mkdir()
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
    assert call_count[0] == 2


class TestLiveTTYBranch:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        self.obj = qibo_job.QiboJob(FAKE_PID, FAKE_URL, device=FAKE_DEVICE)
        monkeypatch.setattr("qibo_client.qibo_job.USE_RICH_UI", True)
        monkeypatch.setattr("qibo_client.qibo_job.constants.TIMEOUT", 2)

    @responses.activate
    def test_live_branch_immediate_success(self, monkeypatch):
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # 1. initial refresh()
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        # 2. _wait_live while-True refresh()
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )

        download_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(
            responses.GET, download_endpoint, json={"data": "result"}, status=200
        )

        from rich.console import Console

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        response, job_status = self.obj._wait_for_response_to_get_request(
            1e-4, verbose=True
        )
        assert job_status == qibo_job.QiboJobStatus.SUCCESS

    @responses.activate
    def test_live_branch_polls_then_success(self, monkeypatch):
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # Sequence of statuses
        responses.add(
            responses.GET, info_endpoint, json={"status": "pending"}, status=200
        )
        responses.add(
            responses.GET, info_endpoint, json={"status": "pending"}, status=200
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
            1e-4, verbose=True
        )
        assert job_status == qibo_job.QiboJobStatus.SUCCESS

    @responses.activate
    def test_live_branch_keyboard_toggle(self, monkeypatch):
        from rich.panel import Panel
        from rich.text import Text

        monkeypatch.setattr(
            "qibo_client.qibo_job.build_circuit_panel",
            lambda *a: Panel(Text("circuit")),
        )
        self.obj.circuit = {"fake": "raw"}
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"

        # Iteration 1: key 'c' -> visible=True
        responses.add(
            responses.GET, info_endpoint, json={"status": "pending"}, status=200
        )
        # Iteration 2: key 'c' -> visible=False
        responses.add(
            responses.GET, info_endpoint, json={"status": "pending"}, status=200
        )
        # Iteration 3: key None -> loop continues
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )

        download_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, download_endpoint, json={"data": "ok"}, status=200)

        from rich.console import Console

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        key_seq = iter(["c", "c", None])

        class FakeKeyReader:
            active = True

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def get_key(self):
                return next(key_seq, None)

        monkeypatch.setattr("qibo_client.qibo_job.NonBlockingKeyReader", FakeKeyReader)
        self.obj._wait_for_response_to_get_request(
            1e-4, verbose=True, show_circuit=False
        )

    @responses.activate
    def test_live_branch_with_circuit_visible(self, monkeypatch):
        from rich.panel import Panel
        from rich.text import Text

        monkeypatch.setattr(
            "qibo_client.qibo_job.build_circuit_panel",
            lambda *a: Panel(Text("circuit")),
        )
        self.obj.circuit = {"fake": "raw"}
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

        self.obj._wait_for_response_to_get_request(
            1e-4, verbose=True, show_circuit=True
        )

    @responses.activate
    def test_live_branch_keyboard_inactive(self, monkeypatch):
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        download_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, download_endpoint, json={"data": "ok"}, status=200)

        class FakeKeyReader:
            active = False

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def get_key(self):
                return None

        monkeypatch.setattr("qibo_client.qibo_job.NonBlockingKeyReader", FakeKeyReader)
        self.obj._wait_for_response_to_get_request(1e-4, verbose=True)

    @responses.activate
    def test_wait_non_live_non_verbose(self, caplog):
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # initial refresh
        responses.add(
            responses.GET, info_endpoint, json={"status": "running"}, status=200
        )
        # loop refresh
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )

        download_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, download_endpoint, json={"data": "ok"}, status=200)

        self.obj._wait_for_response_to_get_request(1e-4, verbose=False)
        assert "Please wait" in "".join(caplog.messages)

    @responses.activate
    def test_live_branch_with_postprocessing(self, monkeypatch):
        info_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/"
        # Sequence: pending -> postprocessing -> success
        responses.add(
            responses.GET, info_endpoint, json={"status": "pending"}, status=200
        )
        responses.add(
            responses.GET, info_endpoint, json={"status": "postprocessing"}, status=200
        )
        responses.add(
            responses.GET, info_endpoint, json={"status": "success"}, status=200
        )
        download_endpoint = FAKE_URL + f"/api/jobs/{FAKE_PID}/download/"
        responses.add(responses.GET, download_endpoint, json={"data": "ok"}, status=200)

        from rich.console import Console
        from rich.live import Live

        fake_console = Console(file=__import__("io").StringIO(), force_terminal=True)
        monkeypatch.setattr("qibo_client.qibo_job.console", fake_console)

        self.obj._wait_for_response_to_get_request(1e-4, verbose=True)
