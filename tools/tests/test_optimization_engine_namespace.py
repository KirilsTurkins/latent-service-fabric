"""Bounded binary/descriptor unit fixtures, not a release evidence graph."""
import copy
import unittest

from tools.optimization_backend_revision.engine import namespace, schedule
from tools.optimization_evidence.common import EvidenceError
from tools.optimization_runner.fixtures import contracts, signed


def section(kind, data, length=None):
    return bytes((kind,)) + (namespace.leb(len(data)) if length is None else length) + data


def export(name, discriminator=0, index=b"\0", kind=5, optional_type=0):
    encoded = name.encode("utf-8")
    return bytes((discriminator,)) + namespace.leb(len(encoded)) + encoded + bytes((kind,)) + index + bytes((optional_type,))


class EngineNamespaceTests(unittest.TestCase):
    def test_only_outer_names_change_preserving_order_and_other_encodings(self):
        first, second = namespace.exports("generic")
        # Opaque nested/custom payloads deliberately also contain original names.
        # Only the outer export section is decoded by this bounded unit fixture.
        nested = section(4, namespace.HEADER + section(11, b"\1" + export(first)))
        self.assertEqual(len(b"\3tag" + first.encode()), 33)
        # Preserve a noncanonical but legal outer section length.
        custom = section(0, b"\3tag" + first.encode(), b"\xa1\0")
        tail = section(0, b"\4tail" + second.encode())
        payload = b"\x82\0" + export(second, 1, b"\x81\0") + export(first)
        before = namespace.HEADER + custom + nested
        base = before + section(11, payload) + tail
        changed = namespace.retarget(base, "tests", "engine-a", (first, second))
        expected = b"\x82\0" + export(second.replace("tests:", "engine-a:"), 1, b"\x81\0")
        expected += export(first.replace("tests:", "engine-a:"))
        self.assertEqual(changed, before + section(11, expected) + tail)
        self.assertIn(first.encode(), changed[:len(before)])
        self.assertEqual(base, before + section(11, payload) + tail)

    def test_split_exports_keep_section_positions_and_empty_sections(self):
        first, second = namespace.exports("generic")
        # Actual maintained generic components use two outer export sections.
        # This framing fixture also checks untouched padding in an empty section.
        empty = section(11, b"\x80\0", b"\x82\0")
        middle = section(5, b"\0")
        base = namespace.HEADER + empty + section(11, b"\1" + export(second, 1))
        base += middle + section(11, b"\1" + export(first, index=b"\x80\0"))
        changed = namespace.retarget(base, "tests", "engine-a", (first, second))
        expected = namespace.HEADER + empty + section(11, b"\1" + export(second.replace("tests:", "engine-a:"), 1))
        expected += middle + section(11, b"\1" + export(first.replace("tests:", "engine-a:"), index=b"\x80\0"))
        self.assertEqual(changed, expected)
        self.assertEqual(namespace.retarget(base, "tests", "tests", (first, second)), base)
        padded_name = b"\0" + bytes((len(first) | 128, 0)) + first.encode() + b"\5\0\0"
        unchanged = namespace.HEADER + section(11, b"\1" + padded_name)
        self.assertEqual(namespace.retarget(unchanged, "tests", "tests", (first,)), unchanged)
        for payload in (section(11, b"\1" + export(first)) * 2,
                        section(11, b"\1" + export(first)) + middle,
                        section(11, b"\1" + export(first)) + section(11, b"\1" + export("tests:foreign/api@0.1.0"))):
            with self.subTest(payload=payload), self.assertRaises(EvidenceError):
                namespace.retarget(namespace.HEADER + payload, "tests", "engine-a", (first, second))

    def test_all_fixed_targets_match_outer_exports_and_b_marker_is_last(self):
        releases = set()
        for tenant, _, contract, family in schedule.TARGETS:
            with self.subTest(tenant=tenant, family=family):
                original = namespace.exports(family)
                base = namespace.HEADER + section(11, namespace.leb(len(original)) + b"".join(export(name) for name in original))
                changed = namespace.component(base, family, tenant)
                names = namespace.exports(family, tenant)
                expected = namespace.HEADER + section(11, namespace.leb(len(names)) + b"".join(export(name) for name in names))
                if tenant == "engine-b":
                    marker = b"latent.engine-fixture.tenant-b"
                    expected += section(0, namespace.leb(len(marker)) + marker + (family + "/v1").encode())
                self.assertEqual(changed, expected)
                self.assertIn(contract, names)
                self.assertTrue(contract.startswith(tenant + ":"))
                self.assertNotEqual(changed, base)
                releases.add(changed)
        self.assertEqual(len(releases), 8)

    def test_export_set_and_framing_mutations_are_rejected(self):
        name = namespace.exports("echo")[0]
        payload = b"\1" + export(name)
        valid = namespace.HEADER + section(11, payload)
        self.assertTrue(namespace.retarget(valid, "examples", "engine-a", (name,)))
        mutations = {
            "core-header": b"\0asm\1\0\0\0" + valid[8:],
            "missing": namespace.HEADER + section(0, b""),
            "duplicate-section": valid + section(11, payload),
            "unknown-section": valid + section(12, b""),
            "section-truncated": valid[:-1],
            "u32-overflow": namespace.HEADER + b"\x0b\xff\xff\xff\xff\x10",
            "u32-too-long": namespace.HEADER + b"\x0b\x80\x80\x80\x80\x80\0",
            "name-options": namespace.HEADER + section(11, b"\1" + export(name, discriminator=2)),
            "wrong-kind": namespace.HEADER + section(11, b"\1" + export(name, kind=1)),
            "typed-export": namespace.HEADER + section(11, b"\1" + export(name, optional_type=1)),
            "foreign-prefix": namespace.HEADER + section(11, b"\1" + export(name.replace("examples:", "tests:"))),
            "count-crossed": namespace.HEADER + section(11, b"\2" + export(name)),
            "trailing": namespace.HEADER + section(11, payload + b"\0"),
            "invalid-utf8": namespace.HEADER + section(11, b"\1\0\1\xff\5\0\0"),
            "oversized-name": namespace.HEADER + section(11, b"\1\0" + namespace.leb(257)),
            "too-many-sections": namespace.HEADER + section(0, b"") * 4096 + section(11, payload),
        }
        for label, data in mutations.items():
            with self.subTest(label=label), self.assertRaises(EvidenceError):
                namespace.retarget(data, "examples", "engine-a", (name,))
        generic = namespace.exports("generic")
        duplicate = namespace.HEADER + section(11, b"\2" + export(generic[0]) * 2)
        with self.assertRaisesRegex(EvidenceError, "export-set"):
            namespace.retarget(duplicate, "tests", "engine-a", generic)

    def test_selectors_and_name_expansion_are_bounded(self):
        name = namespace.exports("echo")[0]
        base = namespace.HEADER + section(11, b"\1" + export(name))
        for original, tenant, expected in (("examples", "engine-a", ()), ("examples", "engine-a", (name, name)),
                ("other", "engine-a", (name,)), ("examples", "Upper", (name,)),
                ("examples", "engine--a", (name,)), ("examples", "engine-a-", (name,)),
                ("examples", "a" * 65, (name,)), ("examples", "engine-a", (name + " ",)),
                ("examples", "engine-a", ("examples:",))):
            with self.subTest(original=original, tenant=tenant, expected=expected), self.assertRaises(EvidenceError):
                namespace.retarget(base, original, tenant, expected)
        long_name = "a:" + "x" * 254
        long_base = namespace.HEADER + section(11, b"\1" + export(long_name))
        with self.assertRaisesRegex(EvidenceError, "name-bound"):
            namespace.retarget(long_base, "a", "engine-a", (long_name,))


