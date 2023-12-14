import io
from pathlib import Path
import tarfile
from typing import Dict, List, Optional, Tuple

from requests.exceptions import HTTPError


class MockedResponse:
    """A fake representation of a `requests.response` object"""

    def __init__(self, status_code: int, json_data: Optional[Dict] = None):
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = json_data.get("headers")
        self.content = json_data.get("content")
        self._iter_content = json_data.get("iter_content")

    def json(self) -> Dict:
        return self._json

    def iter_content(self):
        return self._iter_content

    def raise_for_status(self):
        if 400 <= self.status_code < 500:
            http_error_msg = f"{self.status_code} Client Error"

        elif 500 <= self.status_code < 600:
            http_error_msg = f"{self.status_code} Server Error"
        else:
            http_error_msg = ""

        if http_error_msg:
            raise HTTPError(http_error_msg)


class MockedCircuit:
    """A fake representation of a Qibo quantum circuit"""

    def __init__(self):
        self.raw = "raw circuit representation"


class FakeStreamingHttpResponse:
    """A fake representation of Django StreamingHttpResponse"""

    def __init__(self, tar_gz_bytes):
        self.tar_gz_bytes = tar_gz_bytes

    def __iter__(self):
        # Create a tarfile object from the bytes stream
        tar_stream = io.BytesIO(self.tar_gz_bytes)
        with tarfile.open(fileobj=tar_stream, mode="r:gz") as tar:
            for tar_info in tar:
                # Yield each byte of the file's content
                with tar.extractfile(tar_info) as file:
                    while byte := file.read(1):
                        yield byte


def _generic_create_archive_(archive_path, get_file_context_manager_fn):
    members = ["member1.txt", "member2.txt"]
    members_contents = [
        b"This is the content of member1.txt.",
        b"This is the content of member2.txt.",
    ]

    with get_file_context_manager_fn() as tar:
        for member, contents in zip(members, members_contents):
            member_info = tarfile.TarInfo(member)
            member_info.size = len(contents)
            tar.addfile(member_info, io.BytesIO(contents))

        return members, members_contents


def create_fake_archive(archive_path: Path) -> Tuple[List[str], List[str]]:
    """Create a .tar.gz archive with fake members and


    :param archive_path: the destination path for the archive
    :type archive_path: Path

    :return: the list with the archive file members
    :rtype: List[str]
    :return: the list with the contents of each archive file member
    :rtype: List[str]
    """
    members, members_contents = _generic_create_archive_(
        archive_path, lambda: tarfile.open(archive_path, "w:gz")
    )
    return members, members_contents


def create_in_memory_fake_archive(archive_path: Path):
    with io.BytesIO() as buffer:
        members, members_contents = _generic_create_archive_(
            archive_path, lambda: tarfile.open(fileobj=buffer, mode="w:gz")
        )
        archive_as_bytes = buffer.getvalue()
    return archive_as_bytes, members, members_contents


class TarGzFileStreamer:
    def __init__(self, data, chunk_size=128):
        self.data = data
        self.chunk_size = chunk_size
        self.size = len(data)

    def __iter__(self):
        for i in range(0, len(self.data), self.chunk_size):
            yield self.data[i : i + self.chunk_size]


def get_in_memory_fake_archive_stream(archive_path):
    archive_as_bytes, members, members_contents = create_in_memory_fake_archive(
        archive_path
    )
    return TarGzFileStreamer(archive_as_bytes), members, members_contents


def get_fake_tmp_file_class(file_path: Path):
    class TmpFile:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            self.opened_file = open(file_path, "wb")
            return self.opened_file

        def __exit__(self, exc_type, exc_value, exc_tb):
            self.opened_file.close()

    return TmpFile
