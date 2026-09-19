"""Validate the operator's HTTP ingress example and closed transport profiles."""
import copy
import json
from pathlib import Path
import re
import unittest

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas/node-http-ingress.schema.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
LOCAL = {"formatVersion": 1, "bind": "127.0.0.1:8080",
         "transport": {"mode": "loopback"}, "authentication": {"mode": "bearer"}}


class NodeHttpIngressSchema(unittest.TestCase):
    def test_documented_tls_configuration_and_public_adapter(self):
        VALIDATOR.check_schema(SCHEMA)
        guide = (ROOT / "docs/reference/http-ingress.md").read_text(encoding="utf-8")
        examples = [json.loads(text) for text in re.findall(r"```json\n(.*?)\n```", guide, re.S)]
        self.assertEqual(len(examples), 2)
        self.assertEqual(examples[0]["limits"]["maximumPayloadBytes"], 2097152)
        VALIDATOR.validate(examples[0]["httpIngress"])
        public = copy.deepcopy(LOCAL)
        public["authentication"] = examples[1]
        VALIDATOR.validate(public)
        for name, field in SCHEMA["properties"]["limits"]["properties"].items():
            self.assertEqual(examples[0]["httpIngress"]["limits"][name], field["default"])

    def test_closed_profiles_do_not_infer_proxy_trust_or_public_authority(self):
        VALIDATOR.validate(LOCAL)
        for field, values in {
            "transport": [None, {"mode": "tls"}, {"mode": "loopback", "peers": []},
                          {"mode": "trusted-proxy", "peers": []},
                          {"mode": "trusted-proxy", "peers": ["127.0.0.1"] * 2},
                          {"mode": "tls", "certificateFile": "c.pem", "privateKeyFile": ""}],
            "authentication": [None, {"mode": "anonymous"}, {"mode": "bearer", "tenant": "admin"},
                               {"mode": "public-origins", "origins": []},
                               {"mode": "public-origins", "origins": [{"authority": "web.test"}]}],
            "limits": [None, {"unbounded": True}],
            "formatVersion": [None, 2],
        }.items():
            for value in values:
                invalid = dict(LOCAL, **{field: value})
                self.assertFalse(VALIDATOR.is_valid(invalid), (field, value))
        for value in (None, {}, dict(LOCAL, unknown=True)):
            self.assertFalse(VALIDATOR.is_valid(value))

    def test_individual_resource_bounds(self):
        for name, field in SCHEMA["properties"]["limits"]["properties"].items():
            for value in (field["minimum"], field["default"], field["maximum"]):
                VALIDATOR.validate(dict(LOCAL, limits={name: value}))
            for value in (field["minimum"] - 1, field["maximum"] + 1, None, True, 1.5):
                self.assertFalse(VALIDATOR.is_valid(dict(LOCAL, limits={name: value})), (name, value))

    def test_browser_bindings_are_bounded_closed_and_not_credentials(self):
        binding = {"authority": "web.example.test", "tenant": "example"}
        VALIDATOR.validate(dict(LOCAL, browserOrigins=[]))
        VALIDATOR.validate(dict(LOCAL, browserOrigins=[binding]))
        for value in (None, {}, [None], [{}], [dict(binding, credential="never-a-binding")],
                      [dict(binding, tenant="")], [binding, binding],
                      [dict(binding, authority=f"web{index}.example.test") for index in range(33)]):
            self.assertFalse(VALIDATOR.is_valid(dict(LOCAL, browserOrigins=value)), value)
        guide = (ROOT / "docs/security/browser-boundary.md").read_text(encoding="utf-8")
        examples = [json.loads(text) for text in re.findall(r"```json\n(.*?)\n```", guide, re.S)]
        self.assertEqual(len(examples), 1)
        VALIDATOR.validate(dict(LOCAL, **examples[0]))


if __name__ == "__main__":
    unittest.main()
