"""Small verified worker transfers; large images keep their separate setup receipt."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import stat
import tarfile

from tools.artifact_identity_runner.files import fingerprint
from tools.optimization_docker import fixtures
from tools.optimization_docker.owned import stamp
from tools.optimization_evidence.common import require

MAX_TRANSFER = 40 * 1024**2


def create_archive(directory: Path, destination: Path):
    before = fixtures.inventory(directory)
    require(int(before["bytes"]) <= 32 * 1024**2 and len(before["entries"]) <= 512,
            "kubernetes-small-transfer-bound")
    with destination.open("xb") as output, tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for row in before["entries"]:
            if row["path"] == ".":
                continue
            name = row["path"]
            info = tarfile.TarInfo(name)
            info.mode, info.uid, info.gid, info.mtime = int(row["mode"], 8), 0, 0, 0
            if row["kind"] == "directory":
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                info.size = int(row["bytes"])
                with (directory / name).open("rb") as stream:
                    archive.addfile(info, stream)
    require(fixtures.inventory(directory) == before and destination.stat().st_size <= MAX_TRANSFER,
            "kubernetes-transfer-source-changed")
    return {"inventory": before, "archive_sha256": fingerprint(destination)[0],
            "archive_bytes": str(destination.stat().st_size)}


def extract_archive(archive_path: Path, destination: Path, *, expected_root: str, maximum=MAX_TRANSFER):
    """Extract Docker's directory tar to a fresh local path without trusting tar paths."""
    require(not destination.exists() and destination.parent.is_dir() and not archive_path.is_symlink()
            and archive_path.stat().st_size <= maximum, "kubernetes-download-fresh-bound")
    require(expected_root and "/" not in expected_root and expected_root not in (".", ".."),
            "kubernetes-download-root-name")
    count = total = 0
    seen = set()
    selected = []
    with tarfile.open(archive_path, "r:") as archive:
        for member in archive:
            count += 1
            path = PurePosixPath(member.name)
            require(count <= 512 and member.name == path.as_posix()
                    and not path.is_absolute() and path.parts and path.parts[0] == expected_root
                    and ".." not in path.parts and "\\" not in member.name
                    and member.name.casefold() not in seen and (member.isfile() or member.isdir())
                    and 0 <= member.size <= maximum and len(path.parts) <= 10,
                    "kubernetes-download-member")
            seen.add(member.name.casefold())
            total += member.size
            require(total <= maximum, "kubernetes-download-expanded-bound")
            relative = PurePosixPath(*path.parts[1:])
            require(relative != PurePosixPath(".") or member.isdir(), "kubernetes-download-root-type")
            selected.append((member, relative))
        destination.mkdir(mode=0o700)
        for member, relative in selected:
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("xb") as output:
                    copied = 0
                    while chunk := source.read(65536):
                        copied += len(chunk)
                        require(copied <= member.size, "kubernetes-download-member-growth")
                        output.write(chunk)
                require(copied == member.size, "kubernetes-download-truncated-member")
                target.chmod(member.mode & 0o777)
        for member, relative in reversed(selected):
            if member.isdir():
                destination.joinpath(*relative.parts).chmod(member.mode & 0o777)
    return fixtures.inventory(destination)


def download(worker, source_path: str, destination: Path, archive_path: Path):
    root = "/var/local/lsf112/" + worker.owner + "/"
    require(source_path.startswith(root) and ".." not in PurePosixPath(source_path).parts,
            "kubernetes-download-owned-path")
    started = stamp()
    receipt = inventory = checksum = failure = None
    try:
        receipt = worker.engine.download_archive(worker.container_id, source_path, archive_path,
                                                 timeout=60, maximum=MAX_TRANSFER)
        checksum = fingerprint(archive_path)[0]
        inventory = extract_archive(archive_path, destination, expected_root=PurePosixPath(source_path).name)
    except BaseException as error:
        failure = type(error).__name__
        receipt = getattr(error, "receipt", receipt)
        if archive_path.is_file():
            checksum = fingerprint(archive_path)[0]
        raise
    finally:
        row = worker.journal.append({"provider": "docker", "operation": "worker-download",
            "container_id": worker.container_id, "source_path": source_path,
            "started_nanos": started, "finished_nanos": stamp(), "receipt": receipt,
            "inventory": inventory, "archive_sha256": checksum, "failure": failure})
    return row["ordinal"]


def copy_file(source: Path, destination: Path):
    info = source.lstat()
    require(stat.S_ISREG(info.st_mode) and not source.is_symlink() and info.st_size <= 16 * 1024**2,
            "kubernetes-input-file")
    before = fingerprint(source)
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        while chunk := incoming.read(65536):
            outgoing.write(chunk)
    destination.chmod(stat.S_IMODE(info.st_mode))
    require(fingerprint(source) == fingerprint(destination) == before, "kubernetes-input-file-changed")
