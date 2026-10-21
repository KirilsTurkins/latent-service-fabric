"""Fail-unknown constructor source and private credit-carrier controls."""
import hashlib
import json
from pathlib import Path
import unittest
from tools import host_stream_kernel_birth_derivation as birth
from tools import host_stream_kernel_derivation as free


class HostStreamKernelBirthDerivation(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent /
            "fixtures/host_stream_kernel_birth_functions.json").read_bytes())

    def test_three_whole_source_and_constructor_preimages_are_exact(self):
        self.assertEqual(self.fixture["upstreamCommit"], free.COMMIT)
        self.assertEqual(self.fixture["license"], "GPL-2.0-only")
        self.assertEqual(set(self.fixture["functions"]), set(birth.FUNCTIONS))
        for name, row in self.fixture["functions"].items():
            self.assertEqual((row["source"], row["prefix"], row["sha256"]), birth.FUNCTIONS[name])
            self.assertEqual(hashlib.sha256(row["text"].encode()).hexdigest(), row["sha256"])
            self.assertEqual(birth.function(row["text"], name), row["text"])

    def test_socket_admission_precedes_both_allocators_and_preserves_failure_cleanup(self):
        source = birth.derive_function(self.fixture["functions"]["sk_prot_alloc"]["text"], "sk_prot_alloc")
        gate = source.index("lsf_stream_constructor_prepare")
        self.assertLess(gate, source.index("kmem_cache_alloc("))
        self.assertLess(gate, source.index("kmalloc("))
        self.assertIn("priority, family, 0, &lsf_birth", source)
        self.assertIn("out_free_sec:\n\tsecurity_sk_free(sk);\nout_free:\n"
            "\tlsf_stream_constructor_uncertain(&lsf_birth);", source)
        self.assertIn("if (!try_module_get(prot->owner))\n\t\t\tgoto out_free_sec;", source)
        self.assertIn("if (security_sk_alloc(sk, family, priority))\n\t\t\tgoto out_free;", source)
        self.assertNotIn("atomic64_set", source)
        self.assertIn("lsf_stream_constructor_observed(&lsf_birth, 0, sk, 0)", source)

    def test_timewait_quota_first_and_original_cookie_before_observation(self):
        source = birth.derive_function(self.fixture["functions"]["inet_twsk_alloc"]["text"], "inet_twsk_alloc")
        gate = source.index("lsf_stream_constructor_prepare")
        self.assertLess(source.index("READ_ONCE(dr->sysctl_max_tw_buckets)"), gate)
        self.assertLess(gate, source.index("tw = kmem_cache_alloc"))
        self.assertLess(source.index("atomic64_set(&tw->tw_cookie"), source.index("lsf_stream_constructor_observed"))
        self.assertIn("LSF_CONSTRUCT_TIMEWAIT, sk", source)
        self.assertLess(source.index("__module_get"), source.index("lsf_stream_constructor_observed"))

    def test_skb_both_reservations_precede_header_and_data_including_napi(self):
        source = birth.derive_function(self.fixture["functions"]["__alloc_skb"]["text"], "__alloc_skb")
        gate = source.index("lsf_stream_constructor_prepare")
        for allocator in ("napi_skb_cache_get", "kmem_cache_alloc_node", "kmalloc_reserve"):
            self.assertLess(gate, source.index(allocator))
        self.assertIn("gfp_mask, flags, node, &lsf_birth", source)
        self.assertEqual(source.count("lsf_stream_constructor_prepare"), 1)
        self.assertIn("lsf_stream_constructor_observed(&lsf_birth, 0,", source)
        self.assertIn("lsf_stream_constructor_observed(&lsf_birth, 1, data, 0)", source)
        self.assertIn("nodata:\n\tlsf_stream_constructor_uncertain(&lsf_birth);\n"
            "\tkmem_cache_free(cache, skb);\n\treturn NULL;", source)
        self.assertIn("container_of(skb,\n\t\tstruct sk_buff_fclones, skb1)", source)

    def test_unknown_changed_repeated_or_fragment_source_refuses(self):
        for name, row in self.fixture["functions"].items():
            for changed in (row["text"] + "\n", row["text"].replace("\n", "\r\n"), row["text"] * 2):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    birth.derive_function(changed, name)
            with self.assertRaisesRegex(ValueError, "constructor-occurrence"):
                birth.function(row["text"] * 2, name)
        with self.assertRaisesRegex(ValueError, "unknown-constructor"):
            birth.function("", "unknown")
        fragments = {name: b"" for name in free.SOURCE}
        for row in self.fixture["functions"].values():
            fragments[row["source"]] += row["text"].encode()
        with self.assertRaisesRegex(ValueError, "whole-source-preimage"):
            birth.derive(fragments)
        with self.assertRaises(ValueError):
            birth.derive({})

    def test_actual_kernel_seam_refuses_unknown_and_shares_original_owner_state(self):
        source = (free.OWNED / "constructor-hooks.c").read_text()
        start = source.index("int lsf_stream_constructor_prepare(")
        stop = source.index("\n}\n", start)
        prepare = source[start:stop]
        self.assertIn("return 0;", prepare)
        self.assertNotIn("return 1;", prepare)
        self.assertNotIn("lsf_owner_admit(", source)
        self.assertNotIn("struct lsf_lineage ", source)
        self.assertIn("lsf_bundle_commit(&lsf_stream_state", source)
        self.assertIn("lsf_bundle_uncertain(&lsf_stream_state", source)
        self.assertEqual(source.count("spin_lock_irqsave"), 2)
        self.assertEqual(source.count("spin_unlock_irqrestore"), 2)
        for forbidden in ("EXPORT_SYMBOL", "ioctl(", "bpf_map", "malloc(", "kmalloc("):
            self.assertNotIn(forbidden, source)

    def test_carrier_checks_full_scope_shapes_credits_slots_and_affine_commit(self):
        source = (free.OWNED / "admission.h").read_text()
        self.assertIn("i < 8", source)
        self.assertIn("owner->scope, admission.scope", source)
        self.assertIn("LSF_BUNDLE_ALLOCATIONS 2u", source)
        self.assertIn("costs[1].kind == LSF_SKB_HEAD", source)
        self.assertIn("owner->live_bytes > owner->maximum_bytes - total", source)
        self.assertLess(source.index("if (empty < count)"), source.index("lsf_birth_prepare("))
        self.assertIn("index != bundle->committed", source)
        self.assertIn("bundle->count > LSF_BUNDLE_ALLOCATIONS", source)
        self.assertIn("bundle->tokens[index].owner != bundle->admission.key.slot", source)
        self.assertIn("bundle->tokens[index].owner_generation != bundle->admission.key.generation", source)
        self.assertNotIn("live_bytes -=", source)
        self.assertNotIn("lsf_post_free", source)

    def test_existing_free_hook_source_and_normal_provider_gates_are_unmodified(self):
        self.assertEqual(len(free.FUNCTIONS), 5)
        kernel = (free.ROOT / "crates/latent-streams/src/kernel.rs").read_text()
        tls = (free.ROOT / "crates/latent-streams/src/tls.rs").read_text()
        self.assertIn("Err(error(StreamErrorCode::Unsupported))", kernel)
        self.assertNotIn("Ok(", kernel)
        self.assertIn("const ACCOUNTING_QUALIFIED: bool = false;", tls)
        for name in ("admission-reference.c", "constructor-reference.c"):
            source = (free.OWNED / name).read_text()
            self.assertLess(source.index("#undef NDEBUG"), source.index("#include <assert.h>"))
            self.assertIn("linux-executed=false; final-free-certified=false", source)


if __name__ == "__main__":
    unittest.main()
