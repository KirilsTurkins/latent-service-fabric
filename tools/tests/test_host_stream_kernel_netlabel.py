"""Closed maintained Netlabel source and original owner lifetime boundaries."""
import hashlib
import unittest

from tools import host_stream_kernel_netlabel as netlabel
from tools import host_stream_kernel_protocol as protocol
from tools import host_stream_kernel_maintained as maintained


class KernelNetlabel(unittest.TestCase):
    def setUp(self):
        self.fixture = netlabel.fixture()

    def original(self, name):
        return self.fixture['sections'][name]['text']

    def owned(self, name):
        return (protocol.OWNED / name).read_text()

    def test_thirteen_whole_preimages_and_sixteen_definitions_bind_actual_maintained_archive(self):
        self.assertEqual(len(self.fixture['source']), 13)
        self.assertEqual(sum(row['bytes'] for row in self.fixture['source'].values()), 863534)
        self.assertEqual(self.fixture['upstreamCommit'], maintained.COMMIT)
        self.assertEqual(len(self.fixture['sections']), 16)
        for name, row in self.fixture['sections'].items():
            self.assertEqual(hashlib.sha256(row['text'].encode()).hexdigest(), row['sha256'])
            self.assertEqual(netlabel.section(row['text'], name), row['text'])
            self.assertIs(row['allocationClosureProven'], False)
        self.assertFalse(self.fixture['source']['include/net/netlabel.h']['independentlyGitCorroborated'])

    def test_duplicate_unknown_changed_or_crlf_definition_and_whole_membership_refuse(self):
        with self.assertRaises(ValueError):
            netlabel.authenticate({})
        with self.assertRaises(ValueError):
            netlabel.section('', 'unrecognized')
        for name in netlabel.NAMES:
            raw = self.original(name)
            for changed in (raw + raw, raw.replace('\n', '\r\n'), raw.replace('\n{\n', '\n{\n;\n')):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    netlabel.section(changed, name)

    def test_actual_old_label_producer_uses_generic_allocator_new_private_uses_existing_birth(self):
        raw = self.original('selinux_netlbl_sock_genattr')
        self.assertIn('netlbl_secattr_alloc(GFP_ATOMIC)', raw)
        derived = netlabel.private(raw, 'selinux_netlbl_sock_genattr')
        self.assertNotIn('netlbl_secattr_alloc(', derived)
        self.assertIn('lsf_factory_child_allocate(*source, sizeof(*secattr), LSF_PREPAID_LABEL)', derived)
        self.assertIn('netlbl_secattr_free(secattr)', derived)
        self.assertEqual(raw[raw.index('\tif (rc != 0)'):], derived[derived.index('\tif (rc != 0)'):])

    def test_normal_dispatch_is_closed_owned_branch_and_original_body_remainder_is_identical(self):
        for name in ('selinux_netlbl_sock_genattr', 'netlbl_sock_setattr', 'netlbl_conn_setattr'):
            raw = self.original(name)
            derived = netlabel.observed(raw, name)
            begin = derived.index('#ifdef CONFIG_LSF_STREAM_FACTORY\n')
            end = derived.index('#endif\n', begin) + len('#endif\n')
            self.assertEqual(derived[:begin] + derived[end:], raw)
            self.assertLess(derived.index('if (owned < 0)'), derived.index('if (owned)'))
        source = self.owned('netlabel-private.c')
        self.assertIn('if (!context && !ticket.slot && !ticket.generation)', source)
        self.assertIn('lsf_factory_protocol_parent(sk, context, ticket, source)', source)
        self.assertNotIn('current->', source)

    def test_sid_policy_lookup_rcu_and_label_semantics_are_preserved_without_strdup_fallback(self):
        raw = self.original('security_netlbl_sid_to_secattr')
        derived = netlabel.private(raw, 'security_netlbl_sid_to_secattr')
        for token in ('sidtab_search(policy->sidtab, sid)', 'rcu_read_lock()', 'rcu_read_unlock()',
                      'NETLBL_SECATTR_DOMAIN_CPY | NETLBL_SECATTR_SECID', 'mls_export_netlbl_lvl(policydb, ctx, secattr)'):
            self.assertIn(token, derived)
        self.assertNotIn('kstrdup(', derived)
        self.assertIn('lsf_prepaid_netlabel_strdup(sym_name(policydb, SYM_TYPES, ctx->type - 1), source)', derived)
        helper = self.owned('netlabel-private.c')
        self.assertLess(helper.index('lsf_factory_child_allocate(*source, bytes + 1'), helper.index('memcpy(copy, text, bytes + 1)'))

    def test_mls_category_values_and_original_failure_destructor_remain(self):
        for name in ('mls_export_netlbl_cat', 'ebitmap_netlbl_export', 'netlbl_catmap_setlong'):
            derived = netlabel.private(self.original(name), name)
            self.assertNotIn('kmalloc(', derived)
            self.assertNotIn('kzalloc(', derived)
        derived = netlabel.private(self.original('ebitmap_netlbl_export'), 'ebitmap_netlbl_export')
        self.assertEqual(self.original('ebitmap_netlbl_export').split('netlbl_export_failure:')[1],
                         derived.split('netlbl_export_failure:')[1])
        nodes = netlabel.private(self.original('_netlbl_catmap_getnode'), '_netlbl_catmap_getnode')
        self.assertIn('if (!source || gfp_flags != GFP_ATOMIC)', nodes)
        self.assertNotIn('netlbl_catmap_alloc(', nodes)
        self.assertIn('sizeof(*iter), LSF_PREPAID_LABEL_CATMAP', nodes)

    def test_cipso_admission_precedes_copy_and_publication_with_original_policy_and_error_results(self):
        raw = self.original('cipso_v4_sock_setattr')
        derived = netlabel.private(raw, 'cipso_v4_sock_setattr')
        self.assertNotIn('kmalloc(', derived)
        self.assertNotIn('kzalloc(', derived)
        self.assertLess(derived.index('sizeof(*opt) + opt_len, LSF_PREPAID_IP_OPTIONS'), derived.index('memcpy(opt->opt.__data'))
        self.assertLess(derived.index('lsf_factory_options_publish(opt)'), derived.index('rcu_assign_pointer('))
        self.assertLess(derived.index('lsf_factory_options_owned(old, *source)'), derived.index('lsf_factory_options_publish(opt)'))
        self.assertIn('cipso_v4_genopt(buf, buf_len, doi_def, secattr)', derived)
        self.assertIn('sk_conn->icsk_sync_mss(sk, sk_conn->icsk_pmtu_cookie)', derived)
        self.assertIn('return ret_val;', derived)
        for name in ('netlbl_sock_setattr', 'netlbl_conn_setattr'):
            derived = netlabel.private(self.original(name), name)
            self.assertIn('return ret_val;', derived)
            self.assertIn('rcu_read_unlock()', derived)
            self.assertIn('-EOPNOTSUPP', derived)

    def test_original_options_free_sites_retain_real_rcu_or_normal_free(self):
        for name in ('cipso_v4_delopt', 'inet_sock_destruct'):
            derived = netlabel.observed(self.original(name), name)
            self.assertIn('!lsf_prepaid_options_retire(', derived)
            self.assertIn('kfree_rcu(', derived)
        helper = self.owned('netlabel-private.c')
        self.assertIn('call_rcu(&options->rcu, lsf_prepaid_options_callback)', helper)
        callback = helper[helper.index('static void lsf_prepaid_options_callback'):helper.index('bool lsf_prepaid_options_retire')]
        self.assertLess(callback.index('lsf_factory_blob_lookup('), callback.index('lsf_factory_blob_finish('))
        self.assertNotIn('options->', callback)

    def test_complete_label_graph_is_validated_before_destructors_and_unknown_cache_poison_retains(self):
        helper = self.owned('netlabel-private.c')
        selected = helper[helper.index('bool lsf_prepaid_label_secattr_return'):helper.index('static void lsf_prepaid_options_callback')]
        self.assertLess(selected.index('count < LSF_ALLOCATION_SLOTS'), selected.index('netlbl_secattr_destroy(secattr)'))
        self.assertIn('child.context != copy.context', selected)
        self.assertIn('secattr->flags & ~allowed', selected)
        self.assertIn('lsf_factory_poison(copy.context)', selected)
        self.assertNotIn('NETLBL_SECATTR_CACHE |', selected)

    def test_original_root_blob_allocators_do_not_admit_new_child_kinds(self):
        core = self.owned('prepaid.h')
        alloc = core[core.index('static inline int lsf_prepaid_blob_allocate'):core.index('static inline int lsf_prepaid_child_allocate')]
        self.assertIn('kind != LSF_PREPAID_INODE_BLOB && kind != LSF_PREPAID_SOCK_BLOB', alloc)
        child = core[core.index('static inline int lsf_prepaid_child_allocate'):core.index('static inline int lsf_prepaid_blob_find')]
        self.assertIn('lsf_prepaid_allocate(pool, key, bytes, 1, parent', child)
        self.assertIn('kind < LSF_PREPAID_LABEL || kind > LSF_PREPAID_IP_OPTIONS', child)

    def test_published_options_and_callback_retirement_have_distinct_closed_states(self):
        core = self.owned('prepaid.h')
        self.assertIn('record->deferred != LSF_PREPAID_PUBLISHED', core)
        self.assertIn('record->deferred = LSF_PREPAID_PUBLISHED', core)
        self.assertIn('record->deferred = LSF_PREPAID_QUEUED', core)
        self.assertIn('record->deferred == LSF_PREPAID_PUBLISHED', core)
        self.assertIn('context->continuations++', core)
        self.assertIn('context->continuations--', core)
        self.assertIn('LSF_BACKING_BYTES 524288u', core)
        self.assertIn('records[LSF_ALLOCATION_SLOTS]', core)

    def test_existing_options_require_same_live_context_and_published_state_before_replacement(self):
        raw = self.owned('factory.c')
        selected = raw[raw.index('int lsf_factory_options_owned('):raw.index('int lsf_factory_options_queue(')]
        self.assertIn('lsf_factory_blob_lookup_locked(address, LSF_PREPAID_IP_OPTIONS, &copy)', selected)
        self.assertIn('copy.context != lsf_factory_context_current(parent.context)', selected)
        self.assertIn('deferred != LSF_PREPAID_PUBLISHED', selected)
        self.assertIn('factory.pool.poisoned = 1', selected)
        self.assertNotIn('lsf_prepaid_allocate(', selected)
        derived = netlabel.private(self.original('cipso_v4_sock_setattr'), 'cipso_v4_sock_setattr')
        self.assertLess(derived.index('lsf_factory_options_owned(old, *source)'), derived.index('rcu_assign_pointer('))

    def test_readonly_parent_check_authenticates_origin_without_allocating_or_dereferencing_address(self):
        raw = self.owned('factory.c')
        selected = raw[raw.index('int lsf_factory_protocol_parent('):raw.index('static int lsf_factory_blob_lookup_locked(')]
        self.assertIn('record->offset != value - base', selected)
        self.assertIn('record->owner_generation != context->key.generation', selected)
        self.assertLess(selected.index('lsf_factory_context_current(context)'), selected.index('record = &factory.pool.records'))
        self.assertNotIn('lsf_prepaid_allocate(', selected)
        self.assertNotIn('address->', selected)
        self.assertNotIn('memcpy(', selected)

    def test_real_security_mandatory_checks_and_uninstalled_profile_are_not_disabled(self):
        self.assertIn('selinux_netlbl_sock_genattr(sk)', self.original('selinux_netlbl_socket_post_create'))
        self.assertIn('netlbl_conn_setattr(', self.original('selinux_netlbl_socket_connect_helper'))
        for field in ('kernelBuilt', 'actualLsmExecuted', 'completeAllocationClosure', 'productionInstallation'):
            self.assertIs(self.fixture[field], False)
        self.assertIn('return NULL;', self.owned('factory-private.h'))
        self.assertIn('lsm_for_each_hook(scall, socket_post_create) { return false; }', self.owned('outer-security.c'))
        for name in ('factory.c', 'netlabel-private.c'):
            self.assertNotIn('EXPORT_SYMBOL', self.owned(name))


if __name__ == '__main__':
    unittest.main()
