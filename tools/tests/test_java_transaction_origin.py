"""Explicit private same-origin configuration; descriptions grant no data access."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from tools.java_transaction_qualification import configuration as cfg, http


class QualificationOriginOracle(unittest.TestCase):
    def test_actual_configuration_binds_only_the_selected_loopback_authority_and_tenant(self):
        from jsonschema import Draft202012Validator
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "node"
            directory.mkdir()
            original = directory / "node.json"
            value = {"cells": [{}], "execution": {}, "cache": {}, "catalogs": {}, "audit": {},
                     "retention": {}, "credentials": []}
            original.write_text(json.dumps(value))
            compiler, checkpoint, tls, credential = root / "compiler", root / "clock", root / "tls", root / "token"
            compiler.write_bytes(b"original-aot-compiler")
            checkpoint.write_bytes(b"original-clock")
            credential.write_bytes(b"private-test-only")
            tls.mkdir()
            (tls / "ca.der").write_bytes(b"original-test-ca")
            with patch.object(cfg, "configure_node", return_value=original):
                actual = cfg.configure(directory, root / "signed", compiler, tls, checkpoint, 12345, credential)
            expected = [{"authority": actual.authority, "tenant": cfg.TENANT}]
            self.assertEqual(actual.value["httpIngress"]["browserOrigins"], expected)
            self.assertEqual(actual.value["httpIngress"]["authentication"], {"mode": "bearer"})
            self.assertEqual(actual.value["state"]["operations"], [])
            self.assertEqual(actual.value["state"]["recoverySelections"], [])
            self.assertRegex(actual.authority, r"^localhost:[1-9][0-9]{0,4}$")
            selected = actual.selected(root / "selected.json", [])
            self.assertEqual(json.loads(selected.read_bytes())["httpIngress"]["browserOrigins"], expected)
            schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/node-http-ingress.schema.json").read_bytes())
            Draft202012Validator(schema).validate(actual.value["httpIngress"])
            self.assertEqual(actual.value["budgetProfile"]["maximumStateReadBytes"], 4194304)
            self.assertEqual(actual.value["budgetProfile"]["maximumStateWriteBytes"], 2097152)
            self.assertEqual(actual.value["budgetProfile"]["maximumEffects"], 1)

    def test_real_query_keeps_matching_origin_and_bearer_without_retries(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(dict(self.headers))
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        server.timeout = 2
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        authority = "localhost:" + str(server.server_port)
        peer = http.Http(authority, time.monotonic() + 5, maximum_requests=1)
        try:
            actual = peer.request("GET", "/transaction/query", headers=(("Authorization", "Bearer private-test"),))
        finally:
            thread.join(3)
            server.server_close()
        self.assertFalse(thread.is_alive())
        self.assertEqual(actual["status"], 403)
        self.assertEqual(peer.requests, 1)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["Host"], authority)
        self.assertEqual(seen[0]["Origin"], "http://" + authority)
        self.assertEqual(seen[0]["Authorization"], "Bearer private-test")
        self.assertNotIn("Content-Type", seen[0])


if __name__ == "__main__":
    unittest.main()
