"""Bounded setup arithmetic/identity tests; no Docker or Kubernetes commands."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools.optimization_kubernetes import setup


def encoded(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def digest(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def image_archive(path, *, changed_layer=False, crossed_index=False, duplicate=False, traversal=False):
    layer = b"synthetic immutable layer bytes"
    config = {"os": "linux", "architecture": "amd64",
              "rootfs": {"type": "layers", "diff_ids": [digest(layer)]},
              "config": {"Entrypoint": ["/opt/lsf/optimization-container"]}}
    config_bytes = encoded(config)
    manifest = {"schemaVersion": 2, "config": {"digest": digest(config_bytes), "size": len(config_bytes)},
                "layers": [{"digest": digest(layer), "size": len(layer)}]}
    manifest_bytes = encoded(manifest)
    identifier = digest(manifest_bytes)
    index = {"schemaVersion": 2, "manifests": [{"digest": "sha256:" + "0" * 64 if crossed_index else identifier,
              "annotations": {"io.containerd.image.name": "docker.io/library/" + setup.IMAGE_PREFIX + ":lsf"}}]}
    entries = {"oci-layout": encoded({"imageLayoutVersion": "1.0.0"}), "index.json": encoded(index),
               "blobs/sha256/" + identifier[7:]: manifest_bytes,
               "blobs/sha256/" + digest(config_bytes)[7:]: config_bytes,
               "blobs/sha256/" + digest(layer)[7:]: b"changed" if changed_layer else layer}
    if traversal:
        entries["../outside"] = b"x"
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as archive:
        for name, value in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
        if duplicate:
            info = tarfile.TarInfo("index.json")
            info.size = len(entries["index.json"])
            archive.addfile(info, io.BytesIO(entries["index.json"]))
    original = {"lsf": {"Id": identifier, "Descriptor": {"size": len(manifest_bytes)},
                        "RootFS": {"Layers": [digest(layer)]}, "Config": config["config"]}}
    return original


class KubernetesSetupIdentity(unittest.TestCase):
    def test_configuration_is_owned_two_nodes_and_uniform_pid_limit(self):
        value = setup.configuration("lsf-112-0123456789ab")
        self.assertEqual([row["role"] for row in value["nodes"]], ["control-plane", "worker"])
        self.assertTrue(all(row["image"] == setup.NODE_IMAGE for row in value["nodes"]))
        self.assertEqual(value["networking"]["apiServerAddress"], "127.0.0.1")
        self.assertEqual(value["networking"]["kubeProxyMode"], "iptables")
        self.assertIn("podPidsLimit: 512", value["nodes"][0]["kubeadmConfigPatches"][0])
        self.assertEqual(value["nodes"][1]["labels"], {"latent.benchmark.worker": value["name"]})
        self.assertNotIn("containerdConfigPatches", value)
        with self.assertRaisesRegex(ValueError, "owner-name"):
            setup.configuration("kind")

    def test_existing_network_overlap_is_rejected_before_cluster_creation(self):
        setup._network_space([{"IPAM": {"Config": [{"Subnet": "172.18.0.0/16"}]}}])
        for subnet in ("10.244.0.0/24", "10.96.0.0/12"):
            with self.subTest(subnet=subnet), self.assertRaisesRegex(ValueError, "cidr-overlap"):
                setup._network_space([{"IPAM": {"Config": [{"Subnet": subnet}]}}])

    def test_original_oci_manifest_differs_from_cri_configuration_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "images.tar"
            original = image_archive(path)
            value = setup._archive_images(path, original)
            expected = value["images"]["lsf"]
            self.assertNotEqual(expected["manifest_digest"], expected["config_digest"])
            cri = {"status": {"id": expected["config_digest"], "repoTags": ["docker.io/library/" + expected["tag"]],
                              "repoDigests": ["actual@" + expected["manifest_digest"]]},
                   "info": {"imageSpec": expected["config"]}}
            self.assertEqual(setup._imported_image(cri, expected)["manifest_digest"], original["lsf"]["Id"])
            wrong = copy.deepcopy(cri)
            wrong["status"]["id"] = expected["manifest_digest"]
            with self.assertRaisesRegex(ValueError, "imported-image-binding"):
                setup._imported_image(wrong, expected)
            wrong = copy.deepcopy(cri)
            wrong["info"]["imageSpec"]["rootfs"]["diff_ids"] = ["sha256:" + "9" * 64]
            with self.assertRaisesRegex(ValueError, "imported-image-binding"):
                setup._imported_image(wrong, expected)

    def test_actual_containerd_index_alias_requires_exact_saved_root_and_config(self):
        root = Path(__file__).parent / "fixtures/kubernetes-import-01"
        cri_bytes = (root / "cri-lsf.json").read_bytes()
        transfer_bytes = (root / "image-transfer.json").read_bytes()
        index_bytes = (root / "index.json").read_bytes()
        self.assertEqual(digest(index_bytes), "sha256:77bb5ae886bf776cccccf82443052741efb718fc84f414ddd1f3d0fe5956bc2f")
        expected = json.loads(transfer_bytes)["images"]["lsf"]
        expected.update(archive_index_digest=digest(index_bytes), archive_index_entry=json.loads(index_bytes)["manifests"][0])
        cri = json.loads(cri_bytes)
        actual = setup._imported_image(cri, expected, live_index=index_bytes)
        self.assertEqual(actual["repo_digest_scope"], "archive-index")
        self.assertEqual(actual["manifest_digest"], setup.IMAGE_IDS["lsf"])
        self.assertNotEqual(actual["archive_index_digest"], actual["manifest_digest"])
        for live in (None, index_bytes + b"\n", encoded({"schemaVersion": 2, "manifests": []})):
            with self.subTest(live=live is None), self.assertRaisesRegex(ValueError, "imported-index-binding"):
                setup._imported_image(cri, expected, live_index=live)
        for change in ("id", "tag", "config", "entry"):
            crossed, crossed_expected = copy.deepcopy(cri), copy.deepcopy(expected)
            if change == "id":
                crossed["status"]["id"] = expected["manifest_digest"]
            elif change == "tag":
                crossed["status"]["repoTags"] = ["docker.io/library/other:lsf"]
            elif change == "config":
                crossed["info"]["imageSpec"]["config"]["WorkingDir"] = "/crossed"
            else:
                crossed_expected["archive_index_entry"]["digest"] = setup.IMAGE_IDS["native"]
            with self.subTest(change=change), self.assertRaises(ValueError):
                setup._imported_image(crossed, crossed_expected, live_index=index_bytes)

    def test_runtime_graph_reads_original_manifest_and_config_without_reimport(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "images.tar"
            original = image_archive(path)
            transfer = setup._archive_images(path, original)
            expected = transfer["images"]["lsf"]
            with tarfile.open(path, "r:") as archive:
                with archive.extractfile("index.json") as stream:
                    content = {transfer["index"]["sha256"]: stream.read()}
                for identifier in (expected["manifest_digest"], expected["config_digest"]):
                    with archive.extractfile("blobs/sha256/" + identifier[7:]) as stream:
                        content[identifier] = stream.read()
            commands = []

            def run(name, argv, **kwargs):
                commands.append((name, argv, kwargs))
                self.assertEqual(argv[:5], ["docker.exe", "--context", "desktop-linux", "exec", "f" * 64])
                tail = argv[5:]
                if tail == ["ctr", "--namespace", "k8s.io", "images", "list"]:
                    return "REF TYPE DIGEST SIZE\n" + "docker.io/library/" + expected["tag"] + \
                        " application/vnd.oci.image.index.v1+json " + transfer["index"]["sha256"] + " 1B"
                if tail[:5] == ["ctr", "--namespace", "k8s.io", "content", "get"]:
                    self.assertEqual(kwargs["parse"], "bytes")
                    return content[tail[5]]
                self.assertEqual(tail, ["crictl", "inspecti", expected["tag"]])
                return {"status": {"id": expected["config_digest"], "repoTags": ["docker.io/library/" + expected["tag"]],
                                   "repoDigests": ["import@" + transfer["index"]["sha256"]]},
                        "info": {"imageSpec": expected["config"]}}

            steps = setup._Steps(Path(temporary), Path(temporary))
            with patch.object(steps, "run", side_effect=run):
                value = setup._verify_runtime_images(steps, ["docker.exe", "--context", "desktop-linux"], "f" * 64, transfer)
                self.assertEqual(value["lsf"]["rootfs_diff_ids"], original["lsf"]["RootFS"]["Layers"])
                self.assertFalse(value["lsf"]["live_layer_bytes_rehashed"])
                self.assertEqual(len(commands), 5)
                content[expected["config_digest"]] += b" "
                with self.assertRaisesRegex(ValueError, "runtime-manifest-config-graph"):
                    setup._verify_runtime_images(steps, ["docker.exe", "--context", "desktop-linux"], "f" * 64, transfer)

    def test_archive_rejects_corruption_crossed_index_duplicate_and_traversal(self):
        for options in ({"changed_layer": True}, {"crossed_index": True},
                        {"duplicate": True}, {"traversal": True}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "images.tar"
                original = image_archive(path, **options)
                with self.assertRaises(ValueError):
                    setup._archive_images(path, original)

    def test_resume_binds_failed_original_and_load_cleanup_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            command = root / "commands/00-images-load"
            command.mkdir(parents=True)
            (root / "private").mkdir()
            (root / "private/kubeconfig").write_bytes(b"private synthetic credential")
            for name in ("stdout.bin", "stderr.bin"):
                (command / name).write_bytes(b"")
            setup._json(command / "receipt.json", {"exit_code": 0, "failure": None,
                        "reaped": True, "output_closed": True, "job_empty": True,
                        "stdout": setup._reference(command / "stdout.bin", root),
                        "stderr": setup._reference(command / "stderr.bin", root)})
            transfer = {"archive": {"bytes": "1", "sha256": digest(b"x")}, "images": {}}
            setup._json(root / "image-transfer.json", transfer)
            original = {"schema": setup.SCHEMA, "status": "incomplete", "root": str(root),
                        "owner": "lsf-112-0123456789ab", "context": "kind-lsf-112-0123456789ab",
                        "failure": {"type": "ValueError", "message": "kubernetes-setup-imported-image-binding"},
                        "private_kubeconfig": "private/kubeconfig", "kubeconfig_publishable": False,
                        "private_kubeconfig_identity": setup._reference(root / "private/kubeconfig", root),
                        "image_archive": transfer, "commands": [setup._reference(command / "receipt.json", root)]}
            setup._json(root / "setup.json", original)
            before = (root / "setup.json").read_bytes()
            actual, archive, refs = setup._original_attempt(root)
            self.assertEqual(actual, original)
            self.assertEqual(archive, transfer)
            self.assertEqual(refs["original_setup"]["sha256"], digest(before))
            self.assertEqual((root / "setup.json").read_bytes(), before)
            self.assertEqual(refs["original_image_load"], original["commands"][0])
            (command / "stdout.bin").write_bytes(b"changed after setup")
            with self.assertRaisesRegex(ValueError, "original-reference-hash"):
                setup._original_attempt(root)
            with self.assertRaisesRegex(ValueError, "original-reference-path"):
                setup._retained_reference(root, {"path": "../outside", "bytes": "0", "sha256": digest(b"")})

    def test_resume_node_verification_rejects_recreated_uid_with_same_name(self):
        owner = "lsf-112-0123456789ab"
        original, docker_nodes, kube_nodes = {"owner": owner, "nodes": []}, [], []
        for index, role in enumerate(("control-plane", "worker")):
            labels = {"io.x-k8s.kind.cluster": owner, "io.x-k8s.kind.role": role}
            row = {"role": role, "name": owner + "-" + role, "container_id": str(index) * 64,
                   "image_id": "sha256:" + "a" * 64, "labels": labels, "uid": "original-" + role,
                   "node_info": {"containerRuntimeVersion": "containerd://2.3.4"},
                   "outer_limits": {"cpu_nano": (2 if index == 0 else 8) * 10**9,
                                    "memory_bytes": (4 if index == 0 else 12) * 1024**3,
                                    "memory_plus_swap_bytes": (4 if index == 0 else 12) * 1024**3}}
            original["nodes"].append(row)
            docker_nodes.append({"Id": row["container_id"], "Image": row["image_id"], "Name": "/" + row["name"],
                                 "Config": {"Labels": labels}, "State": {"Running": True},
                                 "HostConfig": {"NanoCpus": row["outer_limits"]["cpu_nano"],
                                                "Memory": row["outer_limits"]["memory_bytes"],
                                                "MemorySwap": row["outer_limits"]["memory_plus_swap_bytes"]}})
            kube_nodes.append({"metadata": {"name": row["name"], "uid": row["uid"],
                                            "labels": {"latent.benchmark.worker": owner}},
                               "status": {"nodeInfo": row["node_info"],
                                          "conditions": [{"type": "Ready", "status": "True"}]}})
        steps = setup._Steps(Path("."), Path("."))
        responses = [docker_nodes, "podPidsLimit: 512\n", "podPidsLimit: 512\n", {"items": kube_nodes}]
        with patch.object(steps, "run", side_effect=responses) as run:
            setup._resume_nodes(steps, ["docker.exe"], ["kubectl.exe"], original)
            self.assertEqual([call.args[0] for call in run.call_args_list],
                             ["owned-nodes", "kubelet-control-plane", "kubelet-worker", "kubernetes-nodes"])
        kube_nodes[1]["metadata"]["uid"] = "different-uid-same-name"
        with patch.object(steps, "run", side_effect=responses), self.assertRaisesRegex(ValueError, "resume-node-uid-ready"):
            setup._resume_nodes(steps, ["docker.exe"], ["kubectl.exe"], original)

    def test_outer_ids_are_exact_frozen_images_not_arbitrary_local_tags(self):
        rows = [{"Id": identifier, "Descriptor": {"digest": identifier,
                 "mediaType": "application/vnd.oci.image.manifest.v1+json"}, "Os": "linux", "Architecture": "amd64",
                 "Config": {"Entrypoint": ["/opt/lsf/" + ("optimization-client" if key == "client" else "optimization-container")]}}
                for key, identifier in setup.IMAGE_IDS.items()]
        self.assertEqual(set(setup._outer_images(rows)), set(setup.IMAGE_IDS))
        rows[1]["Id"] = rows[0]["Id"]
        with self.assertRaisesRegex(ValueError, "original-image-identity"):
            setup._outer_images(rows)

    def test_storage_headroom_uses_actual_backing_free_bytes(self):
        with patch.object(setup.shutil, "disk_usage") as usage:
            usage.return_value.free = setup.HEADROOM
            self.assertEqual(setup._space(Path(".")), setup.HEADROOM)
            usage.return_value.free -= 1
            with self.assertRaisesRegex(ValueError, "disk-headroom"):
                setup._space(Path("."))

    def test_only_the_exact_owned_transfer_has_512_mib_allowance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "private").mkdir()
            (root / "images.tar").write_bytes(b"12345")
            with patch.object(setup, "MAX_OUTPUT", 4), patch.object(setup, "MAX_TAR", 5):
                self.assertEqual(setup._usage(root), 5)
                (root / "other.tar").write_bytes(b"12345")
                with self.assertRaisesRegex(ValueError, "retained-file-bound"):
                    setup._usage(root)

    def test_failed_command_receipt_is_indexed_without_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "commands").mkdir()
            steps = setup._Steps(root, root)

            def failed(argv, directory, *args, **kwargs):
                directory.mkdir()
                setup._json(directory / "receipt.json", {"argv": argv, "failure": "synthetic failure"})
                raise RuntimeError("original failure")

            with patch.object(setup, "_command", side_effect=failed) as call:
                with self.assertRaisesRegex(RuntimeError, "original failure"):
                    steps.run("failure", ["not-executed.exe"])
                self.assertEqual(call.call_count, 1)
            self.assertEqual(len(steps.rows), 1)
            self.assertEqual(steps.rows[0]["path"], "commands/00-failure/receipt.json")

    def test_source_excludes_only_untracked_generated_sdk_tree_and_records_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.lock").write_bytes(b"synthetic lock")
            source = root / "tools/optimization_kubernetes/setup.py"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"synthetic source")
            steps = setup._Steps(root, root)
            with patch.object(steps, "run", side_effect=["", "", "a" * 40, "b" * 40]) as run:
                identity = steps.source("git.exe", "before")
                self.assertEqual(identity["excluded_generated_path"], "sdk/dotnet/Latent.Sdk/target/")
                status_argv = run.call_args_list[1].args[1]
                self.assertEqual(status_argv[-3:], ["--", ".", ":(exclude)sdk/dotnet/Latent.Sdk/target/**"])
                self.assertIn("--untracked-files=all", status_argv)
            with patch.object(steps, "run", return_value="sdk/dotnet/Latent.Sdk/target/tracked.txt"):
                with self.assertRaisesRegex(ValueError, "excluded-generated-tree-is-tracked"):
                    steps.source("git.exe", "before")
            with patch.object(steps, "run", side_effect=["", "?? unrelated.txt"]):
                with self.assertRaisesRegex(ValueError, "source-dirty"):
                    steps.source("git.exe", "before")


class KubernetesKindAcquisition(unittest.TestCase):
    class Response(io.BytesIO):
        status = 200

        def __init__(self, value):
            super().__init__(value)
            self.headers = {"Content-Length": str(len(value))}

        def geturl(self):
            return "https://release-assets.githubusercontent.com/example?temporary-signature=redacted"

    def test_verified_small_download_retains_hash_and_closes_without_secret_query(self):
        data = b"synthetic verified kind executable"
        response = self.Response(data)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "private").mkdir()
            with patch.object(setup, "urlopen", return_value=response), patch.object(setup, "KIND_BYTES", len(data)), \
                    patch.object(setup, "KIND_SHA256", hashlib.sha256(data).hexdigest()), \
                    patch.object(setup, "_space", return_value=setup.HEADROOM + 32 * 1024**2):
                path = setup._acquire_kind(root)
            self.assertEqual(path.read_bytes(), data)
            receipt = json.loads((root / "kind-download.json").read_text())
            self.assertTrue(response.closed and receipt["response_closed"] and receipt["file_closed"])
            self.assertNotIn("?", receipt["final_url"])
            self.assertIsNone(receipt["failure"])

    def test_wrong_digest_retains_failed_original_and_does_not_execute_it(self):
        data = b"wrong synthetic binary"
        response = self.Response(data)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "private").mkdir()
            with patch.object(setup, "urlopen", return_value=response), patch.object(setup, "KIND_BYTES", len(data)), \
                    patch.object(setup, "_space", return_value=setup.HEADROOM + 32 * 1024**2):
                with self.assertRaisesRegex(ValueError, "download-identity"):
                    setup._acquire_kind(root)
            self.assertTrue(response.closed)
            self.assertEqual((root / "private/kind.exe").read_bytes(), data)
            self.assertIsNotNone(json.loads((root / "kind-download.json").read_text())["failure"])


@unittest.skipUnless(os.name == "nt", "actual Windows process ownership")
class KubernetesWindowsProcess(unittest.TestCase):
    def test_actual_child_is_resumed_reaped_and_owned_job_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = setup._command([sys.executable, "-c", "print('bounded-child')"], root / "command", root,
                                    dict(os.environ), root, timeout=10)
            self.assertEqual(result["exit_code"], 0)
            self.assertTrue(result["reaped"] and result["output_closed"] and result["job_empty"])
            self.assertGreater(int(result["creation_time_100ns"]), 0)
            self.assertEqual((root / "command/stdout.bin").read_bytes().strip(), b"bounded-child")

    def test_actual_timed_out_parent_and_descendant_leave_empty_job(self):
        code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)']); time.sleep(20)"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "command-deadline"):
                setup._command([sys.executable, "-c", code], root / "command", root, dict(os.environ), root, timeout=1)
            result = json.loads((root / "command/receipt.json").read_text())
            self.assertTrue(result["reaped"] and result["output_closed"] and result["job_empty"])
            self.assertGreaterEqual(result["job"]["total"], 2)
            self.assertIsNotNone(result["failure"])


if __name__ == "__main__":
    unittest.main()
