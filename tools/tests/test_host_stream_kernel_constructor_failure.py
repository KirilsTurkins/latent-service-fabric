"""Exact source/observation controls; no kernel compilation or VM execution."""
import ast
import hashlib
import re
import unittest
from pathlib import Path
from tools import host_stream_kernel_constructor_failure as observation
from tools import host_stream_kernel_cleanup_constructor as constructor
from tools import host_stream_kernel_cleanup_lifecycle as lifecycle
from tools import host_stream_kernel_cleanup_native_programme as programme
from tools import host_stream_kernel_cleanup_native as native


def originals():
    """Reuse frozen generators, not another copy of the Linux constructor."""
    text = constructor.full_constructor()
    # These are the five existing exact post-constructor source projections,
    # in programme.STAGES order. The whole resulting bytes remain pinned below.
    for include, old, new in (
        ('perf', '\tretval = perf_event_init_task(p, clone_flags);\n',
         '#ifdef CONFIG_PERF_EVENTS\n\tretval = lsf_prepaid_cleanup_perf_event_init_task(source, p, clone_flags);\n'
         '#else\n\tretval = perf_event_init_task(p, clone_flags);\n#endif\n'),
        ('audit', '\tretval = audit_alloc(p);\n',
         '#ifdef CONFIG_AUDITSYSCALL\n\tretval = lsf_prepaid_cleanup_audit_alloc(source, p);\n'
         '#else\n\tretval = audit_alloc(p);\n#endif\n'),
        ('clone', '\t\treturn ERR_PTR(-EOPNOTSUPP);\n',
         '\t\treturn ERR_PTR(-EOPNOTSUPP);\n\tif (!lsf_prepaid_cleanup_clone_args_current(source, args))\n'
         '\t\treturn ERR_PTR(-EOPNOTSUPP);\n'),
        ('io', '\tretval = copy_io(clone_flags, p);\n',
         '#ifdef CONFIG_BLOCK\n\tretval = lsf_prepaid_cleanup_copy_io(source, clone_flags, p);\n'
         '#else\n\tretval = copy_io(clone_flags, p);\n#endif\n'),
        ('cgroup', '\tretval = cgroup_can_fork(p, args);\n',
         '#ifdef CONFIG_CGROUPS\n\tretval = lsf_prepaid_cleanup_cgroup_can_fork(source, p, args);\n'
         '#else\n\tretval = cgroup_can_fork(p, args);\n#endif\n')):
        text = '#include <net/lsf_stream_cleanup_'+include+'.h>\n'+constructor.replace(text, old, new)
    # Preserve the pre-existing prebirth observation's exact literal suffix.
    syntax = ast.parse(Path(programme.__file__).read_text(encoding='utf-8'))
    helper = next(row for row in syntax.body if isinstance(row, ast.FunctionDef)
                  and row.name == 'diagnose_prebirth_refusals')
    suffix = next(ast.literal_eval(row.value) for row in ast.walk(helper) if isinstance(row, ast.AugAssign))
    root = constructor.OWNED
    return {
        'kernel/lsf-cleanup-constructor.c': text.encode(),
        'kernel/lsf-cleanup-lifecycle-task.c': lifecycle.initialized_task().encode(),
        'mm/lsf-cleanup-stack.c': (root/'cleanup-stack-vmap.c').read_bytes(),
        'net/factory-cleanup-stack.c': (root/'factory-cleanup-stack.c').read_bytes(),
        'include/net/lsf_stream_cleanup_stack.h': (root/'cleanup-stack-private.h').read_bytes(),
        'net/factory-cleanup-native-bootstrap.c': (root/'factory-cleanup-native-bootstrap.c').read_bytes()+suffix,
    }


def calls(text):
    ignore = {'if', 'for', 'while', 'switch', 'lsf_cleanup_failure',
              'lsf_cleanup_failure_unwind', 'lsf_factory_cleanup_constructor_failure'}
    # Comments describe original helper names too; they are not calls.
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return [name.removesuffix('_observed') for name in re.findall(r'\b([a-zA-Z_]\w*)\s*\(', text)
            if name not in ignore]


