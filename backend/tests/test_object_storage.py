
"""Tests for private object storage."""

import io

import pytest

from app.storage.base import (
    InvalidStorageKeyError,
    ObjectNotFoundError,
    StorageError,
)
from app.storage.local import LocalObjectStorage


@pytest.fixture
def storage(tmp_path):
    return LocalObjectStorage(tmp_path / "private_objects")


def test_put_read_and_exists(storage):
    content = b"private document content"

    storage.put("org-a/document-1.bin", io.BytesIO(content))

    assert storage.exists("org-a/document-1.bin")
    with storage.open_read("org-a/document-1.bin") as source:
        assert source.read() == content


def test_put_does_not_overwrite_existing_object(storage):
    storage.put("org-a/document.bin", io.BytesIO(b"original"))

    with pytest.raises(StorageError):
        storage.put("org-a/document.bin", io.BytesIO(b"replacement"))

    with storage.open_read("org-a/document.bin") as source:
        assert source.read() == b"original"


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../outside.txt",
        "org/../../outside.txt",
        "/absolute/path.txt",
        r"org\document.txt",
        "C:/outside.txt",
        "org//document.txt",
        "org/./document.txt",
        "org/\x00document.txt",
    ],
)
def test_rejects_unsafe_keys(storage, key):
    with pytest.raises(InvalidStorageKeyError):
        storage.exists(key)


def test_missing_object_raises(storage):
    with pytest.raises(ObjectNotFoundError):
        storage.open_read("org-a/missing.bin")


def test_delete_removes_object(storage):
    storage.put("org-a/document.bin", io.BytesIO(b"content"))

    storage.delete("org-a/document.bin")

    assert not storage.exists("org-a/document.bin")


def test_delete_missing_object_raises(storage):
    with pytest.raises(ObjectNotFoundError):
        storage.delete("org-a/missing.bin")


def test_storage_keys_are_isolated(storage):
    storage.put("org-a/document.bin", io.BytesIO(b"tenant A"))
    storage.put("org-b/document.bin", io.BytesIO(b"tenant B"))

    with storage.open_read("org-a/document.bin") as source:
        assert source.read() == b"tenant A"

    with storage.open_read("org-b/document.bin") as source:
        assert source.read() == b"tenant B"


def test_partial_write_is_cleaned_up(storage):
    class FailingStream:
        def read(self, size=-1):
            raise OSError("simulated read failure")

    with pytest.raises(StorageError):
        storage.put("org-a/failed.bin", FailingStream())

    assert not storage.exists("org-a/failed.bin")
