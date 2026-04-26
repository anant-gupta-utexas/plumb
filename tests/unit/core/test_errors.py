import pytest

from plumb.core.errors import (
    BlobNotFoundError,
    JudgeError,
    PlumbError,
    StorageError,
    ValidationError,
)


def test_all_inherit_from_plumb_error() -> None:
    for cls in (StorageError, BlobNotFoundError, ValidationError, JudgeError):
        assert issubclass(cls, PlumbError), f"{cls} does not inherit from PlumbError"


def test_instances_are_exceptions() -> None:
    for cls in (PlumbError, StorageError, BlobNotFoundError, ValidationError, JudgeError):
        err = cls("msg")
        assert isinstance(err, Exception)
        assert isinstance(err, PlumbError)


def test_raise_and_catch_by_base() -> None:
    for cls in (StorageError, BlobNotFoundError, ValidationError, JudgeError):
        with pytest.raises(PlumbError):
            raise cls("test")


def test_message_preserved() -> None:
    err = ValidationError("bad input")
    assert str(err) == "bad input"
