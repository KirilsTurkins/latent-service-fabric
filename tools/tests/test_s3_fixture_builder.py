"""Pure fixture identity/ownership checks; no Docker or MinIO execution."""
from contextlib import nullcontext, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import build_s3_fixture as builder
from tools.owned_test_process import ProcessFailure, Result
from tools.test_run import TestRun


TOKEN = "a" * 32
CONTAINER = "b" * 64
RECIPE = "c" * 64
BINARY = "d" * 64
ROOTFS = "e" * 64
IMAGE = "sha256:" + "f" * 64
MODULE = b"module example.invalid/fixture\ngo 1.27.1\n"
SUM = b"synthetic module checksums\n"


def member(name, data=b"", kind=tarfile.REGTYPE):
    value = tarfile.TarInfo(name)
    value.type = kind
    value.size = len(data) if kind == tarfile.REGTYPE else 0
    if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
        value.linkname = "../../outside"
    return value, data


def archive_rows():
    root = "minio-" + builder.REVISION
    return [member(root, kind=tarfile.DIRTYPE),
            *(member(root + "/" + name, data) for name, data in
              (("go.mod", MODULE), ("go.sum", SUM), ("LICENSE", b"license"), ("CREDITS", b"credits")))]


def receipt():
    return {"schemaVersion": builder.SCHEMA, "passed": True, "sourceRevision": builder.REVISION,
            "sourceSha256": builder.SOURCE_SHA256, "sourceUrl": builder.SOURCE_URL,
            "release": builder.RELEASE, "builder": builder.BUILDER, "goVersion": builder.GO_VERSION,
            "recipeSha256": RECIPE, "imageId": IMAGE, "binarySha256": BINARY,
            "rootfsSha256": ROOTFS, "imageOwner": TOKEN,
            "source": {"archiveSha256": builder.SOURCE_SHA256, "archiveBytes": builder.SOURCE_BYTES,
                       "members": 5, "files": 4, "expandedBytes": 100},
            "outputSha256": {name: BINARY if name == "minio" else "0" * 64
                             for name in ("minio", "build-info.txt", "LICENSE", "CREDITS", "ca-certificates.crt")},
            "compilerContainer": CONTAINER, "compilerExit": 0, "compilerOomKilled": False,
            "compilerRetired": True,
            "boundary": "Local test fixture only; no registry publication, old-image equivalence, signed upstream commit, or whole-build hermeticity claim. The immutable image is a retained build output."}


def image_info():
    return {"Id": IMAGE, "Os": "linux", "Architecture": "amd64",
            "Config": {"Entrypoint": ["/minio"], "Cmd": None, "Env": ["HOME=/tmp"],
                       "Labels": {builder.OWNER_LABEL: TOKEN, builder.RECIPE_LABEL: RECIPE,
                                  builder.BINARY_LABEL: BINARY}},
            "RootFS": {"Type": "layers", "Layers": ["sha256:" + ROOTFS]}}


class FixtureFilesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def inspect(self, rows):
        path = self.root / "source.tar.gz"
        with tarfile.open(path, "w:gz") as output:
            for entry, data in rows:
                output.addfile(entry, io.BytesIO(data) if entry.isfile() else None)
        with patch.multiple(builder, SOURCE_BYTES=path.stat().st_size,
                            SOURCE_SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            GO_MOD_SHA256=hashlib.sha256(MODULE).hexdigest(),
                            GO_SUM_SHA256=hashlib.sha256(SUM).hexdigest()):
            return builder.inspect_archive(path)

    def test_sha_is_exact_and_rejects_missing_empty_oversized_or_symlink_files(self):
        path = self.root / "input"
        with self.assertRaises(ProcessFailure):
            builder.sha(path, 3)
        path.write_bytes(b"")
        with self.assertRaises(ProcessFailure):
            builder.sha(path, 3)
        path.write_bytes(b"abc")
        self.assertEqual(builder.sha(path, 3), hashlib.sha256(b"abc").hexdigest())
        with self.assertRaises(ProcessFailure):
            builder.sha(path, 2)
        with patch.object(Path, "is_symlink", return_value=True), self.assertRaises(ProcessFailure):
            builder.sha(path, 3)

    def test_recipe_binds_source_builder_go_and_helper_implementation(self):
        with patch.object(builder, "sha", return_value="0" * 64) as digest:
            baseline = builder.recipe()
            digest.assert_called_with(Path(builder.__file__).resolve(), 128 * 1024)
            for field in ("REVISION", "SOURCE_SHA256", "BUILDER", "GO_VERSION"):
                with self.subTest(field=field), patch.object(builder, field, "different"):
                    self.assertNotEqual(builder.recipe(), baseline)
        with patch.object(builder, "sha", return_value="1" * 64):
            self.assertNotEqual(builder.recipe(), baseline)

    def test_archive_accepts_only_the_authenticated_small_source_tree(self):
        observed = self.inspect(archive_rows())
        self.assertEqual((observed["members"], observed["files"]), (5, 4))
        self.assertEqual(observed["expandedBytes"], len(MODULE) + len(SUM) + 14)
        self.assertEqual(list(self.root.iterdir()), [self.root / "source.tar.gz"])

    def test_source_size_or_digest_failure_precedes_tar_parsing(self):
        path = self.root / "source.tar.gz"
        path.write_bytes(b"not a tar")
        for maximum in (path.stat().st_size - 1, path.stat().st_size):
            with self.subTest(maximum=maximum), patch.object(builder, "SOURCE_BYTES", maximum), \
                    patch.object(builder.tarfile, "open") as opened, self.assertRaises(ProcessFailure):
                try:
                    builder.inspect_archive(path)
                finally:
                    opened.assert_not_called()

    def test_archive_rejects_traversal_absolute_foreign_and_ambiguous_paths(self):
        root = "minio-" + builder.REVISION
        for name in ("/absolute", "../escape", root + "/../escape", "another-root/file",
                     root + "/a\\b", root + "/C:drive", root + "/./go.mod", root + "//go.mod"):
            with self.subTest(name=name), self.assertRaises(ProcessFailure):
                self.inspect([*archive_rows(), member(name, b"replacement")])

    def test_archive_rejects_links_special_files_and_duplicate_destinations(self):
        root = "minio-" + builder.REVISION
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind), self.assertRaises(ProcessFailure):
                self.inspect([*archive_rows(), member(root + "/special", kind=kind)])
        with self.assertRaises(ProcessFailure):
            self.inspect([*archive_rows(), member(root + "/LICENSE", b"duplicate")])

    def test_archive_requires_regular_inputs_and_matching_module_hashes(self):
        for name in ("go.mod", "go.sum", "LICENSE", "CREDITS"):
            with self.subTest(name=name):
                rows = [row for row in archive_rows() if not row[0].name.endswith("/" + name)]
                with self.assertRaises(ProcessFailure):
                    self.inspect(rows)
                with self.assertRaises(ProcessFailure):
                    self.inspect([*rows, member("minio-" + builder.REVISION + "/" + name, kind=tarfile.DIRTYPE)])
        for name in ("go.mod", "go.sum"):
            rows = [row for row in archive_rows() if not row[0].name.endswith("/" + name)]
            with self.subTest(name=name), self.assertRaises(ProcessFailure):
                self.inspect([*rows, member("minio-" + builder.REVISION + "/" + name, b"changed")])

    def test_archive_bounds_member_count_names_member_size_and_expansion(self):
        path = self.root / "source.tar.gz"
        path.write_bytes(b"synthetic bounded metadata")
        root = "minio-" + builder.REVISION
        huge, _ = member(root + "/huge")
        huge.size = 64 * 1024 * 1024 + 1
        large = [member(root + f"/large-{index}")[0] for index in range(5)]
        for value in large:
            value.size = 64 * 1024 * 1024
        rows = ([huge], large, [member(root + "/" + "a" * 513)[0]],
                [member(root + f"/{index}")[0] for index in range(2001)])
        for entries in rows:
            with self.subTest(count=len(entries)), patch.multiple(
                    builder, SOURCE_BYTES=path.stat().st_size,
                    SOURCE_SHA256=hashlib.sha256(path.read_bytes()).hexdigest()), \
                    patch.object(builder.tarfile, "open", return_value=nullcontext(entries)), \
                    self.assertRaises(ProcessFailure):
                builder.inspect_archive(path)

    def elf(self):
        data = bytearray(120)
        data[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", data, 18, 62)
        struct.pack_into("<Q", data, 32, 64)
        struct.pack_into("<HH", data, 54, 56, 1)
        struct.pack_into("<I", data, 64, 1)
        return data

    def test_binary_accepts_a_bounded_static_amd64_elf_and_returns_exact_digest(self):
        path = self.root / "minio"
        path.write_bytes(self.elf())
        self.assertEqual(builder.verify_binary(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def test_binary_rejects_wrong_format_architecture_interpreter_and_header_bounds(self):
        path = self.root / "minio"
        for offset, format_, value in ((0, "<I", 0), (18, "<H", 183), (32, "<Q", 121),
                                       (54, "<H", 55), (56, "<H", 0), (56, "<H", 129), (64, "<I", 3)):
            data = self.elf()
            struct.pack_into(format_, data, offset, value)
            path.write_bytes(data)
            with self.subTest(offset=offset, value=value), self.assertRaises(ProcessFailure):
                builder.verify_binary(path)
        path.write_bytes(b"\x7fELF")
        with self.assertRaises(ProcessFailure):
            builder.verify_binary(path)


class FixtureReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        selected_recipe = patch.object(builder, "recipe", return_value=RECIPE)
        selected_recipe.start()
        self.addCleanup(selected_recipe.stop)

    def resolve(self, value=None, info=None):
        path = self.root / "fixture.json"
        path.write_text(json.dumps(receipt() if value is None else value), encoding="utf-8")
        command = Mock(return_value=json.dumps([image_info() if info is None else info]))
        image = builder.image_from_receipt(path, command)
        command.assert_called_once_with(["docker", "image", "inspect", IMAGE])
        return image

    def test_current_retired_receipt_resolves_only_its_immutable_local_image(self):
        self.assertEqual(self.resolve(), IMAGE)

    def test_receipt_rejects_stale_pins_failed_compiler_or_missing_retirement(self):
        changes = {"schemaVersion": "old", "passed": False, "sourceRevision": "0" * 40,
                   "sourceSha256": "0" * 64, "builder": "golang:latest", "goVersion": "go0.0.0",
                   "recipeSha256": "0" * 64, "compilerRetired": False,
                   "compilerExit": 1, "compilerOomKilled": True, "imageId": "minio:latest",
                   "binarySha256": "not-a-digest", "rootfsSha256": "not-a-digest"}
        for name, value in changes.items():
            data = receipt()
            data[name] = value
            with self.subTest(name=name), self.assertRaises(ProcessFailure):
                self.resolve(data)
        data = receipt()
        del data["compilerRetired"]
        with self.assertRaises(ProcessFailure):
            self.resolve(data)

    def test_receipt_rejects_unknown_fields_malformed_shapes_and_forged_outputs(self):
        for value in ([], None, "not-an-object"):
            with self.subTest(value=value):
                self.reject_receipt_json(json.dumps(value))
        for key, value in (("extra", True), ("imageId", None), ("imageOwner", "foreign"),
                           ("outputSha256", {"minio": "0" * 64}),
                           ("compilerExit", False), ("compilerExit", True), ("compilerExit", 0.0)):
            data = receipt()
            data[key] = value
            with self.subTest(key=key, value=value):
                self.reject_receipt_json(json.dumps(data))
        for key in ("outputSha256", "source"):
            for value in (None, [], False, "not-an-object"):
                data = receipt()
                data[key] = value
                with self.subTest(key=key, value=value):
                    self.reject_receipt_json(json.dumps(data))
            for missing in receipt()[key]:
                data = receipt()
                del data[key][missing]
                with self.subTest(key=key, missing=missing):
                    self.reject_receipt_json(json.dumps(data))
            data = receipt()
            data[key]["extra"] = "0" * 64
            with self.subTest(key=key, extra=True):
                self.reject_receipt_json(json.dumps(data))
        for name in receipt()["outputSha256"]:
            for value in (None, False, 0, [], "0" * 63, "A" * 64):
                data = receipt()
                data["outputSha256"][name] = value
                with self.subTest(output=name, value=value):
                    self.reject_receipt_json(json.dumps(data))
        data = receipt()
        data["outputSha256"]["minio"] = "0" * 64
        with self.subTest(output="minio", different_binary=True):
            self.reject_receipt_json(json.dumps(data))
        source_changes = {"archiveSha256": ["0" * 64, None, []],
                          "archiveBytes": [builder.SOURCE_BYTES - 1, True, "243"],
                          "members": [0, -1, 2001, True, 5.0],
                          "files": [0, -1, 6, False, "4"],
                          "expandedBytes": [0, -1, 256 * 1024 * 1024 + 1, True, 100.0]}
        for name, values in source_changes.items():
            for value in values:
                data = receipt()
                data["source"][name] = value
                with self.subTest(source=name, value=value):
                    self.reject_receipt_json(json.dumps(data))
        text = json.dumps(receipt(), separators=(",", ":"))
        for key, value in (("compilerRetired", True), ("archiveSha256", builder.SOURCE_SHA256),
                           ("minio", BINARY)):
            field = json.dumps(key) + ":" + json.dumps(value)
            duplicate = text.replace(field, field + "," + field, 1)
            self.assertNotEqual(duplicate, text)
            with self.subTest(duplicate_key=key):
                self.reject_receipt_json(duplicate)

    def reject_receipt_json(self, text):
        path = self.root / "fixture.json"
        path.write_text(text, encoding="utf-8")
        command = Mock(return_value=json.dumps([image_info()]))
        with self.assertRaises(ProcessFailure):
            builder.image_from_receipt(path, command)
        command.assert_not_called()

    def test_image_must_match_id_platform_entrypoint_labels_and_rootfs(self):
        mutations = [(lambda value: value.update(Id="sha256:" + "0" * 64)),
                     (lambda value: value.update(Os="windows")),
                     (lambda value: value.update(Architecture="arm64")),
                     (lambda value: value["Config"].update(Entrypoint=["/other"])),
                     (lambda value: value["RootFS"].update(Layers=[])),
                     (lambda value: value["RootFS"].update(Layers=["sha256:" + "0" * 64])),
                     *(lambda value, key=key: value["Config"]["Labels"].update({key: "foreign"})
                       for key in (builder.OWNER_LABEL, builder.RECIPE_LABEL, builder.BINARY_LABEL))]
        for index, mutate in enumerate(mutations):
            info = copy.deepcopy(image_info())
            mutate(info)
            with self.subTest(index=index), self.assertRaises(ProcessFailure):
                self.resolve(info=info)

    def test_image_inspection_requires_one_result_and_never_hides_daemon_failure(self):
        path = self.root / "fixture.json"
        path.write_text(json.dumps(receipt()), encoding="utf-8")
        for entries in ([], [image_info(), image_info()]):
            with self.subTest(count=len(entries)), self.assertRaises(ProcessFailure):
                builder.image_from_receipt(path, Mock(return_value=json.dumps(entries)))
        original = ProcessFailure("unavailable-environment", "docker-daemon-denied")
        with self.assertRaises(ProcessFailure) as caught:
            builder.image_from_receipt(path, Mock(side_effect=original))
        self.assertIs(caught.exception, original)


class FixtureOwnerTests(unittest.TestCase):
    def owner(self, **changes):
        value = {"Id": CONTAINER, "Config": {"Labels": {builder.OWNER_LABEL: TOKEN}}}
        value.update(changes)
        return Result(0, json.dumps([value]).encode())

    def test_cleanup_uses_only_verified_immutable_container_id_even_after_reply_loss(self):
        for identity in ([], [CONTAINER]):
            run = Mock(command=Mock(side_effect=[self.owner(), Result(0, b""),
                                                 Result(1, b"No such container")]))
            builder.remove_builder(run, "private-name", TOKEN, identity)
            self.assertEqual(run.command.call_args_list[0].args[0],
                             ["docker", "container", "inspect", "--format", builder.CONTAINER_INSPECT, "private-name"])
            self.assertEqual(run.command.call_args_list[1].args[0],
                             ["docker", "container", "rm", "--force", CONTAINER])
            self.assertTrue(all(call.kwargs["timeout"] <= 8 for call in run.command.call_args_list))

    def test_cleanup_rejects_foreign_label_id_and_malformed_container_identity(self):
        cases = [(self.owner(), "different", [CONTAINER]),
                 (self.owner(), TOKEN, ["0" * 64]), (self.owner(Id="not-an-id"), TOKEN, [])]
        for observed, token, identity in cases:
            run = Mock(command=Mock(return_value=observed))
            with self.subTest(token=token, identity=identity), self.assertRaises(ProcessFailure):
                builder.remove_builder(run, "private-name", token, identity)
            self.assertEqual(run.command.call_count, 1)

    def test_cleanup_distinguishes_confirmed_absence_from_daemon_failure(self):
        for output in (b"No such container", b"No such object"):
            run = Mock(command=Mock(return_value=Result(1, output)))
            builder.remove_builder(run, "private-name", TOKEN, [])
            run.command.assert_called_once()
        run = Mock(command=Mock(return_value=Result(1, b"daemon unavailable")))
        with self.assertRaises(ProcessFailure) as caught:
            builder.remove_builder(run, "private-name", TOKEN, [])
        self.assertEqual(caught.exception.reason, "minio-builder-retirement-unverified")
        run.command.assert_called_once()

    def test_cleanup_cannot_report_success_when_owned_container_remains(self):
        run = Mock(command=Mock(side_effect=[self.owner(), Result(0, b""), self.owner()]))
        with self.assertRaises(ProcessFailure):
            builder.remove_builder(run, "private-name", TOKEN, [CONTAINER])

    def test_failed_removal_forwards_the_original_error_without_retry(self):
        original = ProcessFailure("infrastructure-timeout", "synthetic-docker-rm-timeout")
        run = Mock(command=Mock(side_effect=[self.owner(), original]))
        with self.assertRaises(ProcessFailure) as caught:
            builder.remove_builder(run, "private-name", TOKEN, [CONTAINER])
        self.assertIs(caught.exception, original)
        self.assertEqual(run.command.call_count, 2)

    def test_cleanup_failure_preserves_original_build_failure_and_prevents_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            original = ProcessFailure("infrastructure-timeout", "synthetic-build-timeout")
            run = TestRun("synthetic-s3-build", {"timeoutSeconds": 5},
                          diagnostic_root=Path(temporary), synthetic=True)
            run.command = Mock(return_value=Result(1, b"daemon unavailable"))
            run.cleanup.append(lambda: builder.remove_builder(run, "private-name", TOKEN, [CONTAINER]))
            with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure) as caught:
                with run:
                    raise original
            self.assertIs(caught.exception, original)
            self.assertEqual(run.record["outcome"], "failed")
            self.assertEqual(run.record["reason"], "synthetic-build-timeout")
            self.assertEqual(run.record["cleanupFailures"], ["ProcessFailure"])
            self.assertFalse(run.root.exists())

    def publish(self, *, retirement_fails):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "build"
            path = output / "fixture.json"
            run = TestRun("synthetic-s3-publish", {"timeoutSeconds": 5},
                          diagnostic_root=root / "diagnostics", synthetic=True)
            responses = iter([Result(1, b"daemon unavailable")] if retirement_fails else
                             [self.owner(), Result(0, b""), Result(1, b"No such container")])

            def command(*_args, **_options):
                self.assertFalse(path.exists(), "success receipt precedes compiler retirement")
                return next(responses)

            def build(owner, destination):
                self.assertIs(owner, run)
                destination.mkdir()
                owner.cleanup.append(lambda: builder.remove_builder(owner, "private-name", TOKEN, [CONTAINER]))
                value = receipt()
                del value["compilerRetired"]
                return value

            run.command = Mock(side_effect=command)
            with redirect_stdout(io.StringIO()), patch.object(builder, "TestRun", return_value=run), \
                    patch.object(builder, "build", side_effect=build), patch.object(run, "source_identity"), \
                    patch.object(builder.sys, "argv", ["build_s3_fixture.py", "--output", str(output)]):
                if retirement_fails:
                    with self.assertRaises(ProcessFailure) as caught:
                        builder.main()
                    self.assertEqual(caught.exception.reason, "fixture-cleanup-unconfirmed")
                    self.assertFalse(path.exists())
                else:
                    self.assertEqual(builder.main(), 0)
                    self.assertIs(json.loads(path.read_text())["compilerRetired"], True)
                    self.assertEqual(run.command.call_count, 3)

    def test_main_does_not_publish_success_when_compiler_retirement_is_unconfirmed(self):
        self.publish(retirement_fails=True)

    def test_main_publishes_success_only_after_verified_compiler_retirement(self):
        self.publish(retirement_fails=False)


if __name__ == "__main__":
    unittest.main()
