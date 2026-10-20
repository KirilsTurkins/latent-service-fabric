"""Authenticated socket initialization, immutable cookie semantics and handoff."""
import difflib
import hashlib
import json
from pathlib import Path
import unittest
from tools import host_stream_kernel_handoff_derivation as handoff
from tools import host_stream_kernel_birth_derivation as birth
from tools import host_stream_kernel_derivation as free


class HostStreamKernelHandoffDerivation(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent /
            "fixtures/host_stream_kernel_cookie_functions.json").read_bytes())
        self.constructors = json.loads((Path(__file__).parent /
            "fixtures/host_stream_kernel_birth_functions.json").read_bytes())

    def test_whole_header_and_cookie_chain_preimages_have_no_implicit_acquisition(self):
        self.assertEqual(self.fixture["upstreamCommit"], free.COMMIT)
        self.assertEqual(set(self.fixture["functions"]), set(handoff.FUNCTIONS))
        self.assertEqual(len(handoff.SOURCE), 7)
        self.assertEqual(set(handoff.SOURCE), set(free.SOURCE) | set(handoff.ADDITIONAL))
        for name, row in self.fixture["functions"].items():
            self.assertEqual((row["source"], row["prefix"], row["sha256"]), handoff.FUNCTIONS[name])
            self.assertEqual(hashlib.sha256(row["text"].encode()).hexdigest(), row["sha256"])
            self.assertEqual(handoff.function(row["text"], name), row["text"])

    def test_outer_constructor_changes_are_insertions_preserving_every_upstream_statement(self):
        for name in ("sk_alloc", "sk_clone_lock"):
            original = self.fixture["functions"][name]["text"]
            changed = handoff.derive_function(original, name)
            opcodes = difflib.SequenceMatcher(a=original.splitlines(keepends=True),
                b=changed.splitlines(keepends=True), autojunk=False).get_opcodes()
            self.assertTrue(all(tag in ("equal", "insert") for tag, *_ in opcodes), (name, opcodes))
            self.assertEqual(changed.count("lsf_stream_socket_initialized"), 1)
            self.assertNotIn("atomic64_set", changed)

    def test_fresh_handoff_follows_initialization_and_clone_handoff_follows_failure_paths(self):
        fresh = handoff.derive_function(self.fixture["functions"]["sk_alloc"]["text"], "sk_alloc")
        self.assertLess(fresh.index("sock_lock_init"), fresh.index("lsf_stream_socket_initialized"))
        self.assertLess(fresh.index("sk_tx_queue_clear"), fresh.index("lsf_stream_socket_initialized"))
        self.assertLess(fresh.index("lsf_stream_socket_initialized"), fresh.index("return sk;"))
        clone = handoff.derive_function(self.fixture["functions"]["sk_clone_lock"]["text"], "sk_clone_lock")
        self.assertLess(clone.index("sock_copy("), clone.index("sk_init_common("))
        self.assertLess(clone.index("sk_init_common("), clone.index("lsf_stream_socket_initialized"))
        self.assertLess(clone.index("if (bpf_sk_storage_clone"), clone.index("lsf_stream_socket_initialized"))
        self.assertLess(clone.index("lsf_stream_socket_initialized"), clone.index("smp_wmb();"))
        self.assertLess(clone.index("smp_wmb();"), clone.index("refcount_set(&newsk->sk_refcnt, 2);"))
        self.assertIn("sk_free_unlock_clone(newsk);\n\t\tnewsk = NULL;\n\t\tgoto out;", clone)

    def test_constructor_retains_reserved_address_instead_of_preinitialization_cookie_commit(self):
        original = self.constructors["functions"]["sk_prot_alloc"]["text"]
        old = birth.derive_function(original, "sk_prot_alloc")
        current = handoff.derive_socket_constructor(original)
        self.assertIn("lsf_stream_constructor_observed(&lsf_birth, 0, sk, 0)", old)
        self.assertNotIn("lsf_stream_constructor_observed", current)
        self.assertIn("lsf_stream_socket_reserved(&lsf_birth, sk)", current)
        self.assertNotIn("sock_gen_cookie", current)
        self.assertNotIn("sk->sk_cookie", current)
        self.assertIn("out_free:\n\tlsf_stream_constructor_uncertain(&lsf_birth);", current)

    def test_original_cookie_copy_and_generation_semantics_are_not_reset_or_replaced(self):
        common = self.fixture["functions"]["sk_init_common"]["text"]
        copy = self.fixture["functions"]["sock_copy"]["text"]
        self.assertNotIn("sk_cookie", common)
        self.assertIn("memcpy(nsk, osk, offsetof(struct sock, sk_dontcopy_begin))", copy)
        self.assertIn("preempt_disable();", self.fixture["functions"]["sock_gen_cookie"]["text"])
        self.assertIn("preempt_enable();", self.fixture["functions"]["sock_gen_cookie"]["text"])
        generator = self.fixture["functions"]["__sock_gen_cookie"]["text"]
        self.assertIn("atomic64_cmpxchg(&sk->sk_cookie, res, new)", generator)
        self.assertEqual(generator.count("atomic64_read(&sk->sk_cookie)"), 2)
        self.assertIn("gen_cookie_next(&sock_cookie)", generator)
        for name in ("sk_init_common", "sock_copy", "sock_gen_cookie", "__sock_gen_cookie", "gen_cookie_next"):
            with self.assertRaises(ValueError):
                handoff.derive_function(self.fixture["functions"][name]["text"], name)

    def test_unknown_changed_duplicate_and_partial_preimages_refuse(self):
        for name, row in self.fixture["functions"].items():
            for changed in (row["text"].replace("\n{\n", "\n{\n\t;\n"),
                            row["text"].replace("\n", "\r\n"), row["text"] * 2):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    handoff.function(changed, name)
            with self.assertRaises(ValueError):
                handoff.function(row["text"] * 2, name)
        with self.assertRaisesRegex(ValueError, "unknown-handoff-function"):
            handoff.function("", "unknown")
        with self.assertRaisesRegex(ValueError, "handoff-source-membership"):
            handoff.derive({})
        inputs = {name: b"\0" * row[0] for name, row in handoff.SOURCE.items()}
        with self.assertRaisesRegex(ValueError, "handoff-whole-source-preimage"):
            handoff.derive(inputs)

    def test_private_handoff_copies_before_cookie_and_revalidates_after_with_no_new_table(self):
        hooks = (free.OWNED / "handoff-hooks.c").read_text()
        core = (free.OWNED / "handoff.h").read_text()
        before = hooks.index("lsf_socket_capture_handoff")
        unlock = hooks.index("spin_unlock_irqrestore", before)
        cookie = hooks.index("sock_gen_cookie(sk)")
        after = hooks.index("lsf_socket_commit_handoff")
        self.assertLess(before, unlock)
        self.assertLess(unlock, cookie)
        self.assertLess(cookie, after)
        self.assertNotIn("atomic64_set", hooks)
        self.assertNotIn("static struct lsf_lineage ", hooks + core)
        self.assertNotIn("live_bytes -=", hooks + core)
        self.assertIn("token->owner_generation != bundle->admission.key.generation", core)
        self.assertIn("handoff->token.owner_generation != handoff->admission.key.generation", core)
        self.assertIn("lsf_allocation_for(state, token) != allocation", core)
        for forbidden in ("malloc(", "kmalloc(", "EXPORT_SYMBOL", "ioctl(", "bpf_map"):
            self.assertNotIn(forbidden, hooks + core)

    def test_factory_gate_normal_provider_and_old_mechanisms_remain_closed(self):
        source = (free.OWNED / "constructor-hooks.c").read_text()
        prepare = source[source.index("int lsf_stream_constructor_prepare("):source.index("\n}\n")]
        self.assertIn("return 0;", prepare)
        self.assertNotIn("return 1;", prepare)
        self.assertIn("Err(error(StreamErrorCode::Unsupported))",
            (free.ROOT / "crates/latent-streams/src/kernel.rs").read_text())
        self.assertIn("const ACCOUNTING_QUALIFIED: bool = false;",
            (free.ROOT / "crates/latent-streams/src/tls.rs").read_text())
        self.assertEqual(len(free.FUNCTIONS), 5)
        self.assertEqual(len(birth.FUNCTIONS), 3)
        reference = (free.OWNED / "handoff-reference.c").read_text()
        self.assertLess(reference.index("#undef NDEBUG"), reference.index("#include <assert.h>"))
        self.assertIn("linux-executed=false; trusted-factory=false; final-free-certified=false", reference)


if __name__ == "__main__":
    unittest.main()
