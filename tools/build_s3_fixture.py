#!/usr/bin/env python3
"""Build the pinned, local-only MinIO TLS fixture without a published server image.

The compiler is an explicitly owned container, not a daemon-side BuildKit job.
Image/source/binary receipts are build outputs, not production release attestations.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tarfile
import urllib.request

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.test_run import TestRun, require

ROOT = Path(__file__).resolve().parents[1]
REVISION = "9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a"
RELEASE = "RELEASE.2025-10-15T17-29-55Z"
SOURCE_URL = f"https://codeload.github.com/minio/minio/tar.gz/{REVISION}"
SOURCE_BYTES = 24_232_282
SOURCE_SHA256 = "45521908307306e925c98d629e1c17d78c8b72b6ee242b1bfb1409f7d8ee5841"
GO_MOD_SHA256 = "673f06144e90bc045f0a20050d2874c52e551be5bfbd70dff6e76b66da0db702"
GO_SUM_SHA256 = "86e062349c7abdce0465561bb409d410a95b00b0969ba05d5fb5f2e3550a5cd4"
BUILDER = "docker.io/library/golang@sha256:966278043a40889499db9b0cd196fc789c37c385d41bd9a10cb1e7764af60cdc"
GO_VERSION = "go1.27.1"
SCHEMA = "latent.s3-fixture-build.v1"
OWNER_LABEL = "io.latent.s3-fixture.owner"
RECIPE_LABEL = "io.latent.s3-fixture.recipe"
BINARY_LABEL = "io.latent.s3-fixture.binary"
MAX_BINARY = 256 * 1024 * 1024
ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
CONTAINER_INSPECT = '[{"Id":{{json .Id}},"Config":{"Labels":{{json .Config.Labels}}},"State":{{json .State}}}]'

# No make/go-generate, mutable toolchain, VCS execution, module updates or image
# base inherited from the unavailable server. Module hashes stay authoritative.
BUILD_SCRIPT = f"""set -eu
trap 'build_status=$?; set +e; df -k /work /tmp /module-cache /build-cache; du -sk /work /tmp /module-cache /build-cache; exit "$build_status"' EXIT
test "$(go version)" = "go version {GO_VERSION} linux/amd64"
mkdir -p /work/source /out
tar -xzf /source.tar.gz -C /work/source --strip-components=1
cd /work/source
printf '%s  go.mod\\n%s  go.sum\\n' '{GO_MOD_SHA256}' '{GO_SUM_SHA256}' | sha256sum -c -
go mod download
go mod verify
GOPROXY=off GOSUMDB=off go build -p=2 -mod=readonly -trimpath -buildvcs=false -tags=kqueue -ldflags='-s -w -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z -X github.com/minio/minio/cmd.ReleaseTag={RELEASE} -X github.com/minio/minio/cmd.CommitID={REVISION}' -o /out/minio .
printf '%s  go.mod\\n%s  go.sum\\n' '{GO_MOD_SHA256}' '{GO_SUM_SHA256}' | sha256sum -c -
go version -m /out/minio > /out/build-info.txt
cp LICENSE CREDITS /out/
cp /etc/ssl/certs/ca-certificates.crt /out/ca-certificates.crt
"""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("source download redirects are forbidden")


def download_source(destination: Path) -> None:
    """Run only as a child of the build owner's 125-second process watchdog."""
    request = urllib.request.Request(SOURCE_URL, headers={"Accept-Encoding": "identity"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as source, destination.open("xb") as output:
        require(source.status == 200 and source.geturl() == SOURCE_URL,
                "invalid-fixture", "minio-source-response-mismatch")
        length = source.headers.get("Content-Length")
        require(length is None or length == str(SOURCE_BYTES), "invalid-fixture", "minio-source-length-mismatch")
        copied = 0
        while True:
            block = source.read(min(1024 * 1024, SOURCE_BYTES + 1 - copied))
            if not block:
                break
            copied += len(block)
            require(copied <= SOURCE_BYTES, "invalid-fixture", "minio-source-download-limit")
            output.write(block)
        require(copied == SOURCE_BYTES, "invalid-fixture", "minio-source-short-read")


def sha(path: Path, maximum: int) -> str:
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum,
            "invalid-fixture", "fixture-file-boundary")
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def recipe() -> str:
    # Bind all implementation bytes as well as the upstream identities. Reuse is
    # explicit through a receipt; a mutable tag or an old helper cannot qualify.
    inputs = [REVISION, SOURCE_SHA256, BUILDER, GO_VERSION,
              sha(Path(__file__).resolve(), 128 * 1024)]
    return hashlib.sha256(json.dumps(inputs, separators=(",", ":")).encode()).hexdigest()


def inspect_archive(path: Path) -> dict:
    require(path.stat().st_size == SOURCE_BYTES and sha(path, SOURCE_BYTES) == SOURCE_SHA256,
            "invalid-fixture", "minio-source-checksum-mismatch")
    names: set[str] = set()
    regular: set[str] = set()
    total = files = 0
    root = "minio-" + REVISION
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            canonical = str(name)
            require(len(names) < 2_000 and len(member.name) <= 512 and not name.is_absolute()
                    and name.parts and name.parts[0] == root and ".." not in name.parts
                    and not any(c in member.name for c in "\\:\0")
                    and member.name.rstrip("/") == canonical and canonical not in names
                    and (member.isfile() or member.isdir()) and not member.mode & 0o7000,
                    "invalid-fixture", "unsafe-minio-source-member")
            names.add(canonical)
            if member.isfile():
                regular.add(canonical)
            require(0 <= member.size <= 64 * 1024 * 1024,
                    "invalid-fixture", "minio-source-member-size")
            total += member.size
            files += int(member.isfile())
            require(total <= 256 * 1024 * 1024, "invalid-fixture", "minio-source-expanded-limit")
            for filename, expected in (("go.mod", GO_MOD_SHA256), ("go.sum", GO_SUM_SHA256)):
                if member.name == root + "/" + filename:
                    stream = archive.extractfile(member)
                    require(stream is not None and hashlib.sha256(stream.read()).hexdigest() == expected,
                            "invalid-fixture", "minio-module-checksum-mismatch")
        require({root + "/" + p for p in ("go.mod", "go.sum", "LICENSE", "CREDITS")} <= regular,
                "invalid-fixture", "minio-source-input-missing")
    return {"archiveSha256": SOURCE_SHA256, "archiveBytes": SOURCE_BYTES,
            "members": len(names), "files": files, "expandedBytes": total}


def verify_binary(path: Path) -> str:
    digest = sha(path, MAX_BINARY)
    with path.open("rb") as binary:
        header = binary.read(64)
        require(len(header) == 64 and header[:6] == b"\x7fELF\x02\x01"
                and struct.unpack_from("<H", header, 18)[0] == 62,
                "invalid-fixture", "minio-not-linux-amd64-elf")
        offset = struct.unpack_from("<Q", header, 32)[0]
        size, count = struct.unpack_from("<HH", header, 54)
        require(size == 56 and 0 < count <= 128 and offset + size * count <= path.stat().st_size,
                "invalid-fixture", "minio-elf-program-header-boundary")
        binary.seek(offset)
        for _ in range(count):
            require(struct.unpack_from("<I", binary.read(size))[0] != 3,
                    "invalid-fixture", "minio-dynamic-interpreter-forbidden")
    return digest


def remove_builder(run: TestRun, name: str, token: str, identity: list[str]) -> None:
    result = run.command(["docker", "container", "inspect", "--format", CONTAINER_INSPECT, name], timeout=4, check=False)
    if result.returncode:
        require(b"No such container" in result.output or b"No such object" in result.output,
                "infrastructure-timeout", "minio-builder-retirement-unverified")
        return
    found = json.loads(result.output)[0]
    require(CONTAINER_ID.fullmatch(found["Id"]) and found["Config"]["Labels"].get(OWNER_LABEL) == token
            and (not identity or found["Id"] == identity[0]),
            "invalid-fixture", "minio-builder-owner-mismatch")
    run.command(["docker", "container", "rm", "--force", found["Id"]], timeout=6)
    absent = run.command(["docker", "container", "inspect", found["Id"]], timeout=4, check=False)
    require(absent.returncode != 0 and (b"No such container" in absent.output or b"No such object" in absent.output),
            "infrastructure-timeout", "minio-builder-retirement-unverified")


def receipt_object(pairs: list[tuple[str, object]]) -> dict:
    value: dict = {}
    for key, item in pairs:
        require(key not in value, "invalid-fixture", "duplicate-minio-receipt-field")
        value[key] = item
    return value


def image_from_receipt(path: Path, command) -> str:
    sha(path, 64 * 1024)
    receipt = json.loads(path.read_bytes(), object_pairs_hook=receipt_object)
    expected = {"schemaVersion", "passed", "sourceRevision", "sourceSha256", "sourceUrl", "release",
                "builder", "goVersion", "recipeSha256", "imageId", "binarySha256", "rootfsSha256",
                "imageOwner", "source", "outputSha256", "compilerContainer", "compilerExit",
                "compilerOomKilled", "boundary", "compilerRetired"}
    require(isinstance(receipt, dict) and set(receipt) == expected
            and receipt.get("schemaVersion") == SCHEMA and receipt.get("passed") is True
            and receipt.get("sourceRevision") == REVISION and receipt.get("sourceSha256") == SOURCE_SHA256
            and receipt.get("builder") == BUILDER and receipt.get("goVersion") == GO_VERSION
            and receipt.get("recipeSha256") == recipe() and receipt.get("compilerRetired") is True
            and receipt.get("sourceUrl") == SOURCE_URL and receipt.get("release") == RELEASE
            and type(receipt.get("compilerExit")) is int and receipt["compilerExit"] == 0
            and receipt.get("compilerOomKilled") is False
            and all(isinstance(receipt.get(key), str) for key in
                    ("compilerContainer", "imageId", "imageOwner", "binarySha256", "rootfsSha256"))
            and CONTAINER_ID.fullmatch(receipt.get("compilerContainer", ""))
            and ID.fullmatch(receipt.get("imageId", ""))
            and re.fullmatch(r"[0-9a-f]{32}", receipt.get("imageOwner", ""))
            and re.fullmatch(r"[0-9a-f]{64}", receipt.get("binarySha256", ""))
            and re.fullmatch(r"[0-9a-f]{64}", receipt.get("rootfsSha256", "")),
            "invalid-fixture", "minio-fixture-receipt-mismatch")
    source, outputs = receipt["source"], receipt["outputSha256"]
    require(isinstance(source, dict)
            and set(source) == {"archiveSha256", "archiveBytes", "members", "files", "expandedBytes"}
            and source["archiveSha256"] == SOURCE_SHA256
            and type(source["archiveBytes"]) is int and source["archiveBytes"] == SOURCE_BYTES
            and all(type(source[key]) is int for key in ("members", "files", "expandedBytes"))
            and 4 <= source["files"] <= source["members"] <= 2_000
            and 0 < source["expandedBytes"] <= 256 * 1024 * 1024
            and isinstance(outputs, dict)
            and set(outputs) == {"minio", "build-info.txt", "LICENSE", "CREDITS", "ca-certificates.crt"}
            and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                    for value in outputs.values())
            and outputs["minio"] == receipt["binarySha256"],
            "invalid-fixture", "minio-fixture-evidence-mismatch")
    info = json.loads(command(["docker", "image", "inspect", receipt["imageId"]]))
    check_image(info, receipt)
    return receipt["imageId"]


