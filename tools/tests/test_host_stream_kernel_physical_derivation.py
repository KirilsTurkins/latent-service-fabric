"""Partial source graph and conservative backing-extent plan boundaries."""
import hashlib
import json
from pathlib import Path
import unittest
from tools import host_stream_kernel_derivation as free
from tools import host_stream_kernel_handoff_derivation as handoff
from tools import host_stream_kernel_physical_derivation as physical


class HostStreamKernelPhysicalDerivation(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent /
            "fixtures/host_stream_kernel_allocation_graph.json").read_bytes())

    def test_whole_graph_preimages_bind_historical_commit_not_running_kernel(self):
        self.assertEqual(self.fixture["upstreamCommit"], free.COMMIT)
        self.assertEqual(len(physical.ADDITIONAL), 18)
        self.assertEqual(len(physical.SOURCE), 25)
        self.assertEqual(set(physical.SOURCE), set(handoff.SOURCE) | set(physical.ADDITIONAL))
        self.assertEqual(sum(row[0] for row in physical.ADDITIONAL.values()), 2011850)
        for name, row in self.fixture["additionalSource"].items():
            self.assertEqual((row["bytes"], row["sha256"], row["gitBlob"]), physical.ADDITIONAL[name])
            self.assertIn(free.COMMIT, row["url"])
        for field in ("completeGraph", "runningKernelAuthenticated", "trustedFactoryInstalled",
                      "physicalAllocationQualified", "beforeSocketLookupClassified", "finalFreeCertified"):
            self.assertIs(self.fixture[field], False)

    def test_every_frozen_function_is_exact_and_preserves_explicit_obligation(self):
        self.assertEqual(len(physical.FUNCTIONS), 37)
        self.assertEqual(set(physical.FUNCTIONS), set(self.fixture["functions"]))
        for name, row in self.fixture["functions"].items():
            self.assertEqual((row["source"], row["prefix"], row["sha256"], row["obligation"]),
                physical.FUNCTIONS[name])
            self.assertEqual(hashlib.sha256(row["text"].encode()).hexdigest(), row["sha256"])
            self.assertEqual(physical.function(row["text"], name), row["text"])
            self.assertIs(row["physicalClosureProven"], False)

    def test_changed_partial_duplicate_and_unknown_function_sources_refuse(self):
        for name, row in self.fixture["functions"].items():
            for value in (row["text"] * 2, row["text"].replace("\n", "\r\n"),
                          row["text"].replace("\n{\n", "\n{\n\t;\n")):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    physical.function(value, name)
        with self.assertRaisesRegex(ValueError, "unknown-physical-function"):
            physical.function("", "unknown")

    def test_whole_source_membership_and_wrong_preimage_fail_before_derivation(self):
        with self.assertRaisesRegex(ValueError, "physical-source-membership"):
            physical.derive({})
        inputs = {name: b"\0" * row[0] for name, row in physical.SOURCE.items()}
        with self.assertRaisesRegex(ValueError, "physical-whole-source-preimage"):
            physical.derive(inputs)

    def test_all_five_original_copied_tokens_are_retained_after_object_return(self):
        fixture = json.loads((Path(__file__).parent /
            "fixtures/host_stream_kernel_lineage_functions.json").read_bytes())
        groups = {}
        for name, row in fixture["functions"].items():
            groups.setdefault(row["source"], []).append(free.derive_function(row["text"], name))
        for path, values in groups.items():
            old = "\n".join(values)
            count = 3 if path == "net/core/skbuff.c" else 1
            current = physical.retain_slot_returns(old, count)
            self.assertEqual(current.count("lsf_stream_allocator_returned(lsf_free);"), count)
            self.assertNotIn("lsf_stream_after_free(", current)
            self.assertEqual(current.replace("lsf_stream_allocator_returned", "lsf_stream_after_free"), old)
            self.assertEqual(current.count("lsf_stream_before_free("), count)
            if path == "net/core/skbuff.c":
                self.assertIn("lsf_stream_unproved_fragment(head)", current)
        for value, count in (("", 1), ("lsf_stream_after_free(lsf_free);" * 2, 1),
                             ("lsf_stream_after_free(lsf_free);", 0)):
            with self.assertRaisesRegex(ValueError, "physical-slot-return-occurrence"):
                physical.retain_slot_returns(value, count)

    def test_actual_source_exposes_before_lookup_bulk_cache_and_shared_backing(self):
        functions = self.fixture["functions"]
        self.assertIn("kmem_cache_alloc_bulk", functions["napi_skb_cache_get"]["text"])
        self.assertIn("NAPI_SKB_CACHE_BULK", functions["napi_skb_cache_get"]["text"])
        self.assertLess(functions["__netdev_alloc_skb"]["text"].index("page_frag_alloc("),
            functions["__netdev_alloc_skb"]["text"].index("__build_skb("))
        self.assertIn("page_frag_alloc_1k", functions["napi_alloc_skb"]["text"])
        self.assertIn("nc->skb_cache[nc->skb_count++] = skb;", functions["napi_skb_cache_put"]["text"])
        self.assertIn("return true;", functions["page_pool_recycle_in_cache"]["text"])
        self.assertIn("add_partial", functions["__slab_free"]["text"])
        self.assertIn("call_rcu", functions["free_slab"]["text"])

    def test_clones_expansion_routes_and_deferred_lifetimes_are_not_extra_wire_bytes(self):
        functions = self.fixture["functions"]
        clone = functions["skb_clone"]["text"]
        self.assertIn("n = &fclones->skb2;", clone)
        self.assertIn("refcount_set(&fclones->fclone_ref, 2)", clone)
        expand = functions["pskb_expand_head"]["text"]
        self.assertLess(expand.index("kmalloc_reserve"), expand.index("skb_free_head"))
        self.assertIn("skb_cloned(skb)", expand)
        self.assertIn("kmem_cache_alloc", functions["dst_alloc"]["text"])
        self.assertIn("kzalloc", functions["neigh_alloc"]["text"])
        self.assertIn("dst_destroy(dst)", functions["dst_destroy_rcu"]["text"])

    def test_private_planner_does_not_add_a_table_ledger_refund_or_public_authentication(self):
        core = (free.OWNED / "physical-plan.h").read_text()
        hooks = (free.OWNED / "physical-hooks.c").read_text()
        self.assertIn("lsf_bundle_prepare(state, admission, parent, constructor,", core)
        self.assertIn("plan.costs, plan.count, bundle)", core)
        self.assertIn("LSF_PHYSICAL_HELD = LSF_FREE_CAPTURED + 1", core)
        self.assertIn("allocation->phase = LSF_PHYSICAL_HELD", core)
        self.assertIn("LSF_PLAN_PRELOOKUP_RX", core)
        self.assertIn("LSF_PLAN_SHARED_CACHE", core)
        for forbidden in ("lsf_post_free(", "live_bytes -=", "static struct lsf_lineage ",
                          "malloc(", "kmalloc(", "EXPORT_SYMBOL", "ioctl(", "bpf_map"):
            self.assertNotIn(forbidden, core + hooks)
        self.assertLess(hooks.index("spin_lock_irqsave"), hooks.index("lsf_physical_slot_return"))
        self.assertLess(hooks.index("lsf_physical_slot_return"), hooks.index("spin_unlock_irqrestore"))

    def test_actual_gate_has_no_geometry_factory_or_production_promotion(self):
        source = (free.OWNED / "constructor-hooks.c").read_text()
        prepare = source[source.index("int lsf_stream_constructor_prepare("):source.index("\n}\n")]
        self.assertIn("return 0;", prepare)
        self.assertNotIn("return 1;", prepare)
        self.assertNotIn("lsf_physical_prepare(", prepare)
        self.assertIn("Err(error(StreamErrorCode::Unsupported))",
            (free.ROOT / "crates/latent-streams/src/kernel.rs").read_text())
        self.assertIn("const ACCOUNTING_QUALIFIED: bool = false;",
            (free.ROOT / "crates/latent-streams/src/tls.rs").read_text())


if __name__ == "__main__":
    unittest.main()
