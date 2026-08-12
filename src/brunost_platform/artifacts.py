"""Content-addressed submission bundles compatible with Brunost Judge."""

from __future__ import annotations

import gzip
import hashlib
import io
import tarfile
from pathlib import Path


class ArtifactError(ValueError):
    """Raised when a submission directory cannot be safely packaged."""


def pack_directory(path: str | Path) -> bytes:
    """Create the same deterministic tar.gz format accepted by the Judge API."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ArtifactError(f"submission directory does not exist: {root}")
    tar_output = io.BytesIO()
    with tarfile.open(fileobj=tar_output, mode="w") as archive:
        for item in sorted(root.rglob("*")):
            if item.is_symlink():
                raise ArtifactError(f"symlinks are not allowed: {item}")
            relative = item.relative_to(root).as_posix()
            info = archive.gettarinfo(str(item), arcname=relative)
            if not (item.is_file() or item.is_dir()):
                raise ArtifactError(f"special files are not allowed: {item}")
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            if item.is_file():
                with item.open("rb") as source:
                    archive.addfile(info, source)
            else:
                archive.addfile(info)
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed:
        compressed.write(tar_output.getvalue())
    return output.getvalue()


def artifact_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
