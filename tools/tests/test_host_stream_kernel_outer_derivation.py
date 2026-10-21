"""Closed historical derivation; these controls do not execute Linux."""
import hashlib
import json
from pathlib import Path
import unittest

from tools import host_stream_kernel_outer_derivation as outer

ROOT = Path(__file__).resolve().parents[2]
OWNED = ROOT / "research/standard-outbound/linux-6.12-lineage"


class HostStreamKernelOuter(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(outer.FIXTURE.read_bytes())

    def original(self, name):
        return self.fixture["sections"][name]["text"]

    def test_nine_whole_preimages_and_seventeen_partial_definitions_are_exact(self):
        self.assertEqual(len(outer.SOURCE), 9)
        self.assertEqual(sum(row[0] for row in outer.SOURCE.values()), 715444)
        self.assertEqual(set(self.fixture["source"]), set(outer.SOURCE))
        self.assertEqual(len(outer.SECTIONS), 17)
        for name, (size, sha, blob) in outer.SOURCE.items():
            row = self.fixture["source"][name]
            self.assertEqual((row["bytes"], row["sha256"], row["gitBlob"]), (size, sha, blob))
        for name, row in self.fixture["sections"].items():
            self.assertEqual(hashlib.sha256(row["text"].encode()).hexdigest(), row["sha256"])
            self.assertEqual(outer.section(row["text"], name), row["text"])
            self.assertIs(row["allocationClosureProven"], False)

    def test_unknown_membership_whole_or_partial_preimages_refuse(self):
        with self.assertRaisesRegex(ValueError, "outer-source-membership"):
            outer.derive({})
        with self.assertRaisesRegex(ValueError, "outer-whole-preimage"):
            outer.derive({name: b"\0" * row[0] for name, row in outer.SOURCE.items()})
        for name in outer.SECTIONS:
            raw = self.original(name)
            for changed in (raw + raw, raw.replace("\n", "\r\n"), raw.replace("\n{\n", "\n{\n;\n")):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    outer.section(changed, name)
        with self.assertRaisesRegex(ValueError, "outer-private-name"):
            outer.derive_private(self.original("sock_alloc"), "__sock_create")
        with self.assertRaisesRegex(ValueError, "outer-observed-name"):
            outer.derive_observed(self.original("i_callback"), "i_callback")

    def test_original_outer_constructor_has_no_prepaid_origin(self):
        raw = self.original("sock_alloc_inode")
        self.assertIn("alloc_inode_sb(sb, sock_inode_cachep, GFP_KERNEL)", raw)
        self.assertNotIn("lsf_factory", raw)
        derived = outer.derive_private(raw, "sock_alloc_inode")
        self.assertNotIn("alloc_inode_sb(", derived)
        self.assertLess(derived.index("lsf_factory_allocate("), derived.index("inode_init_once("))
        self.assertLess(derived.index("inode_init_once("), derived.index("ei->lsf_factory = context"))
        self.assertLess(derived.index("ei->lsf_view_generation = ticket.generation"),
                        derived.index("init_waitqueue_head("))
        self.assertEqual(derived[derived.index("\tinit_waitqueue_head("):],
                         raw[raw.index("\tinit_waitqueue_head("):])

    def test_private_inode_keeps_actual_initializer_and_complete_error_cleanup(self):
        raw = self.original("alloc_inode")
        derived = outer.derive_private(raw, "alloc_inode")
        self.assertNotIn("alloc_inode_sb(", derived)
        self.assertNotIn("ops->alloc_inode(sb)", derived)
        self.assertIn("inode = lsf_outer_alloc_inode(sb, context)", derived)
        self.assertEqual(derived[derived.index("\tif (!inode)"):], raw[raw.index("\tif (!inode)"):])
        self.assertIn("inode_init_always(sb, inode)", derived)
        self.assertIn("i_callback(&inode->i_rcu)", derived)

    def test_private_socket_keeps_all_actual_metadata_and_no_global_fallback(self):
        raw = self.original("sock_alloc")
        derived = outer.derive_private(raw, "sock_alloc")
        self.assertNotIn("new_inode_pseudo(", derived)
        self.assertIn("lsf_prepaid_new_inode(sock_mnt->mnt_sb, context)", derived)
        self.assertEqual(derived[derived.index("\tif (!inode)"):], raw[raw.index("\tif (!inode)"):])
        for value in ("get_next_ino()", "current_fsuid()", "current_fsgid()", "&sockfs_inode_ops"):
            self.assertIn(value, derived)

    def test_ordinary_constructor_only_initializes_private_fields_to_nonorigin(self):
        raw = self.original("sock_alloc_inode")
        derived = outer.derive_observed(raw, "sock_alloc_inode")
        self.assertEqual(derived.replace(outer.INITIALIZE, ""), raw)
        self.assertIn("ei->lsf_factory = NULL", derived)
        self.assertEqual(derived.count("alloc_inode_sb("), 1)
        create = self.original("__sock_create")
        self.assertLess(create.index("security_socket_create("), create.index("sock_alloc();"))
        self.assertIn("security_socket_post_create(", create)

    def test_original_global_free_is_preserved_after_typed_birth_field_branch(self):
        raw = self.original("sock_free_inode")
        derived = outer.derive_observed(raw, "sock_free_inode")
        self.assertEqual(derived.replace(outer.FREE, ""), raw)
        self.assertLess(derived.index("lsf_outer_inode_return(ei)"), derived.index("kmem_cache_free("))
        owned = (OWNED / "outer-private.c").read_text()
        self.assertLess(owned.index("lsf_outer_superblock_supported(inode->i_sb)"),
                        owned.index("container_of(inode, struct socket_alloc"))
        self.assertNotIn("register_owner", owned)

    def test_deferred_ownership_is_before_unchanged_actual_rcu_callback(self):
        raw = self.original("destroy_inode")
        derived = outer.derive_observed(raw, "destroy_inode")
        self.assertEqual(derived.replace("\tlsf_outer_inode_queue(inode);\n", ""), raw)
        self.assertLess(derived.index("lsf_outer_inode_queue(inode)"), derived.index("call_rcu("))
        self.assertIn("inode->free_inode(inode)", self.original("i_callback"))
        owned = (OWNED / "outer-private.c").read_text()
        returned = owned[owned.index("static bool lsf_outer_inode_return("):owned.index("int lsf_outer_socket_begin(")]
        for field in ("struct lsf_factory_context *context", "struct lsf_prepaid_ticket ticket", "bool deferred"):
            self.assertLess(returned.index(field), returned.index("lsf_factory_return("))
        self.assertLess(returned.index("lsf_factory_return("), returned.index("lsf_factory_deferred(context, 0)"))
        self.assertIn("lsf_factory_poison(context)", returned)

    def test_security_preflight_refuses_unclosed_hooks_without_disabling_security(self):
        raw = (OWNED / "outer-security.c").read_text()
        self.assertIn("lsm_inode_cache || blob_sizes.lbs_inode", raw)
        for hook in ("inode_alloc_security", "inode_free_security", "inode_free_security_rcu",
                     "socket_create", "socket_post_create"):
            self.assertIn("lsm_for_each_hook(scall, " + hook + ") { return false; }", raw)
        self.assertNotIn("static_branch_disable", raw)
        self.assertNotIn("= NULL", raw)
        self.assertIn("call_int_hook(inode_alloc_security", self.original("security_inode_alloc"))
        self.assertIn("call_rcu(", self.original("security_inode_free"))
        header = (OWNED / "outer-hooks.h").read_text()
        self.assertIn("static inline bool lsf_outer_security_supported(void) { return false; }", header)

    def test_outer_prefix_retains_real_security_order_and_is_not_a_protocol_success(self):
        raw = (OWNED / "outer-private.c").read_text()
        begin = raw[raw.index("int lsf_outer_socket_begin("):raw.index("int lsf_outer_socket_post_create(")]
        self.assertLess(begin.index("lsf_outer_security_supported()"), begin.index("security_socket_create("))
        self.assertLess(begin.index("security_socket_create("), begin.index("lsf_outer_sock_alloc(context)"))
        self.assertIn("(*result)->type = type", begin)
        self.assertNotIn("pf->create(", begin)
        post = raw[raw.index("int lsf_outer_socket_post_create("):]
        self.assertLess(post.index("!socket->sk || !socket->ops"), post.index("security_socket_post_create("))
        self.assertLess(post.index("allocation->lsf_factory != context"), post.index("security_socket_post_create("))
        self.assertNotIn("sock_create_kern(", raw)

    def test_unknown_origin_poison_and_all_production_gates_stay_closed(self):
        raw = (OWNED / "factory.c").read_text()
        poison = raw[raw.index("void lsf_factory_poison("):raw.index("static ssize_t lsf_factory_write(")]
        self.assertLess(poison.index("lsf_factory_context_current(context)"), poison.index("context->key"))
        self.assertIn("WRITE_ONCE(factory.uncertain, 1)", poison)
        self.assertNotIn("factory.uncertain =", raw)
        self.assertEqual(raw.count("WRITE_ONCE(factory.uncertain, 1)"), 6)
        head = raw[raw.index("int lsf_factory_audit_head_current("):raw.index("int lsf_factory_blob_queue(")]
        self.assertIn("if (result == 1 && (!bytes || bytes > LSF_TCP_BYTES ||", head)
        self.assertIn("bytes > factory.pool.records[copy->ticket.slot].bytes)", head)
        self.assertLess(head.index("lsf_factory_blob_lookup_locked(address, LSF_PREPAID_AUDIT_HEAD, copy)"),
                        head.index("factory.pool.contexts[copy->context->key.slot].poisoned = 1"))
        self.assertLess(head.index("WRITE_ONCE(factory.uncertain, 1)"), head.index("result = -1;"))
        gate = (OWNED / "factory-private.h").read_text()
        self.assertIn("lsf_factory_selected_consumer(void)\n{\n    return NULL;", gate)
        for field in ("kernelBuilt", "actualOuterExecuted", "productionInstallation"):
            self.assertIs(self.fixture[field], False)


if __name__ == "__main__":
    unittest.main()
