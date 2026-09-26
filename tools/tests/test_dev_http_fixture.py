"""Real socket ownership and private authority for disposable HTTP fixtures."""
from __future__ import annotations

import copy
from pathlib import Path
import selectors
import socket
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from tools.dev_workflow import effects, http_fixture, http_peer, journal, node_deployment, node_fixtures, paths, state
from tools.dev_workflow.common import DevError, digest, encode


class HttpFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "test-http"
        paths.new_directory(self.root)
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            port = available.getsockname()[1]
        self.fixture = {"port": port, "exchanges": [{"method": "POST", "path": "/fixture",
            "requestBody": "aW4=", "status": 200, "responseBody": "cHJpdmF0ZS1yZXBseQ=="}]}
        self.authorization = http_fixture.credential(self.root, self.fixture, create=True)

    def peer(self):
        selector = selectors.DefaultSelector()
        self.addCleanup(selector.close)
        peer = http_peer.Peer(self.root, self.fixture, selector)
        self.addCleanup(peer.close)
        return peer, selector

    def exchange(self, peer, selector, authorization):
        stream = socket.create_connection(("127.0.0.1", self.fixture["port"]), timeout=1)
        self.addCleanup(stream.close)
        stream.sendall(b"POST /fixture HTTP/1.1\r\nHost: 127.0.0.1:" + str(self.fixture["port"]).encode()
            + b"\r\nContent-Length: 2\r\nAuthorization: " + authorization + b"\r\n\r\nin")
        stream.setblocking(False)
        reply = bytearray()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            peer.check()
            for key, events in selector.select(.01):
                peer.event(key, events)
            try:
                raw = stream.recv(4096)
                if not raw:
                    return bytes(reply)
                reply.extend(raw)
            except BlockingIOError:
                pass
        self.fail("fixture exchange exceeded its owned test deadline")

    def test_unauthenticated_client_receives_no_fixture_and_valid_client_still_works(self):
        peer, selector = self.peer()
        reply = self.exchange(peer, selector, b"Bearer wrong-workspace")
        self.assertTrue(reply.startswith(b"HTTP/1.1 401"))
        self.assertNotIn(b"private-reply", reply)
        self.assertEqual(peer.completed, 0)
        reply = self.exchange(peer, selector, self.authorization)
        self.assertTrue(reply.endswith(b"private-reply"))
        self.assertEqual(peer.completed, 1)
        self.assertEqual(peer.rejected, 1)
        self.assertNotIn(self.authorization, encode(peer.observation()))

    def test_other_workspace_has_distinct_credential_and_cannot_contact_peer(self):
        other = self.root.parent / "test-other"
        paths.new_directory(other)
        second = http_fixture.credential(other, self.fixture, create=True)
        self.assertNotEqual(second, self.authorization)
        peer, selector = self.peer()
        self.assertTrue(self.exchange(peer, selector, second).startswith(b"HTTP/1.1 401"))

    def test_live_listener_cannot_be_replaced_and_clean_shutdown_allows_restart(self):
        peer, selector = self.peer()
        with self.assertRaisesRegex(DevError, "port-unavailable"):
            http_peer.Peer(self.root, self.fixture, selector)
        self.exchange(peer, selector, self.authorization)
        self.assertEqual(peer.close()["openConnections"], 0)
        restarted = http_peer.Peer(self.root, self.fixture, selector)
        self.addCleanup(restarted.close)
        self.assertTrue(self.exchange(restarted, selector, self.authorization).endswith(b"private-reply"))

    def test_partial_unauthenticated_request_times_out_without_stopping_owned_peer(self):
        peer, selector = self.peer()
        stream = socket.create_connection(("127.0.0.1", self.fixture["port"]), timeout=1)
        self.addCleanup(stream.close)
        stream.sendall(b"POST /fixture")
        for key, events in selector.select(1):
            peer.event(key, events)
        self.assertEqual(len(peer.clients), 1)
        next(iter(peer.clients.values()))["deadline"] = time.monotonic() - 1
        peer.check()
        self.assertEqual(len(peer.clients), 0)
        self.assertIsNone(peer.failure)

    def test_changed_selection_and_credential_are_not_silently_rotated(self):
        changed = copy.deepcopy(self.fixture)
        changed["exchanges"][0]["status"] = 201
        with self.assertRaisesRegex(DevError, "credential-changed"):
            http_fixture.credential(self.root, changed, create=True)
        state.atomic(self.root / "http-fixture-private", "owner.json", {
            "purpose": "disposable-http-fixture", "fixture": digest(encode(self.fixture)),
            "credentialSha256": "sha256:" + "0" * 64})
        with self.assertRaisesRegex(DevError, "credential-changed"):
            http_fixture.credential(self.root, self.fixture, create=True)

    def test_fixture_needs_matching_running_peer_observation(self):
        selected = {"http": self.fixture}
        raw = encode(selected)
        paths.write_new(self.root / "fixture.json", raw)
        cases = [{"fixtures": [{"id": "http", "kind": "controlled-peer", "identity": digest(raw),
                               "configuration": "fixture.json"}]}]
        self.assertEqual(node_fixtures.initialized(self.root, cases, selected), set())
        peer, _selector = self.peer()
        self.assertEqual(node_fixtures.initialized(self.root, cases, selected, {"http": peer.observation()}), {"http"})
        self.assertEqual(node_fixtures.initialized(self.root, cases, selected, {"http": peer.close()}), set())

    def test_fixture_rejects_redirects_ambient_hosts_and_duplicate_exchanges(self):
        for changed in ({**self.fixture, "host": "example.com"}, {**self.fixture, "port": 80},
                        {**self.fixture, "exchanges": self.fixture["exchanges"] * 2},
                        {**self.fixture, "exchanges": [{**self.fixture["exchanges"][0], "status": 302}]}):
            with self.assertRaises(DevError):
                http_fixture.validate(changed)