class ConstructorFailureSource(unittest.TestCase):
    def test_exact_six_preimages_and_closed_normal_candidate_projection(self):
        before = originals()
        for name, (size, digest) in observation.PREIMAGES.items():
            self.assertEqual((len(before[name]), hashlib.sha256(before[name]).hexdigest()), (size, digest))
        before['untouched'] = b'unchanged original owner source'
        before['net/factory-private.h'] = (
            'static inline const struct lsf_factory_consumer *lsf_factory_selected_consumer(void)\n'
            '{\n    return NULL;\n}\n'+native.QUALIFICATION_OFF).encode()
        after = observation.transform(before)
        self.assertEqual(set(after), set(before))
        self.assertEqual({name for name in after if before[name] != after[name]}, set(observation.PREIMAGES))
        candidate = native.qualification_projection(after)
        self.assertEqual({name for name in candidate if candidate[name] != after[name]}, {'net/factory-private.h'})
        self.assertIn(native.QUALIFICATION_OFF.encode(), after['net/factory-private.h'])
        self.assertIn(b'return NULL;', candidate['net/factory-private.h'])
        for name in observation.PREIMAGES:
            with self.subTest(name=name), self.assertRaises(ValueError):
                observation.transform({**before, name: before[name]+b'\n'})
        with self.assertRaises(ValueError):
            observation.transform({name: raw for name, raw in before.items()
                                   if name != 'net/factory-cleanup-stack.c'})
        with self.assertRaises(ValueError):
            observation.transform(after)

    def test_original_calls_errno_and_unwind_labels_survive_single_body_wrappers(self):
        before = originals();after = observation.transform(before)
        targets = (
            ('kernel/lsf-cleanup-constructor.c', 'struct task_struct *lsf_prepaid_cleanup_copy_process('),
            ('kernel/lsf-cleanup-lifecycle-task.c', 'struct task_struct *lsf_prepaid_cleanup_dup_initialized('),
            ('kernel/lsf-cleanup-lifecycle-task.c', 'static int lsf_cleanup_dup_empty_user_cpus('),
            ('net/factory-cleanup-stack.c', 'int lsf_factory_cleanup_stack_reserve('),
            ('mm/lsf-cleanup-stack.c', 'static pte_t *lsf_cleanup_existing_pte('),
            ('mm/lsf-cleanup-stack.c', 'static int lsf_cleanup_stack_carve('),
            ('mm/lsf-cleanup-stack.c', 'int lsf_prepaid_cleanup_stack_create('),
        )
        for name, signature in targets:
            observed = signature.replace('(', '_observed(') if any(x in signature for x in
                ('dup_initialized(', 'stack_reserve(', 'existing_pte(', 'stack_create(')) else signature
            old_source, new_source = before[name].decode(), after[name].decode()
            if 'stack_create(' in signature:
                old_source = old_source.split('#else\n', 1)[0]
                new_source = new_source.split('#else\n', 1)[0]
            old = observation.function(old_source, signature)
            new = observation.function(new_source, observed)
            with self.subTest(signature=signature):
                self.assertEqual(calls(new), calls(old))
                if 'stack_carve(' in signature:
                    self.assertEqual(set(re.findall(r'\bgoto (\w+);', new)), {'out'})
                    self.assertEqual(set(re.findall(r'\bgoto (\w+);', old)), {'out'})
                else:
                    self.assertEqual(re.findall(r'\bgoto (\w+);', new), re.findall(r'\bgoto (\w+);', old))
                self.assertEqual(re.findall(r'^\w+:', new, re.M), re.findall(r'^\w+:', old, re.M))
                expected_returns = re.findall(r'\breturn ([^;]+);', old)
                if 'stack_create(' in signature:
                    # The one original short-circuit actor/geometry return is
                    # split into two identical -EOPNOTSUPP returns, in order.
                    self.assertEqual(expected_returns[0], '-EOPNOTSUPP')
                    expected_returns.insert(0, expected_returns[0])
                self.assertEqual(re.findall(r'\breturn ([^;]+);', new), expected_returns)
        full = after['kernel/lsf-cleanup-constructor.c'].decode()
        self.assertIn('kthread_error = lsf_prepaid_cleanup_kthread_prepare(source, p);', full)
        self.assertNotIn('retval = lsf_prepaid_cleanup_kthread_prepare(', full)
        self.assertIn('return lsf_prepaid_cleanup_dup_initialized_observed(source, node, NULL);',
                      after['kernel/lsf-cleanup-lifecycle-task.c'].decode())
        self.assertIn('return lsf_factory_cleanup_stack_reserve_observed(source, actual_task, bytes, address, NULL);',
                      after['net/factory-cleanup-stack.c'].decode())
        self.assertIn('return lsf_prepaid_cleanup_stack_create_observed(source, task, NULL);',
                      after['mm/lsf-cleanup-stack.c'].decode())
        self.assertEqual(after['mm/lsf-cleanup-stack.c'].count(b'int lsf_prepaid_cleanup_stack_create_observed('), 2)

    def test_one_numeric_terminal_printer_first_failure_and_real_unlock_order(self):
        after = observation.transform(originals())
        texts = {name: raw.decode() for name, raw in after.items()}
        self.assertEqual(sum(text.count('LSFVM1 constructor-failure ') for text in texts.values()), 1)
        printer = observation.function(texts['net/factory-cleanup-native-bootstrap.c'],
                                       'void lsf_factory_cleanup_constructor_failure(')
        self.assertIn('lsf_factory_constructor_qualification() && observation && observation->site', printer)
        self.assertEqual(printer.count('pr_info('), 1)
        self.assertIn('site=%u detail=%u origin=%d returned=%d unwind=%u\\n', printer)
        for forbidden in ('%p', '%s', '%x', 'spin_lock', 'kmalloc', 'lsf_device_allocate', 'lsf_device_finish'):
            self.assertNotIn(forbidden, printer)
        header = texts['include/net/lsf_stream_cleanup_stack.h']
        latch = observation.function(header, 'static inline void lsf_cleanup_failure(')
        self.assertIn('if (observation && !observation->site)', latch)
        self.assertNotIn('pr_info', latch)
        full = observation.function(texts['kernel/lsf-cleanup-constructor.c'],
                                    'struct task_struct *lsf_prepaid_cleanup_copy_process(')
        early, tail = full.split('sigemptyset(&delayed.signal);', 1)
        self.assertEqual(early.count('lsf_factory_cleanup_constructor_failure('), 9)
        self.assertEqual(tail.count('lsf_factory_cleanup_constructor_failure('), 1)
        terminal = tail.split('fork_out:\n', 1)[1]
        self.assertLess(terminal.index('spin_unlock_irq('), terminal.index('lsf_factory_cleanup_constructor_failure('))
        self.assertLess(tail.index('delayed_free_task(p);'), tail.index('fork_out:\n'))
        self.assertIn('struct lsf_cleanup_failure_observation observation = {0};', full)

    def test_closed_stage_set_and_short_circuit_stack_guards_keep_real_owners(self):
        before = originals();after = observation.transform(before)
        other = '\n'.join(raw.decode() for name, raw in after.items()
                          if name != 'include/net/lsf_stream_cleanup_stack.h')
        used = set(re.findall(r'LSF_FAILURE_([A-Z0-9_]+)', other))
        self.assertEqual(used, set(observation.SITES))
        self.assertEqual(len(observation.SITES), 55)
        with self.assertRaises(ValueError):
            observation.failure('FOREIGN', '-EOPNOTSUPP')
        stack = after['mm/lsf-cleanup-stack.c'].decode()
        carve = observation.function(stack, 'static int lsf_cleanup_stack_carve(')
        guards = ('if (!vmap_initialized)', 'if (lsf_cleanup_stack_live)',
                  'if (list_empty(&free_vmap_area_list))',
                  'if (!IS_ALIGNED(start, THREAD_ALIGN))', 'if (start < VMALLOC_START)',
                  'if (free->va_end > VMALLOC_END)', 'if (free->va_end <= start)',
                  'if (free->va_end - start <= size)')
        offsets = [carve.index(guard) for guard in guards]
        self.assertEqual(offsets, sorted(offsets))
        self.assertLess(carve.index('spin_lock_irqsave('), min(offsets))
        self.assertGreater(carve.index('spin_unlock_irqrestore('), max(offsets))
        self.assertNotIn('pr_info', carve)
        self.assertIn('lsf_cleanup_existing_pte_observed(start + i * PAGE_SIZE, observation, i)', stack)
        for forbidden in ('pte_alloc', '__vmalloc(', 'purge_vmap', 'schedule_work('):
            # Existing prose may describe the refused allocator; code may not invoke it.
            self.assertNotRegex(re.sub(r'/\*.*?\*/', '', stack, flags=re.S), r'\b'+re.escape(forbidden))
