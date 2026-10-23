"""Complete selected subsystem Task-hook map and original root-css pinning."""
import unittest
from tools import host_stream_kernel_cleanup_cgroup as source


class CleanupCgroupSource(unittest.TestCase):
    def test_selected_subsystems_and_exact_task_hooks(self):
        value = source.preimages()
        self.assertEqual(len(value['registrations']), 14)
        actual = {name:row['taskHooks'] for name,row in value['registrations'].items() if row['taskHooks']}
        self.assertEqual(actual, {
            'cpuset': {'can_fork':'cpuset_can_fork', 'cancel_fork':'cpuset_cancel_fork', 'fork':'cpuset_fork'},
            'pids': {'can_fork':'pids_can_fork', 'cancel_fork':'pids_cancel_fork', 'release':'pids_release'},
            'freezer': {'fork':'freezer_fork'}, 'io': {'exit':'blkcg_exit'},
        })
        self.assertFalse(value['actualCgroupExecution'])
        self.assertFalse(value['fullConstructorClosure'])
        with self.assertRaisesRegex(ValueError, 'cleanup-cgroup-whole-membership'):
            source.transform({}, {})

    def test_pinned_actual_cset_selector_precedes_every_real_callback(self):
        text = source.private_cgroup()
        self.assertLess(text.index('cgroup_css_set_fork(kargs)'), text.index('kargs->cset != &init_css_set'))
        self.assertLess(text.index('kargs->cset != &init_css_set'), text.index('do_each_subsys_mask('))
        selected = text[text.index('if (kargs->cset != &init_css_set)'):text.index('do_each_subsys_mask(')]
        self.assertIn('cgroup_css_set_put_fork(kargs)', selected)
        self.assertIn('return -EOPNOTSUPP', selected)
        pin = source.definition('cgroup_css_set_fork')
        self.assertLess(pin.index('cgroup_threadgroup_change_begin(current)'), pin.index('task_css_set(current)'))
        self.assertLess(pin.index('get_css_set(cset)'), pin.index('kargs->cset = cset'))
        self.assertLess(pin.index('if (!(kargs->flags & CLONE_INTO_CGROUP))'), pin.index('find_css_set('))

    def test_complete_original_callback_and_cancel_body_projects_exactly(self):
        text = source.private_cgroup()
        text = source.replace(text,
            'int lsf_prepaid_cleanup_cgroup_can_fork(struct lsf_cleanup_task_source source,\n'
            '    struct task_struct *child, struct kernel_clone_args *kargs)\n',
            'int cgroup_can_fork(struct task_struct *child, struct kernel_clone_args *kargs)\n')
        text = source.replace(text,
            '\n\tif (!kargs || kargs->flags != LSF_CLEANUP_CLONE_FLAGS || kargs->cgrp || kargs->cset ||\n'
            '\t    !lsf_factory_cleanup_constructor_current(source, child))\n\t\treturn -EOPNOTSUPP;\n', '')
        text = source.replace(text,
            '\n\t/* Inspect the actual pinned cset under the original fork/migration\n'
            '\t * serialization. Never infer root membership from a task name. */\n'
            '\tif (kargs->cset != &init_css_set) {\n'
            '\t\tcgroup_css_set_put_fork(kargs);\n\t\treturn -EOPNOTSUPP;\n\t}\n', '')
        self.assertEqual(text, source.definition('cgroup_can_fork'))

    def test_root_selected_fork_hooks_keep_their_real_fast_paths(self):
        freezer = source.definition('freezer_fork')
        self.assertLess(freezer.index('if (task_css_is_root(task, freezer_cgrp_id))'),
            freezer.index('mutex_lock(&freezer_mutex)'))
        cpuset = source.definition('cpuset_fork')
        self.assertIn('if (cs == &top_cpuset)\n\t\t\treturn;', cpuset)
        ready = source.definition('cgroup_kthread_ready')
        self.assertIn('current->no_cgroup_migration = 0;', ready)
        self.assertNotIn('alloc(', ready)
        exit_hook = source.definition('blkcg_exit')
        self.assertIn('put_disk(tsk->throttle_disk)', exit_hook)
        self.assertNotIn('alloc(', exit_hook)


if __name__ == '__main__':
    unittest.main()
