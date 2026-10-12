"""Closed development direct TLS configuration, not node readiness evidence."""
import copy
import json
from pathlib import Path
import re
import unittest

from tools.tests.test_node_providers_schema import ROOT, VALIDATOR


class StreamTlsSchema(unittest.TestCase):
    def example(self):
        guide = (ROOT / "docs/reference/standalone-streams.md").read_text(encoding="utf-8")
        value = json.loads(re.findall(r"```json\n(.*?)\n```", guide, re.S)[0])["providers"]
        destination = value["outboundStreams"]["configuration"]["destinations"][0]
        destination["endpoint"].update(host="stream.test", transport="host-tls")
        destination["tls"] = {"serverName": "stream.test", "roots": [{
            "file": "private-trust/root.der", "sha256": "sha256:" + "1" * 64}]}
        return value

    def test_explicit_host_tls_accepts_only_named_protected_pinned_trust(self):
        value = self.example()
        VALIDATOR.validate(value)
        original = copy.deepcopy(value)
        for key, invalid in (("clientKey", "PRIVATE"), ("publicRoots", True), ("insecure", True),
                             ("roots", []), ("roots", value["outboundStreams"]["configuration"]["destinations"][0]["tls"]["roots"] * 9)):
            changed = copy.deepcopy(original)
            changed["outboundStreams"]["configuration"]["destinations"][0]["tls"][key] = invalid
            self.assertFalse(VALIDATOR.is_valid(changed), key)

    def test_tcp_cannot_silently_use_tls_policy_and_host_tls_without_trust_is_denied(self):
        value = self.example()
        destination = value["outboundStreams"]["configuration"]["destinations"][0]
        destination["endpoint"]["transport"] = "tcp"
        self.assertFalse(VALIDATOR.is_valid(value))
        destination["endpoint"]["transport"] = "host-tls"
        del destination["tls"]
        self.assertFalse(VALIDATOR.is_valid(value))

    def test_raw_root_bytes_keys_unknown_digest_and_null_policy_are_rejected(self):
        value = self.example()
        for field, invalid in (("file", ""), ("file", "../escape/root.der"), ("file", "private/./root.der"),
                               ("sha256", "sha256:" + "A" * 64),
                               ("privateKey", "PRIVATE"), ("der", [1, 2, 3])):
            changed = copy.deepcopy(value)
            changed["outboundStreams"]["configuration"]["destinations"][0]["tls"]["roots"][0][field] = invalid
            self.assertFalse(VALIDATOR.is_valid(changed), field)
        value["outboundStreams"]["configuration"]["destinations"][0]["tls"] = None
        self.assertFalse(VALIDATOR.is_valid(value))


if __name__ == "__main__":
    unittest.main()