class EngineDescriptorTests(unittest.TestCase):
    def test_real_optimization_metadata_retargets_only_owned_ids_and_digests(self):
        original = contracts()
        saved = copy.deepcopy(original)
        changed = namespace.contracts(original, "optimization", "engine-a")
        descriptor = changed["contracts"][0]
        interface = descriptor["interfaces"][0]
        self.assertEqual(descriptor["id"], "engine-a:benchmark/workloads@0.1.0")
        self.assertEqual(descriptor["package_name"], "engine-a:benchmark")
        self.assertEqual(interface["id"], descriptor["id"])
        self.assertEqual(interface["functions"], original["contracts"][0]["interfaces"][0]["functions"])
        self.assertEqual(interface, signed({key: value for key, value in interface.items() if key != "digest"}))
        self.assertEqual(descriptor, signed({key: value for key, value in descriptor.items() if key != "digest"}))
        self.assertEqual(namespace.contracts(changed, "engine-a", "optimization"), original)
        self.assertEqual(original, saved)

    def test_unowned_strings_are_not_recursively_rewritten(self):
        original = contracts()
        interface = original["contracts"][0]["interfaces"][0]
        interface["documentation"] = "optimization:benchmark must remain literal documentation"
        interface["functions"][0]["attributes"]["import"] = "latent:context/api@0.1.0"
        interface["functions"][0]["attributes"]["literal"] = "optimization:benchmark"
        changed = namespace.contracts(original, "optimization", "engine-b")
        other = changed["contracts"][0]["interfaces"][0]
        self.assertEqual(other["documentation"], interface["documentation"])
        self.assertEqual(other["functions"], interface["functions"])
        self.assertEqual(namespace.contracts(changed, "engine-b", "engine-b"), changed)

    def test_crossed_owned_fields_and_nonempty_dependencies_reject(self):
        original = contracts()
        for key in ("id", "package_name", "interface", "dependencies"):
            changed = copy.deepcopy(original)
            descriptor = changed["contracts"][0]
            if key == "interface":
                descriptor["interfaces"][0]["id"] = "foreign:benchmark/workloads@0.1.0"
            elif key == "dependencies":
                descriptor["dependencies"] = ["foreign:other@0.1.0"]
            else:
                descriptor[key] = "foreign:benchmark"
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                namespace.contracts(changed, "optimization", "engine-a")


if __name__ == "__main__":
    unittest.main()
