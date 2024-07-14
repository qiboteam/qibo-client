import io
import tarfile
from pathlib import Path
from typing import Generator, List, Tuple


def _generic_create_archive_(get_file_context_manager_fn):
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


def create_fake_archive(archive_path: Path) -> Tuple[List[str], List[bytes]]:
    """Create a .tar.gz archive with fake members and


    :param archive_path: the destination path for the archive
    :type archive_path: Path

    :return: the list with the archive file members
    :rtype: List[str]
    :return: the list with the contents of each archive file member
    :rtype: List[bytes]
    """
    members, members_contents = _generic_create_archive_(
        lambda: tarfile.open(archive_path, "w:gz")
    )
    return members, members_contents


def create_in_memory_fake_archive() -> Tuple[bytes, List[str], List[bytes]]:
    with io.BytesIO() as buffer:
        members, members_contents = _generic_create_archive_(
            lambda: tarfile.open(fileobj=buffer, mode="w:gz")
        )
        archive_as_bytes = buffer.getvalue()
    return archive_as_bytes, members, members_contents


class DataStreamer:
    def __init__(self, data: bytes, chunk_size: int = 128):
        self.data = data
        self.chunk_size = chunk_size
        self.size = len(data)

    def __iter__(self) -> Generator[None, bytes, None]:
        for i in range(0, len(self.data), self.chunk_size):
            yield self.data[i : i + self.chunk_size]


def get_in_memory_fake_archive_stream():
    archive_as_bytes, members, members_contents = create_in_memory_fake_archive()
    return DataStreamer(archive_as_bytes), members, members_contents
