"""Explicit Windows kind setup; no acquisition or mutation occurs on import.

Commands start suspended in an owned kill-on-close Windows Job Object. The
setup is one-shot: failures retain the cluster, private credentials and files.
The caller reviews the receipt before any benchmark or separate cleanup.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import time
from urllib.request import urlopen
from urllib.parse import urlsplit, urlunsplit
import uuid

KIND_VERSION = "v0.33.0"
KIND_URL = f"https://github.com/kubernetes-sigs/kind/releases/download/{KIND_VERSION}/kind-windows-amd64"
KIND_SHA256 = "4b22adaa135368c5a465d56bbd8e520cbea87272a06ca00b6078e7b81515c9fc"
KIND_BYTES = 10_844_160
NODE_IMAGE = "kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"
IMAGE_PREFIX = "lsf111-images-fc45a33903fb46eea767"
IMAGE_IDS = {
    "lsf": "sha256:ae339a3194de7528217ba6352d28391425d71b584d89546808de4bd40e5b5eb3",
    "native": "sha256:2d42cbc8194c46ce1c9614ac3bac94dd9e8c44df77ce75db692081cd610154b4",
    "client": "sha256:a0b4d53de03366327b428e80b3e071abbe87b5519717c58839f954cb038d77d7",
}
HEADROOM = 2 * 1024**3
MAX_TAR = 512 * 1024**2
MAX_OUTPUT = 8 * 1024**2
MAX_TOTAL = 1024**3
SCHEMA = "latent.optimization.kubernetes-setup.v1"
EXCLUDED_GENERATED_PATH = "sdk/dotnet/Latent.Sdk/target/"


def _require(condition, message):
    if not condition:
        raise ValueError("kubernetes-setup-" + message)


def _regular(path):
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode)
             and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
             "regular-file")
    return info


def _hash(path, maximum=MAX_OUTPUT):
    _require(_regular(path).st_size <= maximum, "file-bound")
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while block := stream.read(65536):
            count += len(block)
            _require(count <= maximum, "file-growth-bound")
            digest.update(block)
    return {"bytes": str(count), "sha256": "sha256:" + digest.hexdigest()}


def _reference(path, root, maximum=MAX_OUTPUT):
    return {"path": path.relative_to(root).as_posix(), **_hash(path, maximum)}


def _json(path, value):
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    _require(len(data) <= MAX_OUTPUT, "json-bound")
    with path.open("xb") as stream:
        stream.write(data)


def _space(root):
    free = shutil.disk_usage(root).free
    _require(free >= HEADROOM, "disk-headroom")
    return free


def _usage(root):
    total, count, pending = 0, 0, [(root, 0)]
    while pending:
        directory, depth = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                info = entry.stat(follow_symlinks=False)
                _require(count <= 512 and not stat.S_ISLNK(info.st_mode)
                         and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                         "retained-entry")
                if stat.S_ISDIR(info.st_mode):
                    _require(depth < 4, "retained-depth")
                    pending.append((Path(entry.path), depth + 1))
                else:
                    maximum = (MAX_TAR if Path(entry.path) == root / "images.tar" else
                               12 * 1024**2 if Path(entry.path) == root / "private/kind.exe" else MAX_OUTPUT)
                    _require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum, "retained-file-bound")
                    total += info.st_size
                    _require(total <= MAX_TOTAL, "retained-total-bound")
    return total


class _BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t), ("active_process_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [("times", ctypes.c_int64 * 4), ("faults", wintypes.DWORD),
                ("total", wintypes.DWORD), ("active", wintypes.DWORD), ("terminated", wintypes.DWORD)]


class _Thread(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("id", wintypes.DWORD),
                ("owner", wintypes.DWORD), ("priority", wintypes.LONG), ("delta", wintypes.LONG),
                ("flags", wintypes.DWORD)]


class _Job:
    """Only a suspended owned child enters this job; breakaway is not enabled."""
    def __init__(self):
        _require(os.name == "nt", "windows-required")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Thread32First": ([wintypes.HANDLE, ctypes.POINTER(_Thread)], wintypes.BOOL),
            "Thread32Next": ([wintypes.HANDLE, ctypes.POINTER(_Thread)], wintypes.BOOL),
            "OpenThread": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
            "GetProcessTimes": ([wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            getattr(self.api, name).argtypes = args
            getattr(self.api, name).restype = result
        self.handle = self.api.CreateJobObjectW(None, None)
        _require(bool(self.handle), "job-create")
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign_and_resume(self, process):
        handle = wintypes.HANDLE(int(process._handle))
        _require(self.api.AssignProcessToJobObject(self.handle, handle), "job-assignment")
        times = [wintypes.FILETIME() for _ in range(4)]
        _require(self.api.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)), "process-times")
        created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        snapshot = self.api.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        _require(snapshot not in (None, ctypes.c_void_p(-1).value), "thread-snapshot")
        found = []
        try:
            row = _Thread(size=ctypes.sizeof(_Thread))
            more = self.api.Thread32First(snapshot, ctypes.byref(row))
            while more:
                if row.owner == process.pid:
                    found.append(row.id)
                row.size = ctypes.sizeof(_Thread)
                more = self.api.Thread32Next(snapshot, ctypes.byref(row))
            _require(len(found) == 1, "suspended-initial-thread")
            thread = self.api.OpenThread(2, False, found[0])  # THREAD_SUSPEND_RESUME
            _require(bool(thread), "initial-thread-open")
            try:
                _require(self.api.ResumeThread(thread) == 1, "initial-thread-resume")
            finally:
                self.api.CloseHandle(thread)
        finally:
            self.api.CloseHandle(snapshot)
        return str(created)

    def accounting(self):
        value = _Accounting()
        _require(self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(value), ctypes.sizeof(value), None),
                 "job-accounting")
        return {"active": value.active, "total": value.total, "terminated": value.terminated}

    def terminate(self):
        _require(self.api.TerminateJobObject(self.handle, 1), "job-terminate")

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def _command(argv, directory, repository, env, root, *, timeout=60):
    """Retain original bounded stdout/stderr, and close the entire owned job."""
    directory.mkdir()
    receipt = {"argv": list(argv), "cwd": str(repository), "started_nanos": str(time.monotonic_ns()),
               "timeout_seconds": timeout, "cleanup_timeout_seconds": 10,
               "process_id": None, "creation_time_100ns": None,
               "exit_code": None, "reaped": False, "output_closed": False, "job_empty": False,
               "failure": None, "disk_free_before": str(_space(root)), "minimum_disk_free": None,
               "executable": {"path": argv[0], **_hash(Path(argv[0]), 256 * 1024**2)}}
    minimum = int(receipt["disk_free_before"])
    process = job = None
    failure = None
    streams = []
    try:
        streams = [(directory / name).open("xb", buffering=0) for name in ("stdout.bin", "stderr.bin")]
        job = _Job()
        process = subprocess.Popen(argv, cwd=repository, env=env, stdin=subprocess.DEVNULL,
                                   stdout=streams[0], stderr=streams[1], close_fds=True,
                                   creationflags=0x00000004 | 0x08000000)  # suspended; hidden
        receipt["process_id"] = process.pid
        receipt["creation_time_100ns"] = job.assign_and_resume(process)
        until = int(receipt["started_nanos"]) + timeout * 10**9
        while True:
            free = shutil.disk_usage(root).free
            minimum = min(minimum, free)
            _require(free >= HEADROOM, "disk-headroom")
            _usage(root)
            _require(sum(os.fstat(stream.fileno()).st_size for stream in streams) <= MAX_OUTPUT,
                     "command-output-bound")
            _require(time.monotonic_ns() < until, "command-deadline")
            if process.poll() is not None and job.accounting()["active"] == 0:
                break
            time.sleep(0.05)
        process.wait(timeout=1)
        _require(process.returncode == 0, "command-exit")
    except BaseException as error:
        failure = error
        receipt["failure"] = {"type": type(error).__name__, "message": str(error)[:2048]}
    finally:
        try:
            if process is not None:
                if process.poll() is None:
                    process.kill()  # also covers failure before job assignment
                if job is not None:
                    job.terminate()
                process.wait(timeout=10)
                receipt.update(exit_code=process.returncode, reaped=True)
                until = time.monotonic_ns() + 10 * 10**9
                while job is not None and job.accounting()["active"] and time.monotonic_ns() < until:
                    time.sleep(0.01)
                if job is not None:
                    receipt["job"] = job.accounting()
                    receipt["job_empty"] = receipt["job"]["active"] == 0
        finally:
            if job is not None:
                job.close()
            for stream in streams:
                stream.close()
            receipt["output_closed"] = all(stream.closed for stream in streams)
            receipt["finished_nanos"] = str(time.monotonic_ns())
            receipt["minimum_disk_free"] = str(minimum)
            for name in ("stdout", "stderr"):
                path = directory / (name + ".bin")
                if path.exists():
                    # Retain an oversized failure unchanged; never truncate it.
                    receipt[name] = _reference(path, root, MAX_TOTAL)
            _json(directory / "receipt.json", receipt)
    if failure is not None:
        raise failure
    _require(receipt["job_empty"] and receipt["reaped"] and receipt["output_closed"], "command-cleanup")
    return receipt


def _acquire_kind(root):
    path = root / "private/kind.exe"
    receipt = {"url": KIND_URL, "expected_sha256": KIND_SHA256, "expected_bytes": KIND_BYTES,
               "maximum_bytes": 12 * 1024**2, "started_nanos": str(time.monotonic_ns()),
               "response_closed": False, "file_closed": False, "failure": None}
    response = None
    try:
        _require(_space(root) >= HEADROOM + 12 * 1024**2, "kind-disk-reservation")
        response = urlopen(KIND_URL, timeout=10)
        final = urlsplit(response.geturl())
        receipt.update(status=response.status, final_url=urlunsplit((final.scheme, final.netloc, final.path, "", "")))
        _require(response.status == 200 and final.scheme == "https" and final.username is None, "kind-http-status")
        length = response.headers.get("Content-Length")
        _require(length is None or int(length) == KIND_BYTES, "kind-http-size")
        digest, count = hashlib.sha256(), 0
        with path.open("xb") as stream:
            while block := response.read(65536):
                _require(time.monotonic_ns() - int(receipt["started_nanos"]) <= 180 * 10**9, "kind-download-deadline")
                _require(_space(root) >= HEADROOM + len(block), "kind-download-headroom")
                count += len(block)
                _require(count <= 12 * 1024**2, "kind-download-bound")
                stream.write(block)
                digest.update(block)
        receipt["file_closed"] = True
        _require(count == KIND_BYTES and digest.hexdigest() == KIND_SHA256, "kind-download-identity")
        receipt["binary"] = _reference(path, root, 12 * 1024**2)
    except BaseException as error:
        receipt["failure"] = {"type": type(error).__name__, "message": str(error)[:2048]}
        raise
    finally:
        if response is not None:
            response.close()
            receipt["response_closed"] = True
        receipt["file_closed"] = True
        receipt["finished_nanos"] = str(time.monotonic_ns())
        if path.exists():
            receipt["retained_file"] = _reference(path, root, 12 * 1024**2)
        _json(root / "kind-download.json", receipt)
    return path


def configuration(owner):
    _require(re.fullmatch(r"lsf-112-[0-9a-f]{12}", owner) is not None, "owner-name")
    return {"kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4", "name": owner,
            "networking": {"apiServerAddress": "127.0.0.1", "ipFamily": "ipv4",
                           "podSubnet": "10.244.0.0/16", "serviceSubnet": "10.96.0.0/16",
                           "disableDefaultCNI": False, "kubeProxyMode": "iptables"},
            "nodes": [{"role": "control-plane", "image": NODE_IMAGE,
                       "kubeadmConfigPatches": ["kind: KubeletConfiguration\napiVersion: kubelet.config.k8s.io/v1beta1\npodPidsLimit: 512\n"]},
                      {"role": "worker", "image": NODE_IMAGE,
                       "labels": {"latent.benchmark.worker": owner}}]}


def _outer_images(rows):
    _require(isinstance(rows, list) and len(rows) == 3, "image-count")
    result = {}
    for kind, row in zip(IMAGE_IDS, rows):
        descriptor = row.get("Descriptor", {})
        _require(row.get("Id") == IMAGE_IDS[kind] and descriptor.get("digest") == IMAGE_IDS[kind]
                 and descriptor.get("mediaType") == "application/vnd.oci.image.manifest.v1+json"
                 and row.get("Os") == "linux" and row.get("Architecture") == "amd64"
                 and row.get("Config", {}).get("Entrypoint") ==
                 ["/opt/lsf/" + ("optimization-client" if kind == "client" else "optimization-container")],
                 "original-image-identity")
        result[kind] = row
    return result


def _network_space(rows):
    _require(isinstance(rows, list) and len(rows) <= 64, "network-count")
    selected = [ipaddress.ip_network(value) for value in ("10.244.0.0/16", "10.96.0.0/16")]
    for row in rows:
        for item in row.get("IPAM", {}).get("Config", []) or []:
            if "Subnet" in item:
                subnet = ipaddress.ip_network(item["Subnet"])
                _require(all(subnet.version != owned.version or not subnet.overlaps(owned)
                             for owned in selected), "network-cidr-overlap")


def _archive_images(path, original):
    """Verify the original OCI manifests/configs/layers in the exact saved tar."""
    reference = _hash(path, MAX_TAR)
    with tarfile.open(path, "r:") as archive:
        members = {}
        for member in archive:
            _require(len(members) < 4096 and member.name not in members
                     and not member.name.startswith(("/", "\\")) and "\\" not in member.name
                     and all(part not in ("..", "") for part in member.name.rstrip("/").split("/"))
                     and (member.isfile() or member.isdir()) and 0 <= member.size <= 256 * 1024**2,
                     "image-archive-member")
            members[member.name] = member
        _require("oci-layout" in members and "index.json" in members, "image-archive-requires-oci")
        for name in ("oci-layout", "index.json"):
            _require(members[name].isfile() and members[name].size <= MAX_OUTPUT, "oci-index-bound")
        with archive.extractfile(members["oci-layout"]) as stream:
            _require(json.load(stream).get("imageLayoutVersion") == "1.0.0", "oci-layout-version")
        with archive.extractfile(members["index.json"]) as stream:
            index_bytes = stream.read(MAX_OUTPUT + 1)
            index = json.loads(index_bytes)
        index_digest = "sha256:" + hashlib.sha256(index_bytes).hexdigest()
        _require(index.get("schemaVersion") == 2 and isinstance(index.get("manifests"), list)
                 and 1 <= len(index["manifests"]) <= 16, "oci-index")
        _require(all(any(item.get("digest") == row["Id"] for item in index["manifests"])
                     for row in original.values()), "oci-original-index-membership")

        def blob(digest, maximum=MAX_OUTPUT):
            _require(re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None, "oci-digest")
            item = members.get("blobs/sha256/" + digest[7:])
            _require(item is not None and item.isfile() and item.size <= maximum, "oci-blob")
            with archive.extractfile(item) as stream:
                value = stream.read(maximum + 1)
            _require(len(value) == item.size and hashlib.sha256(value).hexdigest() == digest[7:], "oci-blob-hash")
            return value

        checked_layers, result = set(), {}
        for kind, row in original.items():
            manifest_bytes = blob(row["Id"])
            _require(len(manifest_bytes) == row["Descriptor"]["size"], "oci-manifest-size")
            manifest = json.loads(manifest_bytes)
            _require(manifest.get("schemaVersion") == 2 and 1 <= len(manifest.get("layers", [])) <= 64,
                     "oci-manifest")
            config_digest = manifest["config"]["digest"]
            config_bytes = blob(config_digest)
            _require(len(config_bytes) == manifest["config"]["size"], "oci-config-size")
            config = json.loads(config_bytes)
            _require(config.get("rootfs", {}).get("diff_ids") == row["RootFS"]["Layers"]
                     and len(config["rootfs"]["diff_ids"]) == len(manifest["layers"])
                     and config.get("os") == "linux" and config.get("architecture") == "amd64"
                     and config.get("config", {}).get("Entrypoint") == row["Config"]["Entrypoint"],
                     "oci-original-config")
            for layer in manifest["layers"]:
                digest = layer["digest"]
                if digest in checked_layers:
                    continue
                _require(re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None, "oci-layer-digest")
                member = members.get("blobs/sha256/" + digest[7:])
                _require(member is not None and member.isfile() and member.size == layer["size"], "oci-layer-size")
                actual = hashlib.sha256()
                with archive.extractfile(member) as stream:
                    while block := stream.read(65536):
                        actual.update(block)
                _require(actual.hexdigest() == digest[7:], "oci-layer-hash")
                checked_layers.add(digest)
            tag = IMAGE_PREFIX + ":" + kind
            index_members = [item for item in index["manifests"] if item.get("digest") == row["Id"]
                             and item.get("annotations", {}).get("io.containerd.image.name") ==
                             "docker.io/library/" + tag]
            _require(len(index_members) == 1, "oci-original-tag-membership")
            result[kind] = {"manifest_digest": row["Id"], "config_digest": config_digest,
                            "config": config, "layers": manifest["layers"], "tag": tag,
                            "archive_index_digest": index_digest, "archive_index_entry": index_members[0]}
    return {"archive": reference, "images": result,
            "index": {"sha256": index_digest, "bytes": str(len(index_bytes)), "document": index}}


def _imported_image(value, expected, *, live_index=None, live_target=None):
    status, info = value.get("status", {}), value.get("info", {})
    digests = status.get("repoDigests")
    _require(isinstance(digests, list) and len(digests) <= 32
             and all(isinstance(name, str) and len(name) <= 1024 for name in digests), "imported-repo-digests")
    roots = {name.rsplit("@", 1)[-1] for name in digests}
    scope = "manifest"
    if expected["manifest_digest"] not in roots:
        scope = "archive-index"
        _require(isinstance(live_index, bytes)
                 and "sha256:" + hashlib.sha256(live_index).hexdigest() == expected.get("archive_index_digest")
                 and expected.get("archive_index_entry") in json.loads(live_index).get("manifests", []),
                 "imported-index-binding")
        if digests:
            _require(expected["archive_index_digest"] in roots, "imported-index-binding")
        else:
            # CRI can omit repoDigests for an archive-loaded tagged image. The
            # separately read containerd target must still be its exact manifest.
            scope = "not-reported"
            _require(live_target == {"media_type": "application/vnd.oci.image.manifest.v1+json",
                                     "digest": expected["manifest_digest"]}, "imported-tag-manifest-binding")
    _require(status.get("id") == expected["config_digest"]
             and "docker.io/library/" + expected["tag"] in status.get("repoTags", [])
             and info.get("imageSpec") == expected["config"], "imported-image-binding")
    return {"status_id": status["id"], "repo_digests": status["repoDigests"],
            "repo_tags": status.get("repoTags", []), "manifest_digest": expected["manifest_digest"],
            "config_digest": expected["config_digest"], "repo_digest_scope": scope,
            "archive_index_digest": expected.get("archive_index_digest")}


def _verify_runtime_images(steps, docker, worker, transfer):
    """Only read immutable containerd content/metadata and CRI image status."""
    base = [*docker, "exec", worker]
    listing = steps.run("runtime-images", [*base, "ctr", "--namespace", "k8s.io", "images", "list"])
    targets = {}
    for line in listing.splitlines():
        fields = line.split()
        if fields and fields[0] in {"docker.io/library/" + row["tag"] for row in transfer["images"].values()}:
            _require(len(fields) >= 3 and fields[0] not in targets, "runtime-image-target")
            targets[fields[0]] = {"media_type": fields[1], "digest": fields[2]}
    _require(len(targets) == len(transfer["images"]), "runtime-image-target-count")
    content = [*base, "ctr", "--namespace", "k8s.io", "content", "get"]
    index = steps.run("runtime-index", [*content, transfer["index"]["sha256"]], parse="bytes")
    _require("sha256:" + hashlib.sha256(index).hexdigest() == transfer["index"]["sha256"]
             and json.loads(index) == transfer["index"]["document"], "runtime-index-bytes")
    result = {}
    for kind, expected in transfer["images"].items():
        target = targets["docker.io/library/" + expected["tag"]]
        types = {expected["manifest_digest"]: "application/vnd.oci.image.manifest.v1+json",
                 expected["archive_index_digest"]: "application/vnd.oci.image.index.v1+json"}
        _require(target["digest"] in types and target["media_type"] == types[target["digest"]],
                 "runtime-target-digest")
        manifest = steps.run("runtime-manifest-" + kind, [*content, expected["manifest_digest"]], parse="bytes")
        config = steps.run("runtime-config-" + kind, [*content, expected["config_digest"]], parse="bytes")
        _require("sha256:" + hashlib.sha256(manifest).hexdigest() == expected["manifest_digest"]
                 and json.loads(manifest)["config"]["digest"] == expected["config_digest"]
                 and json.loads(manifest)["layers"] == expected["layers"]
                 and "sha256:" + hashlib.sha256(config).hexdigest() == expected["config_digest"]
                 and json.loads(config) == expected["config"], "runtime-manifest-config-graph")
        actual = steps.run("import-" + kind, [*base, "crictl", "inspecti", expected["tag"]], parse=True)
        result[kind] = {**_imported_image(actual, expected, live_index=index, live_target=target), "containerd_target": target,
                        "rootfs_diff_ids": actual["info"]["imageSpec"]["rootfs"]["diff_ids"],
                        "live_layer_bytes_rehashed": False}
    return result


class _Steps:
    def __init__(self, root, repository):
        self.root, self.repository, self.rows = root, repository, []
        self.env = dict(os.environ)
        for key in ("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "KUBECONFIG"):
            self.env.pop(key, None)
        self.env.update(DOCKER_CONTEXT="desktop-linux", KIND_EXPERIMENTAL_PROVIDER="docker",
                        TEMP=str(root / "private/tmp"), TMP=str(root / "private/tmp"))

    def run(self, name, argv, *, timeout=60, parse=False):
        directory = self.root / "commands" / f"{len(self.rows):02d}-{name}"
        try:
            _command([str(item) for item in argv], directory, self.repository, self.env, self.root, timeout=timeout)
        finally:
            if (directory / "receipt.json").exists():
                self.rows.append(_reference(directory / "receipt.json", self.root))
                _json(self.root / "commands" / f"completed-{len(self.rows):02d}.json", self.rows)
        data = (directory / "stdout.bin").read_bytes()
        if parse == "bytes":
            return data
        return json.loads(data) if parse else data.decode("utf-8", errors="strict").strip()

    def source(self, git, label, *, repository=None):
        repository = repository or self.repository
        prefix = [git, "-C", repository]
        _require(not self.run(label + "-generated-untracked", [*prefix, "ls-files", "--", EXCLUDED_GENERATED_PATH]),
                 "excluded-generated-tree-is-tracked")
        _require(not self.run(label + "-clean", [*prefix, "status", "--porcelain", "--untracked-files=all",
                         "--", ".", ":(exclude)" + EXCLUDED_GENERATED_PATH + "**"]),
                 "source-dirty")
        commit = self.run(label + "-commit", [*prefix, "rev-parse", "HEAD"])
        tree = self.run(label + "-tree", [*prefix, "rev-parse", "HEAD^{tree}"])
        _require(all(re.fullmatch(r"[0-9a-f]{40}", item) for item in (commit, tree)), "source-identity")
        return {"commit": commit, "tree": tree, "clean": True,
                "excluded_generated_path": EXCLUDED_GENERATED_PATH,
                "cargo_lock": _hash(repository / "Cargo.lock"),
                "setup_source": _hash(repository / "tools/optimization_kubernetes/setup.py")}


def prepare(repository: Path, root: Path) -> dict:
    """Acquire, create and import once; caller owns all later cleanup/campaigns."""
    _require(os.name == "nt", "windows-required")
    repository, root = repository.resolve(), root.absolute()
    _require(root.parent == repository / "target/phase1-extension"
             and re.fullmatch(r"issue112-setup-[0-9]{2}", root.name) is not None and not root.exists(),
             "fresh-owned-root")
    for path in (root, *root.parents):
        if path.exists():
            info = path.lstat()
            _require(not stat.S_ISLNK(info.st_mode)
                     and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                     "root-reparse")
    _space(root.parent)
    root.mkdir()
    for name in ("commands", "private", "private/tmp"):
        (root / name).mkdir()
    owner = "lsf-112-" + uuid.uuid4().hex[:12]
    receipt = {"schema": SCHEMA, "owner": owner, "status": "incomplete", "root": str(root),
               "private_kubeconfig": "private/kubeconfig", "kubeconfig_publishable": False,
               "context": "kind-" + owner, "started_nanos": str(time.monotonic_ns()),
               "headroom_bytes": str(HEADROOM), "failure": None}
    _json(root / "ownership.json", receipt)
    steps = _Steps(root, repository)
    try:
        tools = {name: shutil.which(name) for name in ("git", "docker", "kubectl")}
        _require(all(tools.values()), "required-local-tools")
        tools = {name: str(Path(path).resolve()) for name, path in tools.items()}
        _require(all(Path(path).suffix.lower() == ".exe" for path in tools.values()), "native-tool-executable")
        receipt["source_before"] = steps.source(tools["git"], "before")
        docker = [tools["docker"], "--context", "desktop-linux"]
        receipt["docker_version"] = steps.run("docker-version", [*docker, "version", "--format", "{{json .}}"], parse=True)
        server = receipt["docker_version"].get("Server", {})
        _require(server.get("Version") == "29.7.2" and server.get("Os") == "linux"
                 and server.get("Arch") == "amd64", "docker-server-identity")
        receipt["kubectl_version"] = steps.run("kubectl-version", [tools["kubectl"], "version", "--client", "-o", "json"], parse=True)
        _require(receipt["kubectl_version"].get("clientVersion", {}).get("gitVersion") == "v1.36.1",
                 "kubectl-version")
        original = _outer_images(steps.run("original-images", [*docker, "image", "inspect",
                                  *(IMAGE_PREFIX + ":" + key for key in IMAGE_IDS)], parse=True))
        receipt["original_images"] = original
        kind = _acquire_kind(root)
        receipt["kind_version"] = steps.run("kind-version", [kind, "version"])
        _require(KIND_VERSION in receipt["kind_version"], "kind-version")
        steps.run("node-pull", [*docker, "pull", "--platform", "linux/amd64", NODE_IMAGE], timeout=600)
        node_image = steps.run("node-image", [*docker, "image", "inspect", NODE_IMAGE], parse=True)
        _require(len(node_image) == 1 and any(value.endswith("@" + NODE_IMAGE.split("@", 1)[1])
                                             for value in node_image[0].get("RepoDigests", []))
                 and node_image[0].get("Os") == "linux" and node_image[0].get("Architecture") == "amd64", "node-image")
        receipt["node_image"] = node_image[0]
        _require(not steps.run("cluster-absent", [*docker, "ps", "-a", "--filter",
                     "label=io.x-k8s.kind.cluster=" + owner, "--format", "{{.ID}}"]), "cluster-already-exists")
        network_ids = steps.run("networks-before", [*docker, "network", "ls", "--format", "{{.ID}}"])
        network_ids = network_ids.splitlines()
        _require(1 <= len(network_ids) <= 64 and all(re.fullmatch(r"[0-9a-f]{12,64}", item)
                                                   for item in network_ids), "network-identities")
        receipt["networks_before"] = steps.run("network-inspect", [*docker, "network", "inspect", *network_ids], parse=True)
        _network_space(receipt["networks_before"])
        _json(root / "kind-config.json", configuration(owner))
        kubeconfig = root / "private/kubeconfig"
        steps.run("cluster-create", [kind, "create", "cluster", "--name", owner, "--config", root / "kind-config.json",
                                     "--kubeconfig", kubeconfig, "--wait", "180s", "--retain"], timeout=300)
        receipt["private_kubeconfig_identity"] = _reference(kubeconfig, root, 128 * 1024)
        nodes = steps.run("node-inspect", [*docker, "inspect", owner + "-control-plane", owner + "-worker"], parse=True)
        _require(len(nodes) == 2, "node-count")
        owned_nodes = []
        for index, node in enumerate(nodes):
            role = "control-plane" if index == 0 else "worker"
            labels = node.get("Config", {}).get("Labels", {})
            _require(re.fullmatch(r"[0-9a-f]{64}", node.get("Id", "")) is not None
                     and node.get("Name") == "/" + owner + "-" + role
                     and labels.get("io.x-k8s.kind.cluster") == owner
                     and labels.get("io.x-k8s.kind.role") == role and node.get("State", {}).get("Running") is True,
                     "node-ownership")
            owned_nodes.append({"role": role, "name": owner + "-" + role, "container_id": node["Id"],
                                "labels": labels, "image_id": node["Image"]})
        receipt["nodes"] = owned_nodes
        _json(root / "cluster-created.json", receipt)
        for node in owned_nodes:
            cpu, memory = ("2", "4g") if node["role"] == "control-plane" else ("8", "12g")
            steps.run("node-ceiling-" + node["role"], [*docker, "update", "--cpus", cpu, "--memory", memory,
                       "--memory-swap", memory, node["container_id"]])
            effective = steps.run("node-ceiling-inspect-" + node["role"],
                                  [*docker, "inspect", node["container_id"]], parse=True)
            expected_memory = (4 if node["role"] == "control-plane" else 12) * 1024**3
            _require(len(effective) == 1 and effective[0]["Id"] == node["container_id"]
                     and effective[0]["HostConfig"].get("NanoCpus") == int(cpu) * 10**9
                     and effective[0]["HostConfig"].get("Memory") == expected_memory
                     and effective[0]["HostConfig"].get("MemorySwap") == expected_memory, "node-effective-ceiling")
            node["outer_limits"] = {"cpu_nano": int(cpu) * 10**9, "memory_bytes": expected_memory,
                                    "memory_plus_swap_bytes": expected_memory}
            observed = steps.run("kubelet-" + node["role"], [*docker, "exec", node["container_id"],
                                  "cat", "/var/lib/kubelet/config.yaml"])
            _require(len(re.findall(r"(?m)^podPidsLimit: 512\s*$", observed)) == 1, "pod-pid-policy")
        kubectl = [tools["kubectl"], "--kubeconfig", kubeconfig, "--context", "kind-" + owner, "--request-timeout=10s"]
        observed_nodes = steps.run("kubernetes-nodes", [*kubectl, "get", "nodes", "-o", "json"], parse=True)
        _require(len(observed_nodes.get("items", [])) == 2, "kubernetes-node-count")
        for node in owned_nodes:
            matches = [item for item in observed_nodes["items"] if item["metadata"]["name"] == node["name"]]
            _require(len(matches) == 1 and any(item["type"] == "Ready" and item["status"] == "True"
                     for item in matches[0]["status"]["conditions"]), "kubernetes-node-ready")
            node["uid"] = matches[0]["metadata"]["uid"]
            _require(re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", node["uid"]), "node-uid")
            node["node_info"] = matches[0]["status"]["nodeInfo"]
            if node["role"] == "worker":
                _require(matches[0]["metadata"].get("labels", {}).get("latent.benchmark.worker") == owner,
                         "worker-placement-label")
        _require(_space(root) >= HEADROOM + MAX_TAR, "image-export-reservation")
        transfer = root / "images.tar"
        steps.run("images-save", [*docker, "image", "save", "--output", transfer,
                                  *(IMAGE_PREFIX + ":" + key for key in IMAGE_IDS)], timeout=600)
        receipt["image_archive"] = _archive_images(transfer, original)
        _json(root / "image-transfer.json", receipt["image_archive"])
        steps.run("images-load", [kind, "load", "image-archive", transfer, "--name", owner,
                                  "--nodes", owner + "-worker"], timeout=600)
        worker = owned_nodes[1]["container_id"]
        receipt["imported_images"] = _verify_runtime_images(steps, docker, worker, receipt["image_archive"])
        after_images = _outer_images(steps.run("original-images-after", [*docker, "image", "inspect",
                                    *(IMAGE_PREFIX + ":" + key for key in IMAGE_IDS)], parse=True))
        _require(after_images == original, "original-images-changed")
        receipt["source_after"] = steps.source(tools["git"], "after")
        _require(receipt["source_after"] == receipt["source_before"], "source-changed")
        receipt.update(status="ready-for-campaign-preflight", commands=steps.rows,
                       disk_free_after=str(_space(root)), retained_bytes=str(_usage(root)))
    except BaseException as error:
        receipt["failure"] = {"type": type(error).__name__, "message": str(error)[:2048]}
        receipt["commands"] = steps.rows
        raise
    finally:
        receipt["finished_nanos"] = str(time.monotonic_ns())
        _json(root / "setup.json", receipt)
    return receipt


def _retained_reference(root, reference):
    relative = reference.get("path", "")
    _require(isinstance(relative, str) and re.fullmatch(
        r"(?:commands/[0-9]{2}-[a-z0-9-]+/(?:receipt.json|stdout.bin|stderr.bin)|private/kubeconfig)", relative),
        "original-reference-path")
    path = root / relative
    for parent in (path.parent, *path.parent.parents):
        if parent == root.parent:
            break
        info = parent.lstat()
        _require(stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0)
                 & stat.FILE_ATTRIBUTE_REPARSE_POINT, "original-reference-parent")
    _require(_reference(path, root) == reference, "original-reference-hash")
    return path


def _original_attempt(root):
    original_path, transfer_path = root / "setup.json", root / "image-transfer.json"
    references = {"original_setup": {"path": str(original_path), **_hash(original_path)},
                  "original_image_transfer": {"path": str(transfer_path), **_hash(transfer_path)}}
    original = json.loads(original_path.read_bytes())
    transfer = json.loads(transfer_path.read_bytes())
    _require(original.get("schema") == SCHEMA and original.get("status") == "incomplete"
             and original.get("root") == str(root)
             and original.get("failure", {}).get("message") == "kubernetes-setup-imported-image-binding",
             "original-failed-import-attempt")
    _require(re.fullmatch(r"lsf-112-[0-9a-f]{12}", original.get("owner", ""))
             and original.get("context") == "kind-" + original["owner"]
             and original.get("image_archive") == transfer
             and original.get("private_kubeconfig") == "private/kubeconfig"
             and original.get("kubeconfig_publishable") is False, "original-setup-binding")
    _retained_reference(root, original["private_kubeconfig_identity"])
    commands = original.get("commands", [])
    _require(isinstance(commands, list) and 1 <= len(commands) <= 64
             and len({row["path"] for row in commands}) == len(commands), "original-command-count")
    loaded = []
    for reference in commands:
        command = json.loads(_retained_reference(root, reference).read_bytes())
        _require(command.get("exit_code") == 0 and command.get("failure") is None
                 and all(command.get(key) is True for key in ("reaped", "output_closed", "job_empty")),
                 "original-command-cleanup")
        for stream in ("stdout", "stderr"):
            _retained_reference(root, command[stream])
        if reference["path"].endswith("-images-load/receipt.json"):
            loaded.append(reference)
    _require(len(loaded) == 1, "original-image-load-receipt")
    return original, transfer, {**references, "original_image_load": loaded[0]}


def _resume_nodes(steps, docker, kubectl, original):
    nodes = original.get("nodes", [])
    _require(len(nodes) == 2 and [node.get("role") for node in nodes] == ["control-plane", "worker"]
             and len({node.get("container_id") for node in nodes}) == 2
             and all(re.fullmatch(r"[0-9a-f]{64}", node.get("container_id", "")) for node in nodes),
             "resume-node-set")
    actual = steps.run("owned-nodes", [*docker, "inspect", *(node["container_id"] for node in nodes)], parse=True)
    _require(len(actual) == 2, "resume-node-count")
    for expected, node in zip(nodes, actual):
        limits = expected["outer_limits"]
        labels = node.get("Config", {}).get("Labels", {})
        _require(node.get("Id") == expected["container_id"] and node.get("Image") == expected["image_id"]
                 and node.get("Name") == "/" + expected["name"]
                 and node.get("State", {}).get("Running") is True and labels == expected["labels"]
                 and labels.get("io.x-k8s.kind.cluster") == original["owner"]
                 and labels.get("io.x-k8s.kind.role") == expected["role"]
                 and node.get("HostConfig", {}).get("NanoCpus") == limits["cpu_nano"]
                 and node["HostConfig"].get("Memory") == limits["memory_bytes"]
                 and node["HostConfig"].get("MemorySwap") == limits["memory_plus_swap_bytes"],
                 "resume-owned-node-changed")
        policy = steps.run("kubelet-" + expected["role"], [*docker, "exec", expected["container_id"],
                           "cat", "/var/lib/kubelet/config.yaml"])
        _require(len(re.findall(r"(?m)^podPidsLimit: 512\s*$", policy)) == 1, "pod-pid-policy")
    observed = steps.run("kubernetes-nodes", [*kubectl, "get", "nodes", "-o", "json"], parse=True)
    _require(len(observed.get("items", [])) == 2, "kubernetes-node-count")
    for node in nodes:
        matches = [item for item in observed["items"] if item.get("metadata", {}).get("name") == node["name"]]
        _require(len(matches) == 1 and matches[0]["metadata"].get("uid") == node["uid"]
                 and matches[0].get("status", {}).get("nodeInfo") == node["node_info"]
                 and any(item.get("type") == "Ready" and item.get("status") == "True"
                         for item in matches[0]["status"].get("conditions", [])), "resume-node-uid-ready")
        if node["role"] == "worker":
            _require(matches[0]["metadata"].get("labels", {}).get("latent.benchmark.worker") == original["owner"],
                     "worker-placement-label")


def resume(repository: Path, original_root: Path, root: Path) -> dict:
    """Read-only verification of the retained loaded cluster; no create/load/retry."""
    _require(os.name == "nt", "windows-required")
    repository, original_root, root = repository.resolve(), original_root.absolute(), root.absolute()
    _require(root.parent == original_root and re.fullmatch(r"resume-[0-9]{2}", root.name)
             and re.fullmatch(r"issue112-setup-[0-9]{2}", original_root.name)
             and original_root.parent.name == "phase1-extension" and original_root.parent.parent.name == "target"
             and not root.exists(), "fresh-resume-root")
    for path in (original_root, *original_root.parents):
        info = path.lstat()
        _require(stat.S_ISDIR(info.st_mode) and not getattr(info, "st_file_attributes", 0)
                 & stat.FILE_ATTRIBUTE_REPARSE_POINT, "resume-root-reparse")
    original, prior_transfer, references = _original_attempt(original_root)
    _space(original_root)
    root.mkdir()
    for name in ("commands", "private", "private/tmp"):
        (root / name).mkdir()
    receipt = {key: original[key] for key in ("owner", "nodes", "original_images", "context",
                "private_kubeconfig", "private_kubeconfig_identity", "kubeconfig_publishable")}
    receipt.update(schema="latent.optimization.kubernetes-setup-resume.v1", root=str(original_root),
                   verification_root=str(root), status="incomplete", verification_kind="read-only-existing-import",
                   historical_failure=original["failure"], failure=None, **references,
                   started_nanos=str(time.monotonic_ns()), headroom_bytes=str(HEADROOM))
    _json(root / "ownership.json", receipt)
    steps = _Steps(root, repository)
    try:
        tools = {name: shutil.which(name) for name in ("git", "docker", "kubectl")}
        _require(all(tools.values()), "required-local-tools")
        tools = {name: str(Path(path).resolve()) for name, path in tools.items()}
        _require(all(Path(path).suffix.lower() == ".exe" for path in tools.values()), "native-tool-executable")
        receipt["source_before"] = steps.source(tools["git"], "verifier-before")
        _require(_hash(Path(__file__)) == receipt["source_before"]["setup_source"], "executing-source-binding")
        original_repository = original_root.parents[2]
        receipt["original_source_before"] = steps.source(tools["git"], "original-before", repository=original_repository)
        _require(receipt["original_source_before"] == original["source_before"], "original-source-changed")
        docker = [tools["docker"], "--context", "desktop-linux"]
        receipt["docker_version"] = steps.run("docker-version", [*docker, "version", "--format", "{{json .}}"], parse=True)
        server = receipt["docker_version"].get("Server", {})
        _require(server.get("Version") == "29.7.2" and server.get("Os") == "linux"
                 and server.get("Arch") == "amd64", "docker-server-identity")
        original_images = _outer_images(steps.run("original-images", [*docker, "image", "inspect",
                                      *(IMAGE_PREFIX + ":" + key for key in IMAGE_IDS)], parse=True))
        _require(original_images == original["original_images"], "original-images-changed")
        transfer = _archive_images(original_root / "images.tar", original_images)
        old_projection = {"archive": transfer["archive"], "images": {
            kind: {key: value for key, value in image.items() if key not in ("archive_index_digest", "archive_index_entry")}
            for kind, image in transfer["images"].items()}}
        _require(old_projection == prior_transfer, "original-transfer-changed")
        receipt["image_archive"] = transfer
        kubectl = [tools["kubectl"], "--kubeconfig", original_root / "private/kubeconfig",
                   "--context", original["context"], "--request-timeout=10s"]
        _resume_nodes(steps, docker, kubectl, original)
        receipt["imported_images"] = _verify_runtime_images(steps, docker, original["nodes"][1]["container_id"], transfer)
        after_images = _outer_images(steps.run("original-images-after", [*docker, "image", "inspect",
                                    *(IMAGE_PREFIX + ":" + key for key in IMAGE_IDS)], parse=True))
        _require(after_images == original_images, "original-images-changed")
        receipt["original_source_after"] = steps.source(tools["git"], "original-after", repository=original_repository)
        receipt["source_after"] = steps.source(tools["git"], "verifier-after")
        _require(receipt["original_source_after"] == receipt["original_source_before"]
                 and receipt["source_after"] == receipt["source_before"], "source-changed")
        _require(_original_attempt(original_root) == (original, prior_transfer, references)
                 and _hash(original_root / "images.tar", MAX_TAR) == transfer["archive"], "original-attempt-changed")
        receipt.update(status="ready-for-campaign-preflight", disk_free_after=str(_space(root)),
                       retained_bytes=str(_usage(root)))
    except BaseException as error:
        receipt["failure"] = {"type": type(error).__name__, "message": str(error)[:2048]}
        raise
    finally:
        receipt.update(commands=steps.rows, finished_nanos=str(time.monotonic_ns()))
        _json(root / "setup.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--resume-from", type=Path)
    args = parser.parse_args()
    try:
        result = (resume(args.repository, args.resume_from, args.root) if args.resume_from is not None
                  else prepare(args.repository, args.root))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Kubernetes setup retained an incomplete attempt: {error}\n")
    print(json.dumps({"status": result["status"], "owner": result["owner"], "root": result["root"]}))


if __name__ == "__main__":
    main()
