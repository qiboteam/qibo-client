import tarfile
from contextlib import contextmanager
from pathlib import Path

import pytest
import responses
import utils_test_qibo_client as utils

from qibo_client import QiboJobStatus, exceptions, qibo_job

ARCHIVE_NAME = "file.tar.gz"


@pytest.mark.parametrize(
    "status, expected_result",
    [
        ("to_do", QiboJobStatus.QUEUED),
        ("in_progress", QiboJobStatus.RUNNING),
        ("success", QiboJobStatus.DONE),
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
FAKE_URL = "http://fake.endpoint.com/api"
FAKE_CIRCUIT = "fakeCircuit"
FAKE_NSHOTS = 10
FAKE_DEVICE = "fakeDevice"
FAKE_NUM_QUBITS = 8
FAKE_HARDWARE_TYPE = "fakeHardwareType"
FAKE_DESCRIPTION = "fakeDescription"
FAKE_STATUS = "fakeStatus"
BASE_JOB_STATUS = QiboJobStatus.DONE
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
        endpoint = FAKE_URL + f"/job/info/{FAKE_PID}/"
        response_json = {
            "circuit": FAKE_CIRCUIT,
            "nshots": FAKE_NSHOTS,
            "device": {
                "name": FAKE_DEVICE,
                "max_num_qubits": FAKE_NUM_QUBITS,
                "hardware_type": FAKE_HARDWARE_TYPE,
                "description": None,
                "status": FAKE_STATUS,
            },
            "status": BASE_JOB_STATUS_STR,
        }
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
        endpoint = FAKE_URL + f"/job/info/{invalid_pid}/"
        response_json = {"detail": f"Invalid job pid, got {invalid_pid}"}
        responses.add(responses.GET, endpoint, status=404, json=response_json)

        with pytest.raises(exceptions.JobApiError) as err:
            self.obj.refresh()

        expected_message = f"[404 Error] {response_json['detail']}"
        assert str(err.value) == expected_message

    @pytest.mark.parametrize(
        "status, expected_result",
        [
            ("to_do", QiboJobStatus.QUEUED),
            ("in_progress", QiboJobStatus.RUNNING),
            ("success", QiboJobStatus.DONE),
            ("error", QiboJobStatus.ERROR),
        ],
    )
    @responses.activate
    def test_status(self, status, expected_result):
        endpoint = FAKE_URL + f"/job/info/{FAKE_PID}/"
        response_json = {"status": status}
        responses.add(responses.GET, endpoint, status=200, json=response_json)

        result = self.obj.status()

        assert result == expected_result

    @pytest.mark.parametrize(
        "status, expected_result",
        [
            (QiboJobStatus.QUEUED, False),
            (QiboJobStatus.RUNNING, True),
            (QiboJobStatus.DONE, False),
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
            (QiboJobStatus.QUEUED, False),
            (QiboJobStatus.RUNNING, True),
            (QiboJobStatus.DONE, False),
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
            (QiboJobStatus.QUEUED, False),
            (QiboJobStatus.RUNNING, False),
            (QiboJobStatus.DONE, True),
            (QiboJobStatus.ERROR, False),
        ],
    )
    def test_done_with_cached_results(
        self, status: QiboJobStatus, expected_result: bool
    ):
        self.obj._status = status
        result = self.obj.done()
        assert result == expected_result

    @pytest.mark.parametrize(
        "status, expected_result",
        [
            (QiboJobStatus.QUEUED, False),
            (QiboJobStatus.RUNNING, False),
            (QiboJobStatus.DONE, True),
            (QiboJobStatus.ERROR, False),
        ],
    )
    def test_done_without_cached_results(
        self, monkeypatch, status: QiboJobStatus, expected_result: bool
    ):
        assert self.obj._status is None

        def change_obj_status_to():
            self.obj._status = status

        monkeypatch.setattr(self.obj, "refresh", change_obj_status_to)
        result = self.obj.done()
        assert result == expected_result

    @responses.activate
    def test_result_handles_tarfile_readerror(self, monkeypatch, refresh_job):
        endpoint = FAKE_URL + f"/job/result/{FAKE_PID}/"
        headers = {"Job-Status": "success"}
        responses.add(responses.GET, endpoint, status=200, headers=headers)

        info_endpoint = FAKE_URL + f"/job/info/{FAKE_PID}/"
        responses.add(
            responses.GET,
            info_endpoint,
            json={"status": "in_progress"},
            status=200,
        )

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
        endpoint = FAKE_URL + f"/job/result/{FAKE_PID}/"
        headers = {"Job-Status": "error"}
        responses.add(responses.GET, endpoint, status=200, headers=headers)

        info_endpoint = FAKE_URL + f"/job/info/{FAKE_PID}/"
        responses.add(
            responses.GET,
            info_endpoint,
            json={"status": "in_progress"},
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
        endpoint = FAKE_URL + f"/job/result/{FAKE_PID}/"
        headers = {"Job-Status": "success"}
        responses.add(responses.GET, endpoint, status=200, headers=headers)

        info_endpoint = FAKE_URL + f"/job/info/{FAKE_PID}/"
        responses.add(
            responses.GET,
            info_endpoint,
            json={"status": "in_progress"},
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
            ("success", QiboJobStatus.DONE),
            ("error", QiboJobStatus.ERROR),
        ],
    )
    @responses.activate
    def test_wait_for_response_to_get_request(
        self, monkeypatch, caplog, status, expected_job_status
    ):

        monkeypatch.setattr("qibo_client.qibo_job.constants.TIMEOUT", 2)

        info_endpoint = FAKE_URL + f"/job/info/{FAKE_PID}/"
        responses.add(
            responses.GET,
            info_endpoint,
            json={"status": "in_progress"},
            status=200,
        )

        failed_attempts = 3
        endpoint = FAKE_URL + f"/job/result/{FAKE_PID}/"
        failed_headers = {"Job-Status": "in_progress"}
        response_json = {"detail": "output"}
        for _ in range(failed_attempts):
            responses.add(
                responses.GET,
                endpoint,
                headers=failed_headers,
                status=200,
            )

        success_headers = {"Job-Status": status}
        responses.add(
            responses.GET,
            endpoint,
            headers=success_headers,
            json=response_json,
            status=200,
        )

        response, job_status = self.obj._wait_for_response_to_get_request(1e-4)

        assert job_status == expected_job_status
        assert response.json() == response_json
        assert len(responses.calls) == 1 + failed_attempts + 1

        # first call is to status
        assert responses.calls[0].request.url == info_endpoint

        # other calls are to result
        for i in range(failed_attempts + 1):
            r = responses.calls[i + 1].request
            assert r.url == endpoint

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

        endpoint = FAKE_URL + f"/job/info/{FAKE_PID}/"
        responses.add(
            responses.GET,
            endpoint,
            json={"status": "in_progress"},
            status=200,
        )

        endpoint = FAKE_URL + f"/job/result/{FAKE_PID}/"
        statuses_list = ["to_do", "in_progress", status]
        for s in statuses_list:
            failed_headers = {"Job-Status": s}
            responses.add(
                responses.GET,
                endpoint,
                headers=failed_headers,
                status=200,
            )
        self.obj._wait_for_response_to_get_request(verbose=True)

        expected_logs = ["Job QUEUING", "Job RUNNING", "Job COMPLETED"]
        assert caplog.messages == expected_logs
