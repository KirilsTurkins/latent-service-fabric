"""Authenticated source hooks are prerequisites, never a kernel certificate."""
import difflib
import hashlib
import json
from pathlib import Path
import unittest
from tools import host_stream_kernel_derivation as recipe


class HostStreamKernelDerivation(unittest.TestCase):
    def setUp(self):
        self.fixtures = json.loads((Path(__file__).parent / "fixtures/host_stream_kernel_lineage_functions.json").read_bytes())

    def test_original_five_functions_bind_three_authenticated_upstream_files(self):
        self.assertEqual(self.fixtures["upstreamCommit"], recipe.COMMIT)
        self.assertEqual(self.fixtures["license"], "GPL-2.0-only")
        self.assertEqual(set(self.fixtures["functions"]), set(recipe.FUNCTIONS))
        self.assertEqual(len(recipe.SOURCE), 3)
        for symbol, row in self.fixtures["functions"].items():
            self.assertEqual((row["source"], row["sha256"]), recipe.FUNCTIONS[symbol])
            self.assertEqual(hashlib.sha256(row["text"].encode()).hexdigest(), row["sha256"])
            self.assertEqual(recipe.function(row["text"], symbol), row["text"])

    def test_all_upstream_function_statements_remain_byte_exact_and_ordered(self):
        for symbol, row in self.fixtures["functions"].items():
            before = row["text"].splitlines(keepends=True)
            after = recipe.derive_function(row["text"], symbol).splitlines(keepends=True)
            opcodes = difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes()
            self.assertTrue(all(tag in ("equal", "insert") for tag, *_ in opcodes), (symbol, opcodes))
            self.assertTrue(any(tag == "insert" for tag, *_ in opcodes))

    def test_socket_and_timewait_copy_identity_before_free_and_observe_after(self):
        for name in ("sk_prot_free", "inet_twsk_free"):
            original = self.fixtures["functions"][name]["text"]
            self.assertNotIn("lsf_stream_before_free", original)
            self.assertNotIn("lsf_stream_after_free", original)
            changed = recipe.derive_function(original, name)
            captured = changed.index("lsf_stream_before_free")
            cookie = changed.index("atomic64_read")
            free = changed.index("\n\t\tkmem_cache_free" if name == "sk_prot_free" else "\n\tkmem_cache_free")
            observed = changed.index("lsf_stream_after_free")
            self.assertLess(captured, cookie)
            self.assertLess(cookie, free)
            self.assertLess(free, observed)
            self.assertLess(observed, changed.index("module_put(owner)"))
            suffix = changed[observed:]
            self.assertNotIn("sk->", suffix)
            self.assertNotIn("tw->", suffix)

    def test_skb_physical_header_clone_and_data_free_are_distinct(self):
        header = recipe.derive_function(self.fixtures["functions"]["kfree_skbmem"]["text"], "kfree_skbmem")
        self.assertEqual(header.count("lsf_stream_before_free"), 2)
        self.assertEqual(header.count("lsf_stream_after_free"), 2)
        self.assertIn("LSF_SKB_HEADER, skb, 0", header)
        self.assertIn("LSF_SKB_CLONE, fclones, 0", header)
        self.assertLess(header.index("if (!refcount_dec_and_test"), header.index("LSF_SKB_CLONE"))
        head = recipe.derive_function(self.fixtures["functions"]["skb_kfree_head"]["text"], "skb_kfree_head")
        self.assertLess(head.index("lsf_stream_before_free"), head.index("kmem_cache_free"))
        self.assertLess(head.index("kfree(head)"), head.index("lsf_stream_after_free"))
        fragment = recipe.derive_function(self.fixtures["functions"]["skb_free_head"]["text"], "skb_free_head")
        self.assertLess(fragment.index("lsf_stream_unproved_fragment"), fragment.index("skb_pp_recycle"))
        self.assertNotIn("lsf_stream_after_free", fragment)

    def test_changed_function_repeated_anchor_unknown_function_and_hunk_refuse(self):
        for name, row in self.fixtures["functions"].items():
            for changed in (row["text"] + "\n", row["text"].replace("\n", "\r\n"), row["text"] * 2):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    recipe.derive_function(changed, name)
        with self.assertRaisesRegex(ValueError, "unknown-function"):
            recipe.function("void unrelated(void) {}", "unknown")
        with self.assertRaisesRegex(ValueError, "function-occurrence"):
            recipe.function(self.fixtures["functions"]["sk_prot_free"]["text"] * 2, "sk_prot_free")
        for raw in ("", "same same"):
            with self.assertRaisesRegex(ValueError, "hunk-preimage"):
                recipe.replace_once(raw, "same", "new")

    def test_whole_preimages_and_exact_source_membership_are_mandatory(self):
        inputs = {name: b"\0" * row[0] for name, row in recipe.SOURCE.items()}
        for changed in ({}, {**inputs, "other.c": b""}, inputs):
            with self.assertRaises(ValueError):
                recipe.derive(changed)
        # Authenticated function fragments cannot substitute for their full files.
        fragments = {name: b"" for name in recipe.SOURCE}
        for row in self.fixtures["functions"].values():
            fragments[row["source"]] += row["text"].encode()
        with self.assertRaisesRegex(ValueError, "whole-source-preimage"):
            recipe.derive(fragments)

    def test_bounded_private_state_has_no_public_release_or_allocator(self):
        core = (recipe.OWNED / "lineage.h").read_text()
        hooks = (recipe.OWNED / "kernel-hooks.c").read_text()
        self.assertIn("#define LSF_OWNER_SLOTS 64u", core)
        self.assertIn("#define LSF_ALLOCATION_SLOTS 256u", core)
        self.assertIn("#define LSF_TCP_BYTES 98304u", core)
        self.assertIn("#define LSF_DNS_BYTES 65536u", core)
        for forbidden in ("malloc(", "calloc(", "realloc(", "kmalloc(", "EXPORT_SYMBOL", "ioctl(", "bpf_map"):
            self.assertNotIn(forbidden, core + hooks)
        self.assertIn("static struct lsf_lineage lsf_stream_state", hooks)
        self.assertEqual(hooks.count("spin_lock_irqsave"), 3)
        self.assertEqual(hooks.count("spin_unlock_irqrestore"), 3)
        self.assertNotIn("sk->", hooks)
        self.assertNotIn("skb->", hooks)
        self.assertNotIn("tw->", hooks)
        for name in ("reference.c", "hook-reference.c"):
            source = (recipe.OWNED / name).read_text()
            self.assertLess(source.index("#undef NDEBUG"), source.index("#include <assert.h>"))

    def test_normal_provider_gate_and_accounting_flag_stay_closed(self):
        kernel = (recipe.ROOT / "crates/latent-streams/src/kernel.rs").read_text()
        tls = (recipe.ROOT / "crates/latent-streams/src/tls.rs").read_text()
        self.assertIn("Err(error(StreamErrorCode::Unsupported))", kernel)
        self.assertNotIn("Ok(", kernel)
        self.assertIn("const ACCOUNTING_QUALIFIED: bool = false;", tls)
        self.assertNotIn("kernel-hooks", kernel)


if __name__ == "__main__":
    unittest.main()
