"""Enabled audit selection, exact context initialization and return order."""
import unittest
from tools import host_stream_kernel_cleanup_audit as source
from tools.host_stream_kernel_device_security import function


class CleanupAuditSource(unittest.TestCase):
    def test_fixed_actual_source_and_runtime_transition_gate(self):
        value = source.preimages()
        self.assertEqual(len(value['sections']), 9)
        self.assertFalse(value['runtimeAuditContextTransitionsQualified'])
        self.assertFalse(value['fullConstructorClosure'])
        with self.assertRaisesRegex(ValueError, 'cleanup-audit-whole-membership'):
            source.transform({}, {})

    def test_original_filter_and_rcu_extent_project_exactly(self):
        text = function(source.private_audit(), 'static enum audit_state lsf_cleanup_audit_filter_task(')
        text = source.replace(text,
            'static enum audit_state lsf_cleanup_audit_filter_task(struct lsf_cleanup_task_source source,\n'
            '    struct task_struct *tsk, char **key)\n',
            'static enum audit_state audit_filter_task(struct task_struct *tsk, char **key)\n')
        text = source.replace(text, 'lsf_cleanup_audit_key(source, tsk, e->rule.filterkey)',
            'kstrdup(e->rule.filterkey, GFP_ATOMIC)')
        self.assertEqual(text, source.definition('audit_filter_task'))

    def test_original_context_initialization_projects_exactly(self):
        text = function(source.private_audit(), 'static struct audit_context *lsf_cleanup_audit_alloc_context(')
        text = source.replace(text,
            'static struct audit_context *lsf_cleanup_audit_alloc_context(struct lsf_cleanup_task_source source,\n'
            '    struct task_struct *task, enum audit_state state)\n',
            'static inline struct audit_context *audit_alloc_context(enum audit_state state)\n')
        text = source.replace(text,
            'lsf_factory_cleanup_child_new(source, task, LSF_CLEANUP_AUDIT_CONTEXT, task)',
            'kzalloc(sizeof(*context), GFP_KERNEL)')
        self.assertEqual(text, source.definition('audit_alloc_context'))

    def test_original_real_switch_filters_work_flags_and_failure_log_are_kept(self):
        text = function(source.private_audit(), 'int lsf_prepaid_cleanup_audit_alloc(')
        text = source.replace(text,
            'int lsf_prepaid_cleanup_audit_alloc(struct lsf_cleanup_task_source source, struct task_struct *tsk)\n',
            'int audit_alloc(struct task_struct *tsk)\n')
        text = source.replace(text,
            '\n\tif (!lsf_factory_cleanup_constructor_current(source, tsk))\n\t\treturn -EOPNOTSUPP;\n', '')
        text = source.replace(text, 'lsf_cleanup_audit_filter_task(source, tsk, &key)',
            'audit_filter_task(tsk, &key)')
        text = source.replace(text, 'lsf_cleanup_audit_alloc_context(source, tsk, state)',
            'audit_alloc_context(state)')
        text = source.replace(text,
            '\t\tif (key)\n\t\t\t(void)lsf_factory_cleanup_child_finish(key, LSF_CLEANUP_AUDIT_KEY);\n',
            '\t\tkfree(key);\n')
        self.assertEqual(text, source.definition('audit_alloc'))

    def test_key_bound_and_charge_precede_first_copy(self):
        text = function(source.GEOMETRY, 'static char *lsf_cleanup_audit_key(')
        self.assertIn('strnlen(key, AUDIT_MAX_KEY_LEN + 1u)', text)
        self.assertLess(text.index('if (bytes > AUDIT_MAX_KEY_LEN)'),
            text.index('lsf_factory_cleanup_child_new('))
        self.assertLess(text.index('lsf_factory_cleanup_child_new('), text.index('memcpy(copy, key, bytes + 1u)'))
        self.assertIn('if (!key)', text)
        self.assertNotIn('kstrdup(', text.replace('kstrdup(NULL)', 'original NULL'))

    def test_actual_unused_context_name_paths_return_before_allocation(self):
        # This is source evidence for actual kernel VFS calls, not a forced
        # dummy/state flag or a complete future worker-work qualification.
        for name in ('audit_getname', 'audit_inode', 'audit_inode_child'):
            text = source.definition(name)
            self.assertIn('if (context->context == AUDIT_CTX_UNUSED)\n\t\treturn;', text)
        free = source.definition('audit_free_context')
        self.assertLess(free.index('audit_reset_context(context)'), free.index('audit_proctitle_free(context)'))
        self.assertLess(free.index('free_tree_refs(context)'), free.index('kfree(context->filterkey)'))
        self.assertLess(free.index('kfree(context->filterkey)'), free.index('kfree(context);'))


if __name__ == '__main__':
    unittest.main()
