"""Small synthetic closure/API tests; no Docker daemon, builds, or workloads."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools.artifact_identity_runner.files import reference, write_json
from tools.optimization_docker import build, fixtures, images, setup
from tools.optimization_docker.engine import EngineError
from tools.tests import test_optimization_docker_build as build_test

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = "a" * 64


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def closure(root):
    root.mkdir()
    value = build_test.DockerBuildBindings().receipt(root)
    for name in ("app.Dockerfile", "client.Dockerfile"):
        relative = "tools/optimization-docker/" + name
        path = root / "source" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
        value["inputs"][relative] = reference(path, root)
    for row in value["executables"].values():
        (root / row["path"]).chmod(0o755)
    value["fixtures"] = fixtures.materialize(root / "component.wasm", root / "fixtures", root=root, repository=ROOT)
    write_json(root / "docker-builds.json", value)
    return value


def pack(source, destination, *, extra=None, pax=False):
    with tarfile.open(destination, "w", format=tarfile.PAX_FORMAT if pax else tarfile.USTAR_FORMAT) as archive:
        for path in [source, *sorted(source.rglob("*"))]:
            name = "build-01" + ("/" + path.relative_to(source).as_posix() if path != source else "")
            info = archive.gettarinfo(str(path), name)
            info.uid, info.gid, info.uname, info.gname, info.mtime = 0, 0, "", "", 0
            if pax:
                info.pax_headers = {"mtime": "123.456789"}
            if path.is_file():
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
            else:
                archive.addfile(info)
        if extra:
            info, data = extra
            archive.addfile(info, io.BytesIO(data))


class FakeEngine:
    """Only transport is mocked; closure, tar, modes, hashes and image replay are real."""
    def __init__(self, archive=None):
        self.archive, self.calls, self.archives, self.tags = archive, [], [], {}
        self.api_version, self.server_version = "1.54", "29.7.2"
        self.fail_build = self.cross_image = False
        self.version_body = b'{"Version":"29.7.2","ApiVersion":"1.55","MinAPIVersion":"1.40"}'
        self.version_receipt = self.receipt("GET", "/version", self.version_body)

    def receipt(self, method, path, body, request=b""):
        self.last_body = body
        self.last_receipt = {"method": method, "path": path, "begin_nanos": "10", "end_nanos": "20",
                             "status": 200, "request_bytes": str(len(request)), "request_sha256": digest(request),
                             "response_bytes": str(len(body)), "response_sha256": digest(body),
                             "response_complete": True, "connection_closed": True, "failure": None}
        return self.last_receipt

    def download_archive(self, container, source, destination, **kwargs):
        self.calls.append(("download", container, source, kwargs))
        with destination.open("xb") as output:
            output.write(self.archive.read_bytes())
        row = self.receipt("GET", "/v1.54/containers/" + container + "/archive", self.archive.read_bytes())
        row.update(destination=str(destination), file_closed=True)
        self.last_body = b""
        return row

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if "debian" in path:
            value = {"Id": images.BASE.split("@", 1)[1], "Os": "linux", "Architecture": "amd64",
                     "RepoDigests": [images.BASE], "Config": {}, "RootFS": {"Type": "layers", "Layers": ["sha256:" + "b" * 64]}}
        else:
            kind = next(key for key in images.KINDS if path.endswith("%3A" + key + "/json"))
            query = self.tags[kind]
            executable = "optimization-client" if kind == "client" else "optimization-container"
            labels = dict(query["labels"])
            if self.cross_image:
                labels[setup.OWNER_LABEL] = "different-owner"
            value = {"Id": "sha256:" + {"lsf": "1", "native": "2", "client": "3"}[kind] * 64,
                     "Os": "linux", "Architecture": "amd64", "Size": 123,
                     "Config": {"Entrypoint": ["/opt/lsf/" + executable], "Labels": labels},
                     "RootFS": {"Type": "layers", "Layers": ["sha256:" + "b" * 64]}, "RepoDigests": []}
        body = json.dumps(value).encode()
        return value, self.receipt(method, "/v1.54" + path, body)

    def build(self, path, query):
        raw = path.read_bytes()
        self.archives.append(raw)
        self.calls.append(("build", str(path), copy.deepcopy(query)))
        kind = query["labels"][setup.ROLE_LABEL]
        self.tags[kind] = query
        if self.fail_build:
            body = b'{"error":"synthetic unsupported builder"}\n'
            row = self.receipt("POST", "/v1.54/build", body, raw)
            row["failure"] = "engine-build-stream-error"
            raise EngineError(row["failure"], receipt=row, body=body)
        body = b'{"stream":"synthetic build succeeded\\n"}\n'
        return [{"stream": "synthetic build succeeded\n"}], self.receipt("POST", "/v1.54/build", body, raw)


class DockerBuildImport(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX permission preservation")
    def test_exact_closure_and_pax_modes_hashes_retained_tar(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source, bench = base / "source", base / "bench"
            bench.mkdir()
            original = closure(source)
            archive = base / "original.tar"
            pack(source, archive, pax=True)
            engine = FakeEngine(archive)
            with patch.object(setup, "BENCH", bench):
                result = setup.import_build(engine, CONTAINER,
                                            "/workspace/project/target/optimization-docker/build-01", bench / "build-01", ROOT)
            imported = bench / "build-01"
            self.assertEqual(build.validate_receipt(json.loads((imported / "docker-builds.json").read_bytes()), imported), original)
            self.assertEqual(Path(result["archive"]["source_path"]).read_bytes(), archive.read_bytes())
            self.assertEqual((imported / "fixtures/token").stat().st_mode & 0o777, 0o600)
            self.assertEqual((imported / "binaries/latentd").stat().st_mode & 0o777, 0o755)
            self.assertTrue(result["archive"]["retained"])
            self.assertEqual(engine.calls[0][-1], {"maximum": 512 * 1024**2})
            for row in result["members"]:
                if row["kind"] == "file":
                    self.assertEqual(reference(imported / row["path"], imported),
                                     {key: row[key] for key in ("path", "sha256", "bytes")})

    def test_extra_duplicate_traversal_link_and_special_members_reject_before_extract(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            closure(source)
            cases = [("build-01/extra", tarfile.REGTYPE, ""),
                     ("build-01/component.wasm", tarfile.REGTYPE, ""),
                     ("build-01/../escaped", tarfile.REGTYPE, ""),
                     ("build-01/source/.git/config", tarfile.REGTYPE, ""),
                     ("build-01/source/target/cache", tarfile.REGTYPE, ""),
                     ("build-01/link", tarfile.SYMTYPE, "component.wasm"),
                     ("build-01/pipe", tarfile.FIFOTYPE, "")]
            for index, (name, kind, link) in enumerate(cases):
                with self.subTest(name=name):
                    bench = base / f"bench-{index}"
                    bench.mkdir()
                    archive = base / f"case-{index}.tar"
                    info = tarfile.TarInfo(name)
                    info.type, info.linkname, info.mode = kind, link, 0o644
                    pack(source, archive, extra=(info, b""))
                    with patch.object(setup, "BENCH", bench), self.assertRaises(ValueError):
                        setup.import_build(FakeEngine(archive), CONTAINER,
                                            "/workspace/project/target/optimization-docker/build-01", bench / "build-01", ROOT)
                    self.assertFalse((bench / "build-01/binaries").exists())
                    self.assertTrue((bench / "scratch/build-01-import.tar").exists())
                    self.assertTrue((bench / "build-01/import/failure.json").exists())

    def test_source_ref_hash_change_rejects_and_keeps_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source, bench = base / "source", base / "bench"
            bench.mkdir()
            closure(source)
            # A valid tar is not enough: its original build receipt binds bytes.
            (source / "component.wasm").write_bytes(b"changed component")
            archive = base / "changed.tar"
            pack(source, archive)
            with patch.object(setup, "BENCH", bench), self.assertRaisesRegex(ValueError, "extracted-source-hash"):
                setup.import_build(FakeEngine(archive), CONTAINER, "/owned/build-01", bench / "build-01", ROOT)
            self.assertEqual((bench / "scratch/build-01-import.tar").read_bytes(), archive.read_bytes())

    def test_physical_pax_and_file_bounds_are_checked_before_allocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kind, length, error in ((tarfile.XHDTYPE, 65537, "pax-byte-bound"),
                                        (tarfile.REGTYPE, 16, "archive-file-bound")):
                with self.subTest(kind=kind):
                    path = root / (kind.decode() + ".tar")
                    info = tarfile.TarInfo("build-01/file")
                    info.type, info.size = kind, length
                    with path.open("wb") as output:
                        output.write(info.tobuf(format=tarfile.USTAR_FORMAT))
                        output.write(bytes(((length + 511) // 512) * 512 + 1024))
                    with patch.object(setup, "MAX_FILE_BYTES", 8), self.assertRaisesRegex(ValueError, error):
                        setup._members(path, "build-01")

    def test_import_destination_source_and_nonempty_scratch_are_rejected_without_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = Path(temporary)
            (bench / "scratch").mkdir()
            (bench / "scratch/old-import.tar").write_bytes(b"original failed scratch")
            engine = FakeEngine()
            with patch.object(setup, "BENCH", bench):
                for source, destination in (("/owned/build-01", bench / "build-01"),
                                             ("/owned/../build-01", bench / "build-01"),
                                             ("/owned/build-01", bench / "nested/build-01")):
                    with self.subTest(source=source, destination=destination), self.assertRaises(ValueError):
                        setup.import_build(engine, CONTAINER, source, destination, ROOT)
            self.assertEqual(engine.calls, [])
            self.assertEqual((bench / "scratch/old-import.tar").read_bytes(), b"original failed scratch")


class DockerImageSetup(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX executable context modes")
    def test_three_actual_context_streams_bind_raw_http_and_distinct_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = Path(temporary)
            root = bench / "build-01"
            original = closure(root)
            engine = FakeEngine()
            with patch.object(setup, "BENCH", bench):
                result = setup.prepare_images(engine, root, ROOT)
            self.assertEqual(set(result["images"]), set(images.KINDS))
            self.assertEqual(len({row["image_id"] for row in result["images"].values()}), 3)
            self.assertEqual(list((bench / "scratch").iterdir()), [])
            self.assertEqual(result["build"], reference(root / "docker-builds.json", root))
            self.assertEqual(json.loads((root / "docker-builds.json").read_bytes()), original)
            for index, kind in enumerate(images.KINDS):
                row = result["builds"][kind]
                self.assertEqual(row["context_archive"]["sha256"], digest(engine.archives[index]))
                self.assertFalse(row["context_archive"]["retained"])
                http = json.loads((root / row["build_http"]["path"]).read_bytes())
                self.assertEqual(http["request_sha256"], row["context_archive"]["sha256"])
                self.assertEqual(http["request_bytes"], row["context_archive"]["bytes"])
                body = (root / row["build_response"]["path"]).read_bytes()
                self.assertEqual(digest(body), http["response_sha256"])
                consumed = json.loads((root / row["consumed_receipt"]["path"]).read_bytes())
                self.assertEqual(consumed["image_id"], result["images"][kind]["image_id"])
                self.assertNotIn("retained", consumed["build"]["context_archive"])
                self.assertEqual(row["query"]["version"], "1")
                self.assertEqual(row["query"]["networkmode"], "none")
                self.assertEqual(row["query"]["pull"], "0")
                with tarfile.open(fileobj=io.BytesIO(engine.archives[index])) as archive:
                    for member in archive:
                        if member.isfile() and member.name != "Dockerfile":
                            self.assertEqual(member.mode, 0o755)
                    dockerfile = archive.extractfile("Dockerfile").read()
                    self.assertNotIn(b"--chmod", dockerfile)
                    self.assertIn(images.BASE.encode(), dockerfile)

    @unittest.skipUnless(os.name == "posix", "POSIX executable context modes")
    def test_failed_stream_or_crossed_image_keeps_tar_raw_receipts_and_no_final_envelope(self):
        for failure in ("fail_build", "cross_image"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                bench = Path(temporary)
                root = bench / "build-01"
                closure(root)
                engine = FakeEngine()
                setattr(engine, failure, True)
                with patch.object(setup, "BENCH", bench), self.assertRaises(ValueError):
                    setup.prepare_images(engine, root, ROOT)
                self.assertFalse((root / "images.json").exists())
                self.assertTrue((bench / "scratch/build-01-lsf-context.tar").exists())
                self.assertTrue((root / "images/requests/lsf-build.body.jsonl").exists())
                self.assertTrue((root / "images/failure.json").exists())
                self.assertFalse((root / "images/requests/lsf-consumed.json").exists())

    def test_retained_context_budget_preflight_happens_before_writes_or_api(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = Path(temporary)
            root = bench / "build-01"
            closure(root)
            engine = FakeEngine()
            with patch.object(setup, "BENCH", bench), patch.object(setup, "_usage", return_value=(1024**3 - 1, 10)):
                with self.assertRaisesRegex(ValueError, "images-reservation"):
                    setup.prepare_images(engine, root, ROOT)
            self.assertFalse((root / "images").exists())
            self.assertEqual(engine.calls, [])

    def test_scratch_separation_counts_only_one_import_and_one_current_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = Path(temporary)
            scratch = bench / "scratch"
            scratch.mkdir()
            imported = scratch / "build-01-import.tar"
            imported.write_bytes(b"retained exact import tar")
            with patch.object(setup, "BENCH", bench):
                setup._scratch(scratch / "build-01-lsf-context.tar", import_tar=False)
                with self.assertRaisesRegex(ValueError, "previous-import-retained"):
                    setup._scratch(scratch / "next-import.tar", import_tar=True)
                (scratch / "build-01-lsf-context.tar").write_bytes(b"retained failed context")
                with self.assertRaisesRegex(ValueError, "previous-context-retained"):
                    setup._scratch(scratch / "build-01-native-context.tar", import_tar=False)
            self.assertEqual(imported.read_bytes(), b"retained exact import tar")

    def test_deterministic_context_tar_preserves_explicit_mode_and_rejects_extra_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            bench = Path(temporary)
            context = bench / "build-01/images/contexts/client"
            context.mkdir(parents=True)
            (context / "Dockerfile").write_bytes((ROOT / "tools/optimization-docker/client.Dockerfile").read_bytes())
            (context / "optimization-client").write_bytes(b"synthetic executable")
            root = bench / "build-01"
            row = {"context": "images/contexts/client", "executables": {"client": reference(context / "optimization-client", root)}}
            recorded = fixtures.inventory(context)
            for item in recorded["entries"]:
                item["mode"] = "0755" if item["kind"] == "directory" or item["path"] != "Dockerfile" else "0644"
            with patch.object(setup, "BENCH", bench), patch.object(setup.fixtures, "inventory", return_value=recorded):
                first = bench / "scratch/first-context.tar"
                identity, _ = setup._context_tar(root, row, first)
                saved = first.read_bytes()
                first.unlink()  # Test-owned fixture only; production removal is tested separately.
                second = bench / "scratch/second-context.tar"
                again, _ = setup._context_tar(root, row, second)
                self.assertEqual(saved, second.read_bytes())
                self.assertEqual(identity["sha256"], again["sha256"])
            with tarfile.open(fileobj=io.BytesIO(saved)) as archive:
                self.assertEqual(archive.getmember("optimization-client").mode, 0o755)
            (context / "extra").write_bytes(b"unexpected context input")
            with patch.object(setup, "BENCH", bench), self.assertRaisesRegex(ValueError, "context-file-set"):
                setup._context_tar(root, row, bench / "scratch/third-context.tar")


if __name__ == "__main__":
    unittest.main()
