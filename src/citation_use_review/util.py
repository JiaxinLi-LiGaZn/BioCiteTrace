"""Small deterministic I/O, hashing, and path helpers."""

# Standard-library imports provide atomic files, canonical JSON, hashes, and timestamps.
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping
from datetime import datetime, timezone

from .errors import ContractError


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Decode a JSON object while rejecting ambiguous duplicate keys.

    Args:
        pairs: Ordered key-value pairs supplied by ``json.loads``.

    Returns:
        A dictionary containing each key exactly once.

    Raises:
        ContractError: If a key occurs more than once.
    """

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path | str) -> Any:
    """Read one UTF-8 JSON file with duplicate-key rejection.

    Args:
        path: JSON file path.

    Returns:
        The decoded JSON value.
    """

    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot read valid JSON from {source}: {error}") from error


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON-compatible value in a stable byte representation.

    Args:
        value: JSON-compatible object.

    Returns:
        UTF-8 bytes with sorted keys and no insignificant whitespace.
    """

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 digest for a byte string.

    Args:
        value: Bytes to hash.

    Returns:
        A 64-character hexadecimal digest.
    """

    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path | str) -> str:
    """Hash a file without loading the entire file into memory.

    Args:
        path: File to hash.

    Returns:
        A 64-character lowercase SHA-256 digest.
    """

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    """Return the current UTC time.

    Returns:
        ISO-8601 timestamp with an explicit UTC offset.
    """

    return datetime.now(timezone.utc).isoformat()


def resolve_project_path(project_root: Path, value: str) -> Path:
    """Resolve a configured path inside the project root.

    Args:
        project_root: Trusted repository root.
        value: Relative configured path or an absolute path already inside the root.

    Returns:
        Resolved path contained by ``project_root``.

    Raises:
        ContractError: If the path escapes the repository root.
    """

    root = project_root.resolve()
    candidate = Path(value)
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ContractError(f"configured path escapes project root: {value}") from error
    return resolved


def _prepare_private_parent(path: Path) -> None:
    """Create a private parent directory for a workflow artifact.

    Args:
        path: Destination file whose parent should exist.

    Returns:
        ``None`` after creating the parent and setting mode ``0700``.
    """

    missing: list[Path] = []
    current = path.parent
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            raise ContractError(f"cannot find an existing ancestor for {path}")
        current = current.parent
    if not current.is_dir():
        raise ContractError(f"artifact parent is not a directory: {current}")
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            if not directory.is_dir():
                raise ContractError(f"artifact parent is not a directory: {directory}")


def atomic_write_bytes(path: Path | str, data: bytes, mode: int = 0o600) -> None:
    """Atomically replace one file with durable bytes.

    Args:
        path: Destination file.
        data: Complete new file bytes.
        mode: POSIX permission bits for the new file.

    Returns:
        ``None`` after the file and parent directory entry are fsynced.
    """

    destination = Path(path)
    _prepare_private_parent(destination)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as handle:
            temporary_name = handle.name
            os.chmod(temporary_name, mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def atomic_write_json(path: Path | str, value: Any) -> None:
    """Atomically write canonical JSON followed by one newline.

    Args:
        path: Destination JSON file.
        value: JSON-compatible value.

    Returns:
        ``None`` after durable publication.
    """

    atomic_write_bytes(path, canonical_json_bytes(value) + b"\n")


def atomic_write_text(path: Path | str, value: str) -> None:
    """Atomically write UTF-8 text.

    Args:
        path: Destination text file.
        value: Complete text content.

    Returns:
        ``None`` after durable publication.
    """

    atomic_write_bytes(path, value.encode("utf-8"))


def write_exclusive_json(path: Path | str, value: Mapping[str, Any]) -> None:
    """Create a durable JSON claim without replacing an existing path.

    Args:
        path: New claim path.
        value: Claim payload.

    Returns:
        ``None`` after the claim and directory entry are fsynced.

    Raises:
        FileExistsError: If a claim already exists.
    """

    destination = Path(path)
    _prepare_private_parent(destination)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        payload = canonical_json_bytes(dict(value)) + b"\n"
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory_fd = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
