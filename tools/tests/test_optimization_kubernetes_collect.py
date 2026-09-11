"""Cleanup fault tests use isolated files and fake APIs, never infrastructure."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tools.optimization_kubernetes import model
from tools.optimization_kubernetes.collect import Campaign


class CleanupTests(unittest.TestCase):
    def campaign(self, directory):
        value = Campaign.__new__(Campaign)
        value.owner, value.run_id = "lsf-112-123456abcdef", "smoke-01"
        value.namespace = model.namespace_name(value.owner, value.run_id)
        value.root = directory / value.run_id
        value.root.mkdir()
        value.bootstrap_path = directory / "bootstrap.json"
        value.private_directory = directory / "private" / ("tls-" + value.run_id)
        value.private_directory.mkdir(parents=True)
        for name in ("ca.pem", "client.pem", "client.key"):
            (value.private_directory / name).write_bytes(b"test-only")
        value.namespace_attempted = value.remote_attempted = True
        value.namespace_uid = "owned-namespace-uid"
        value.remote_root = model.host_path(value.owner, value.run_id)
        value.sessions, value.delete_receipts = [], []
        value.preparations, value.transfers = [], []
        value.pending_pods, value.pods = set(), {}
        value.api, value.worker = Mock(), Mock()
        value.worker.json.side_effect = [({"containers": []}, 1), ({"containers": []}, 2),
                                        ({"items": []}, 3), ({"items": []}, 4)]
        value.worker.command.return_value = (b"", 5)
        return value

    def test_replaced_namespace_blocks_every_destructive_api_and_worker_action(self):
        with tempfile.TemporaryDirectory() as root:
            campaign = self.campaign(Path(root))
            item = model.namespace(campaign.owner, campaign.run_id)
            item["metadata"]["uid"] = "replacement-uid"
            campaign.api.call.return_value = (item, 0)
            result = campaign.cleanup()
            self.assertEqual(len(result["errors"]), 1)
            self.assertEqual([row.args[0] for row in campaign.api.call.call_args_list], ["GET"])
            campaign.worker.command.assert_not_called()
            campaign.worker.json.assert_not_called()
            self.assertTrue(result["private_tls_removed"])

    def test_absent_namespace_and_empty_runtime_allow_only_canonical_run_data_removal(self):
        with tempfile.TemporaryDirectory() as root:
            campaign = self.campaign(Path(root))
            campaign.api.call.return_value = ({"kind": "Status", "code": 404}, 0)
            result = campaign.cleanup()
            self.assertEqual(result["errors"], [])
            self.assertTrue(result["remote_removed"] and result["namespace_absent"])
            args = campaign.worker.command.call_args.args[0]
            self.assertEqual(args[-1], campaign.remote_root)
            self.assertEqual(args[:2], ["sh", "-c"])
            self.assertIn('--one-file-system', args[2])
            self.assertFalse(campaign.private_directory.exists())

    def test_live_or_unrecognized_runtime_owner_prevents_removal(self):
        for state in ("CONTAINER_RUNNING", "CONTAINER_EXITED"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as root:
                campaign = self.campaign(Path(root))
                campaign.api.call.return_value = ({"kind": "Status", "code": 404}, 0)
                campaign.worker.json.side_effect = [({"containers": [{"id": "a" * 64,
                    "state": state, "labels": {"io.kubernetes.pod.namespace": campaign.namespace,
                        "io.kubernetes.pod.uid": "unrecorded", "io.kubernetes.pod.name": "unexpected"}}]}, 1)]
                result = campaign.cleanup()
                self.assertEqual(len(result["errors"]), 1)
                self.assertFalse(result["remote_removed"])
                campaign.worker.command.assert_not_called()

    def test_private_directory_extra_file_is_retained_and_reported(self):
        with tempfile.TemporaryDirectory() as root:
            campaign = self.campaign(Path(root))
            campaign.api.call.return_value = ({"kind": "Status", "code": 404}, 0)
            extra = campaign.private_directory / "unexpected"
            extra.write_bytes(b"keep")
            result = campaign.cleanup()
            self.assertEqual(result["errors"][0]["stage"], "private-tls")
            self.assertEqual(extra.read_bytes(), b"keep")
            self.assertTrue((campaign.private_directory / "client.key").exists())

    def test_altered_remote_path_never_reaches_shell(self):
        with tempfile.TemporaryDirectory() as root:
            campaign = self.campaign(Path(root))
            campaign.remote_root += "/.."
            campaign.api.call.return_value = ({"kind": "Status", "code": 404}, 0)
            result = campaign.cleanup()
            self.assertEqual(len(result["errors"]), 1)
            campaign.worker.command.assert_not_called()

    def test_failed_diagnostic_download_keeps_remote_output_for_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            campaign = self.campaign(Path(root))
            campaign.api.call.return_value = ({"kind": "Status", "code": 404}, 0)
            campaign.preparations = [{"relative": "owners/app", "destination": campaign.remote_root + "/owners/app"}]
            campaign.download_directory = Mock(side_effect=OSError("retain worker bytes"))
            result = campaign.cleanup(failed=True)
            self.assertFalse(result["remote_removed"])
            self.assertEqual(len(result["errors"]), 1)
            campaign.worker.command.assert_not_called()
            campaign.download_directory.assert_called_once()

    def test_unfinished_output_is_copied_after_quiescence_before_remote_removal(self):
        with tempfile.TemporaryDirectory() as root:
            campaign = self.campaign(Path(root))
            campaign.api.call.return_value = ({"kind": "Status", "code": 404}, 0)
            completed = campaign.remote_root + "/owners/completed"
            pending = campaign.remote_root + "/clients/0"
            campaign.preparations = [{"relative": "owners/completed", "destination": completed},
                                     {"relative": "clients/0", "destination": pending}]
            campaign.transfers = [{"remote": completed}]

            def download(remote, _local):
                self.assertEqual(campaign.worker.json.call_count, 4)
                campaign.worker.command.assert_not_called()
                self.assertEqual(remote, pending)
                return {"remote": remote, "retained": True}

            campaign.download_directory = Mock(side_effect=download)
            result = campaign.cleanup(failed=True)
            self.assertEqual(result["errors"], [])
            self.assertTrue(result["remote_removed"])
            self.assertEqual(result["failure_diagnostics"], [{"remote": pending, "retained": True}])
            campaign.download_directory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
