from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.java_guest.model import Graph
from tools.java_guest import java, c


def document():
    return {"worlds": [{"name": "service", "imports": {}, "exports": {"interface-0": {"interface": {"id": 0}}}, "package": 0}],
            "interfaces": [{"name": "api", "package": 0, "types": {}, "functions": {"run": {
                "name": "run", "kind": "freestanding", "params": [{"name": "value", "type": "u64"}], "result": 0}}}],
            "types": [{"name": None, "kind": {"result": {"ok": "s64", "err": "string"}}, "owner": None}],
            "packages": [{"name": "examples:sample@1.0.0", "interfaces": {"api": 0}, "worlds": {"service": 0}}]}


HEADER = "void exports_examples_sample_api_run(uint64_t value, sample_result_t *ret);\n"


class Bindings(unittest.TestCase):
    def test_full_width_result_and_source_owned_exports_are_explicit(self):
        graph = Graph(document(), "examples:sample/service@1.0.0", HEADER)
        output = java.generate(graph)
        self.assertIn("Result<Long, String> run(Unsigned64 value)", output)
        self.assertIn("new dev.latent.app.Capsule().run(value)", output)
        self.assertIn("value.bits(), 8", output)
        self.assertNotIn("catch (", output)
        self.assertEqual(output, java.generate(graph))
        bridge = c.generate(graph)
        self.assertIn("lsf_java_free(owned)", bridge)
        self.assertIn("lsf_allocate", bridge)
        self.assertNotIn("double", bridge)

    def test_unsupported_future_and_inline_interface_fail_closed(self):
        data = document()
        data["types"][0]["kind"] = {"future": "u64"}
        with self.assertRaisesRegex(ValueError, "unsupported Java WIT type"):
            Graph(data, "service", HEADER)
        data = document()
        data["worlds"][0]["imports"]["function"] = {"function": {}}
        with self.assertRaisesRegex(ValueError, "named interface"):
            Graph(data, "service", HEADER)

    def test_exported_resources_and_resource_methods_fail_closed(self):
        data = document()
        data["types"][0] = {"name": "item", "kind": "resource", "owner": {"interface": 0}}
        with self.assertRaisesRegex(ValueError, "exported resources"):
            Graph(data, "service", HEADER)
        data = document()
        data["interfaces"][0]["functions"]["run"]["kind"] = {"method": 0}
        with self.assertRaisesRegex(ValueError, "resource constructors"):
            Graph(data, "service", HEADER)

    def test_current_generator_signature_must_match_unflattened_types(self):
        with self.assertRaisesRegex(ValueError, "signature not found"):
            Graph(document(), "service", "")
        with self.assertRaisesRegex(ValueError, "unexpected flattened"):
            Graph(document(), "service", "void exports_examples_sample_api_run(uint64_t value);\n")
        with self.assertRaisesRegex(ValueError, "resolve exactly once"):
            Graph(document(), "unselected", HEADER)


if __name__ == "__main__": unittest.main()
