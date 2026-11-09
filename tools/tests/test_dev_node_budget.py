"""The scenario budget is a closed, bounded numeric selection."""
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from tools.dev_workflow import common, journal, node_invocation, node_scenarios
from tools.dev_workflow.client import Client


class NodeScenarioBudget(unittest.TestCase):
    def test_defaults_timeout_and_overrides_match_the_cli_file_form(self):
        selected = node_scenarios._selected_budget(
            {"cpuFuel": 12, "memoryBytes": 34, "wallTimeLimitMillis": None,
             "childCalls": 2, "outboundRequests": 3, "blobReadBytes": 7,
             "blobWriteBytes": 8, "logBytes": 9},
            50, {"fuel": "17", "memoryBytes": "99"})
        self.assertEqual(selected, {
            "cpuFuel": 17, "memoryBytes": 99, "wallTimeLimitMillis": 50,
            "childCalls": 2, "outboundRequests": 3, "blobReadBytes": 7,
            "blobWriteBytes": 8, "logBytes": 9,
        })
        self.assertEqual(node_scenarios._selected_budget({"wallTimeLimitMillis": 25}, 50, None)
                         ["wallTimeLimitMillis"], 25)
        self.assertEqual(node_scenarios._selected_budget({"wallTimeLimitMillis": 0}, 50, None)
                         ["wallTimeLimitMillis"], 50)

    def test_invalid_or_secret_values_never_become_numeric_arguments(self):
        for value in ({"cpuFuel": "private-value"}, {"cpuFuel": True},
                      {"cpuFuel": 1.5}, {"cpuFuel": -1}, {"cpuFuel": 2**64},
                      {"childCalls": 2**32}, {"outboundRequests": 2**32},
                      {"effectCount": 2**32}, {"wallTimeLimitMillis": False},
                      {"unknown": 1}):
            with self.subTest(value=value), self.assertRaises(common.DevError):
                node_scenarios._selected_budget(value, 10, None)
        for value in ("123 secret", "-1", "0", True):
            with self.subTest(execution=value), self.assertRaises(common.DevError):
                node_scenarios._selected_budget({}, 10, {"fuel": value})

    def test_integer_widths_and_all_fields_remain_distinct(self):
        raw = {name: (2**32 - 1 if maximum == 2**32 - 1 else 2**64 - 1)
               for name, maximum in node_scenarios._BUDGET_FIELDS.items()}
        selected = node_scenarios._selected_budget(raw, 500, None)
        self.assertEqual(selected["wallTimeLimitMillis"], 500)
        self.assertEqual(selected["childCalls"], 2**32 - 1)
        self.assertEqual(selected["blobWriteBytes"], 2**64 - 1)
        self.assertEqual(len(selected), 11)

    def test_allowed_field_names_and_widths_match_the_actual_cli_budget(self):
        source = (Path(__file__).resolve().parents[2] / "apps/latent/src/invocation/budget.rs").read_text()
        definition = source.split("pub struct Budget {", 1)[1].split("}", 1)[0]
        fields = re.findall(r"^\s*(\w+):\s*(u32|u64|Option<u64>),", definition, re.MULTILINE)
        def camel(name):
            first, *rest = name.split("_")
            return first + "".join(word.title() for word in rest)
        self.assertEqual({camel(name): 2**(32 if kind == "u32" else 64) - 1
                          for name, kind in fields}, node_scenarios._BUDGET_FIELDS)

    def test_unknown_result_retains_the_original_budget_identity_without_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller = journal.Journal(Path(temporary), "node", "examples")
            budget = node_scenarios._selected_budget({"cpuFuel": 12}, 10, None)
            raw = common.encode(budget).removesuffix(b"\n")
            intent = {"budgetSha256": common.digest(raw), "budgetProfile": "phase1"}
            client = Mock()
            invocation = Mock(side_effect=common.DevError("owned-process-cleanup-unconfirmed", uncertain=True))
            result = node_invocation.execute(client, controller, intent, invocation, time.monotonic() + 5)
            pending = controller.read()["pending"]
            self.assertEqual(pending["intent"], intent)
            self.assertEqual(result["data"]["activationId"], pending["id"])
            self.assertEqual(result["data"]["recovery"]["clientCleanup"], "unconfirmed")
            invocation.assert_called_once()
            client.call.assert_not_called()
            with self.assertRaisesRegex(common.DevError, "recover-original"):
                node_invocation.execute(client, controller, intent, invocation, time.monotonic() + 5)
            invocation.assert_called_once()

    @unittest.skipUnless(os.name == "posix", "owned-process control uses a POSIX executable")
    def test_owned_child_receives_the_selected_numeric_document_and_private_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable, marker = root / "cli-double", root / "pid"
            executable.write_text(
                f"#!{sys.executable}\n"
                "import hashlib,json,os,pathlib,sys\n"
                f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\n"
                "budget=sys.argv[sys.argv.index('--budget-json')+1]\n"
                "raw=sys.stdin.buffer.read()\n"
                "print(json.dumps({'schemaVersion':'latent.cli.result.v1','category':'success',"
                "'outcomeKnown':True,'data':{'budget':budget,'inputSha256':'sha256:'+hashlib.sha256(raw).hexdigest()}}))\n"
            )
            executable.chmod(0o700)
            budget = node_scenarios._selected_budget({"cpuFuel": 12}, 10, None)
            encoded = common.encode(budget).removesuffix(b"\n").decode("ascii")
            raw = b"private-opaque-input\0\xff"
            result = Client(executable, root / "config.json", root).call(
                "invoke", "--budget-json", encoded, "--input", "-", stdin=raw, timeout=5)
            self.assertEqual(result["data"], {"budget": encoded, "inputSha256": common.digest(raw)})
            with self.assertRaises(ChildProcessError):
                os.waitpid(int(marker.read_text()), os.WNOHANG)


if __name__ == "__main__":
    unittest.main()