def check_image(info: object, receipt: dict) -> None:
    require(isinstance(info, list) and len(info) == 1,
            "invalid-fixture", "minio-image-inspection-count")
    image = info[0]
    labels = image["Config"].get("Labels", {})
    require(image["Id"] == receipt["imageId"] and image["Os"] == "linux" and image["Architecture"] == "amd64"
            and image["Config"].get("Entrypoint") == ["/minio"]
            and image.get("RootFS", {}).get("Layers") == ["sha256:" + receipt.get("rootfsSha256", "")]
            and labels.get(OWNER_LABEL) == receipt["imageOwner"]
            and labels.get(RECIPE_LABEL) == recipe() and labels.get(BINARY_LABEL) == receipt["binarySha256"],
            "invalid-fixture", "minio-image-identity-mismatch")


def build(run: TestRun, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "source.tar.gz"
    run.artifact("fixture-builder", Path(__file__).resolve())
    run.mark("source-download")
    run.command([sys.executable, str(Path(__file__).resolve()), "--download-source", str(archive)], timeout=125)
    source = inspect_archive(archive)
    run.artifact("minio-source", archive)
    run.mark("compiler-image")
    run.command(["docker", "pull", "--platform", "linux/amd64", BUILDER], timeout=240)
    # The retained TestRun ID also identifies partial image-import outputs. They
    # remain unqualified static build artifacts if an import reply is lost.
    token = run.run_id
    container_name = "lsf-s3-compiler-" + token
    identity: list[str] = []
    run.cleanup.append(lambda: remove_builder(run, container_name, token, identity))
    run.mark("source-build")
    created = run.command([
        "docker", "create", "--pull=never", "--platform", "linux/amd64", "--name", container_name, "--label", f"{OWNER_LABEL}={token}",
        "--memory", "6g", "--memory-swap", "6g", "--cpus", "2", "--pids-limit", "256",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--log-driver", "none",
        "--tmpfs", "/work:rw,nosuid,nodev,size=536870912", "--tmpfs", "/tmp:rw,nosuid,nodev,size=2147483648",
        "--tmpfs", "/module-cache:rw,nosuid,nodev,size=2147483648",
        "--tmpfs", "/build-cache:rw,nosuid,nodev,size=1073741824",
        "--env", "CGO_ENABLED=0", "--env", "GOTOOLCHAIN=local", "--env", "GOOS=linux", "--env", "GOARCH=amd64",
        "--env", "GOMAXPROCS=2", "--env", "GOMODCACHE=/module-cache", "--env", "GOCACHE=/build-cache",
        "--env", "GOPROXY=https://proxy.golang.org", "--env", "GOSUMDB=sum.golang.org",
        "--entrypoint", "/bin/sh", BUILDER, "-c", BUILD_SCRIPT,
    ], timeout=30).output.decode().strip()
    require(CONTAINER_ID.fullmatch(created), "invalid-fixture", "minio-builder-id-invalid")
    identity.append(created)
    run.command(["docker", "cp", str(archive), created + ":/source.tar.gz"], timeout=30)
    run.command(["docker", "start", "--attach", created], timeout=1000, maximum=4 * 1024 * 1024)
    state = json.loads(run.command(["docker", "container", "inspect", "--format", CONTAINER_INSPECT, created]).output)[0]
    require(state["Id"] == created and state["State"]["Status"] == "exited"
            and state["State"]["ExitCode"] == 0 and state["State"]["OOMKilled"] is False,
            "invalid-fixture", "minio-compiler-not-cleanly-exited")
    for name in ("minio", "build-info.txt", "LICENSE", "CREDITS", "ca-certificates.crt"):
        run.command(["docker", "cp", created + ":/out/" + name, str(output / name)], timeout=30)
    binary = verify_binary(output / "minio")
    files = {p: sha(output / p, MAX_BINARY if p == "minio" else 2 * 1024 * 1024)
             for p in ("minio", "build-info.txt", "LICENSE", "CREDITS", "ca-certificates.crt")}
    run.mark("local-image-assembly")
    rootfs = run.root / "rootfs.tar"
    with tarfile.open(rootfs, "w", format=tarfile.USTAR_FORMAT) as bundle:
        for local, target in (("minio", "minio"), ("LICENSE", "licenses/minio/LICENSE"),
                              ("CREDITS", "licenses/minio/CREDITS"),
                              ("ca-certificates.crt", "etc/ssl/certs/ca-certificates.crt")):
            data = (output / local).read_bytes()
            entry = tarfile.TarInfo(target)
            entry.size, entry.mode, entry.mtime = len(data), 0o755 if local == "minio" else 0o644, 0
            bundle.addfile(entry, io.BytesIO(data))
    rootfs_digest = sha(rootfs, MAX_BINARY + 4 * 1024 * 1024)
    run.artifact("minio-rootfs", rootfs, MAX_BINARY + 4 * 1024 * 1024)
    imported = run.command(["docker", "image", "import", "--platform", "linux/amd64",
                            "--change", 'ENTRYPOINT ["/minio"]', "--change", "ENV HOME=/tmp",
                            "--change", f"LABEL {OWNER_LABEL}={token}",
                            "--change", f"LABEL {RECIPE_LABEL}={recipe()}",
                            "--change", f"LABEL {BINARY_LABEL}={binary}", str(rootfs)], timeout=60).output.decode().strip()
    require(ID.fullmatch(imported), "invalid-fixture", "minio-import-id-invalid")
    receipt = {"schemaVersion": SCHEMA, "passed": True, "sourceRevision": REVISION,
            "sourceSha256": SOURCE_SHA256, "sourceUrl": SOURCE_URL, "release": RELEASE,
            "builder": BUILDER, "goVersion": GO_VERSION, "recipeSha256": recipe(),
            "imageId": imported, "binarySha256": binary, "rootfsSha256": rootfs_digest,
            "imageOwner": token, "source": source, "outputSha256": files,
            "compilerContainer": created, "compilerExit": 0, "compilerOomKilled": False,
            "boundary": "Local test fixture only; no registry publication, old-image equivalence, signed upstream commit, or whole-build hermeticity claim. The immutable image is a retained build output."}
    check_image(json.loads(run.command(["docker", "image", "inspect", imported]).output), receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--output", type=Path)
    operation.add_argument("--download-source", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.download_source is not None:
        download_source(args.download_source)
        return 0
    output = args.output.resolve()
    owner = TestRun("s3-fixture-build", {"timeoutSeconds": 1500}, repo=ROOT,
                    diagnostic_root=output.parent / "s3-fixture-diagnostics")
    with owner:
        if os.environ.get("GITHUB_SHA"):
            owner.source_identity()
        receipt = build(owner, output)
    # Publish success only AFTER the compiler's immutable-ID retirement succeeds.
    receipt["compilerRetired"] = True
    path = output / "fixture.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"schemaVersion": SCHEMA, "imageId": receipt["imageId"], "passed": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