class HttpDeploymentRecovery(unittest.TestCase):
    """The after-denial switch must reconcile, not repeat, its original apply."""

    def setUp(self):
        self.prepare()

    def prepare(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "test-http-deployment"
        paths.new_directory(self.root)
        self.controller = journal.Journal(self.root, "node", "examples",
            settle=lambda operation, result: effects.settle(self.root, operation, result))
        self.intent = {"source": "sha256:" + "a" * 64, "componentDigest": "sha256:" + "c" * 64,
            "publication": "published-http", "deployment": "http", "expectedGeneration": "4", "expectedStateVersion": "7"}
        self.previous = {"generation": "4", "publication": "published-http", "operation": "denied-grants"}
        state.atomic(self.root, "last-deployment.json", self.previous)
        self.mutation = Mock(return_value=self.lost())
        self.deploy = Mock(side_effect=lambda: self.controller.execute("deployment", self.intent, self.mutation))
        self.cli = Mock()
        self.cli.call.side_effect = lambda *arguments, **_options: self.response(arguments[-1])

    def lost(self):
        return {"category": "platform-failure", "outcomeKnown": False, "requestDispatched": True,
                "error": {"code": "unavailable"}, "data": {}}

    def response(self, operation):
        return {"category": "success", "outcomeKnown": True, "data": {
            "lookup": "DEPLOYMENT_OPERATION_LOOKUP_DISPOSITION_FOUND", "durability": "DEPLOYMENT_DURABILITY_CONFIRMED",
            "receipt": {"operationId": operation, "tenant": "examples", "componentDigest": self.intent["componentDigest"],
                "publication": {"id": "published-http", "tenant": "examples"}, "deploymentId": "http",
                "expectedGeneration": "4", "expectedStateVersion": "7", "objectGeneration": "5",
                "routeGeneration": "5", "stateVersion": "8", "action": "DEPLOYMENT_OPERATION_ACTION_APPLY"}}}

    def switch(self, deadline=None):
        return node_deployment.switch(self.cli, self.controller, self.deploy,
                                      time.monotonic() + 60 if deadline is None else deadline)

    def assert_retained(self):
        self.deploy.assert_called_once_with()
        self.mutation.assert_called_once()
        self.assertEqual(self.controller.read()["pending"]["id"], self.mutation.call_args.args[0])
        self.assertEqual(self.controller.read()["history"], [])
        self.assertEqual(state.load(self.root, "last-deployment.json"), self.previous)

    def test_lost_after_denial_reply_recovers_original_and_settles_generation_once(self):
        result = self.switch()
        original = self.mutation.call_args.args[0]
        self.assertEqual(result, {"operationId": original, "queries": 1, "disposition": "original-receipt-confirmed"})
        self.deploy.assert_called_once_with()
        self.mutation.assert_called_once_with(original)
        self.assertEqual(self.cli.call.call_args.args[2:], ("deployment", "operation", original))
        self.assertIsNone(self.controller.read()["pending"])
        self.assertEqual(len(self.controller.read()["history"]), 1)
        saved = state.load(self.root, "last-deployment.json")
        self.assertEqual((saved["operation"], saved["generation"], saved["publication"]), (original, "5", "published-http"))
        self.assertEqual(state.load(self.root, "last-operation-observation.json")["code"], "unavailable")

    def test_helper_and_scenario_journals_reconcile_the_same_durable_intent(self):
        helper_journal = journal.Journal(self.root, "node", "examples",
            settle=lambda operation, result: effects.settle(self.root, operation, result))
        self.deploy.side_effect = lambda: helper_journal.execute("deployment", self.intent, self.mutation)
        result = self.switch()
        self.mutation.assert_called_once()
        self.assertIsNone(helper_journal.read()["pending"])
        self.assertEqual(self.controller.read(), helper_journal.read())
        self.assertEqual(state.load(self.root, "last-deployment.json")["operation"], result["operationId"])

    def test_healthy_apply_has_no_recovery_read(self):
        self.mutation.side_effect = self.response
        self.assertIsNone(self.switch())
        self.deploy.assert_called_once_with()
        self.mutation.assert_called_once()
        self.cli.call.assert_not_called()
        self.assertIsNone(self.controller.read()["pending"])

    def test_transport_failure_repeats_only_the_original_receipt_read(self):
        def lookup(*arguments, **_options):
            return self.lost() if self.cli.call.call_count == 1 else self.response(arguments[-1])
        self.cli.call.side_effect = lookup
        with patch.object(node_deployment.time, "sleep"):
            result = self.switch()
        self.assertEqual(result["queries"], 2)
        self.mutation.assert_called_once()
        self.assertEqual([call.args[2:] for call in self.cli.call.call_args_list],
                         [("deployment", "operation", result["operationId"])] * 2)

    def test_exhausted_transport_reads_keep_pending_and_last_confirmed_deployment(self):
        self.cli.call.side_effect = None
        self.cli.call.return_value = self.lost()
        with patch.object(node_deployment.time, "sleep"), self.assertRaisesRegex(DevError, "outcome-uncertain") as error:
            self.switch()
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(self.cli.call.call_count, 3)
        self.assert_retained()

    def test_semantic_unknown_and_uncertain_are_not_polled_or_replayed(self):
        for disposition in ("UNKNOWN", "UNCERTAIN"):
            with self.subTest(disposition=disposition):
                self.prepare()
                self.cli.call.side_effect = lambda *arguments, **_options: {
                    "category": "success", "outcomeKnown": True,
                    "data": {"lookup": "DEPLOYMENT_OPERATION_LOOKUP_DISPOSITION_" + disposition}}
                with self.assertRaisesRegex(DevError, "no-replay") as error:
                    self.switch()
                self.assertTrue(error.exception.uncertain)
                self.cli.call.assert_called_once()
                self.assert_retained()

    def test_bad_receipt_identity_preconditions_target_and_durability_fail_closed(self):
        mutations = (
            lambda value: value["data"]["receipt"].update(operationId="other"),
            lambda value: value["data"]["receipt"].update(tenant="other"),
            lambda value: value["data"]["receipt"].update(expectedGeneration="3"),
            lambda value: value["data"]["receipt"].update(expectedStateVersion="6"),
            lambda value: value["data"]["receipt"].update(componentDigest="sha256:" + "d" * 64),
            lambda value: value["data"]["receipt"]["publication"].update(id="other"),
            lambda value: value["data"]["receipt"].update(deploymentId="other"),
            lambda value: value["data"]["receipt"].update(routeGeneration="4"),
            lambda value: value["data"]["receipt"].update(stateVersion="9"),
            lambda value: value["data"].update(durability="uncertain"),
            lambda value: value["data"].pop("receipt"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                self.prepare()
                def lookup(*arguments, **_options):
                    value = self.response(arguments[-1])
                    mutate(value)
                    return value
                self.cli.call.side_effect = lookup
                with self.assertRaises(DevError) as error:
                    self.switch()
                self.assertTrue(error.exception.uncertain)
                self.cli.call.assert_called_once()
                self.assert_retained()

    def test_existing_pending_operation_blocks_both_new_apply_and_recovery(self):
        original = self.controller.begin("deployment", self.intent)
        with self.assertRaisesRegex(DevError, "recover-original"):
            self.switch()
        self.deploy.assert_not_called()
        self.cli.call.assert_not_called()
        self.assertEqual(self.controller.read()["pending"], original)

    def test_non_deployment_uncertainty_is_never_adopted(self):
        self.deploy.side_effect = lambda: self.controller.execute("release", self.intent, self.mutation)
        with self.assertRaisesRegex(DevError, "outcome-uncertain"):
            self.switch()
        self.cli.call.assert_not_called()
        self.assertEqual(self.controller.read()["pending"]["kind"], "release")
        self.assert_retained()

    def test_rejected_invalid_or_unreaped_apply_is_not_recovered(self):
        for error in (DevError("operator-request-rejected-last-deployment-retained"),
                      DevError("confirmed-deployment-generation", uncertain=True),
                      DevError("owned-process-cleanup-unconfirmed", uncertain=True),
                      DevError("operation-outcome-uncertain-use-recover"), OSError("lost client")):
            with self.subTest(error=str(error)):
                self.prepare()
                self.mutation.side_effect = error
                with self.assertRaises(type(error)):
                    self.switch()
                self.cli.call.assert_not_called()
                self.assert_retained()

    def test_lookup_validation_or_cleanup_failure_stops_further_clients(self):
        for error in (DevError("operator-response-format"),
                      DevError("owned-process-cleanup-unconfirmed", uncertain=True), OSError("lookup failed")):
            with self.subTest(error=str(error)):
                self.prepare()
                self.cli.call.side_effect = error
                with self.assertRaises(DevError) as caught:
                    self.switch()
                self.assertTrue(caught.exception.uncertain)
                self.cli.call.assert_called_once()
                self.assert_retained()

    def test_recovery_uses_remaining_scenario_deadline_for_rpc_and_process(self):
        clock = Mock()
        clock.monotonic.side_effect = [10, 10, 10.25]
        with patch.object(node_deployment, "time", clock):
            self.switch(deadline=10.75)
        call = self.cli.call.call_args
        self.assertEqual(call.args[:2], ("--rpc-timeout-ms", "500"))
        self.assertEqual(call.kwargs["timeout"], .5)

    def test_recovery_has_its_own_five_second_cap(self):
        clock = Mock()
        clock.monotonic.side_effect = [10, 10, 15]
        with patch.object(node_deployment, "time", clock), self.assertRaisesRegex(DevError, "outcome-uncertain"):
            self.switch(deadline=100)
        self.cli.call.assert_not_called()
        self.assert_retained()

    def test_expired_scenario_deadline_does_not_start_mutation_or_recovery(self):
        with self.assertRaisesRegex(DevError, "node-test-run-deadline"):
            self.switch(deadline=0)
        self.deploy.assert_not_called()
        self.cli.call.assert_not_called()
        self.assertIsNone(self.controller.read()["pending"])

    def test_plain_journal_still_requires_explicit_recovery_and_never_replays(self):
        with self.assertRaisesRegex(DevError, "outcome-uncertain"):
            self.deploy()
        with self.assertRaisesRegex(DevError, "recover-original"):
            self.controller.execute("deployment", self.intent, self.mutation)
        self.cli.call.assert_not_called()
        self.assert_retained()


if __name__ == "__main__":
    unittest.main()
