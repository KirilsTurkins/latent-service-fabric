"""Actual initial-only C predicates/whole-source controls; no Linux execution."""
import ast
import hashlib
import importlib
import re
import unittest
from pathlib import Path

from tools import host_stream_kernel_no_begin_root_final_free as source
from tools import host_stream_kernel_root_final_free as root
from tools import host_stream_kernel_late_fd_final_free as late
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_cleanup_native import function
from tools.tests.test_host_stream_kernel_task_identity_geometry import calculate


def parents():
    return {name: row['text'].encode() for group in ('parentDerived', 'readOnlyLayouts')
        for name, row in source.preimages()[group].items()}


def helper():
    return (source.OWNED/'factory-cleanup-no-begin-root-final-free.c').read_text()


def fields(text, name):
    body = re.search(r'struct '+name+r' \{(.*?)\n\};', text, re.S)[1]
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
    result = {}
    for declaration in body.split(';'):
        if not declaration.strip():
            continue
        match = re.fullmatch(r'\s*(struct \w+|unsigned int|lsf_u64|u64|work_func_t)\s+(.*?)\s*',
            declaration, re.S)
        if not match:
            raise ValueError('unknown-actual-layout-declaration')
        for member in match[2].split(','):
            member = member.strip().removeprefix('*')
            if not re.fullmatch(r'[a-z_]+', member):
                raise ValueError('unknown-actual-layout-member')
            result[member] = match[1]
    return result


def interpret(expression, values):
    """Closed interpretation of operands extracted from the actual C guard."""
    expression = expression.replace('lsf_cleanup_root_no_application_locked()', 'no_application')
    expression = expression.replace('lsf_route_cache_empty(&record->route_cache)', 'route_empty')
    expression = expression.replace('(void *)((char *)page_address(factory.pages) + record->offset)',
        'record_address')
    expression = expression.replace('atomic_read_acquire(&lsf_cleanup_irq_hint.phase)', 'phase')
    expression = expression.replace('atomic_read(&lsf_cleanup_irq_hint.uncertain)', 'uncertain')
    expression = expression.replace('in_interrupt()', 'interrupt')
    # Each actual conditional is evaluated from its original condition/arms.
    def conditional(match):
        condition, yes, no = match.groups()
        return yes if interpret(condition, values) else no
    expression = re.sub(r'\((i == 0) \? ([A-Z_]+) : ([A-Z_]+|0u)\)', conditional, expression)
    for member in sorted(set(re.findall(r'\b(?:factory|device|owner|record|lsf_cleanup_irq_hint)'
            r'(?:(?:\.|->)[a-z0-9_]+)+', expression)), key=len, reverse=True):
        expression = expression.replace(member, member.replace('->', '_').replace('.', '_'))
    expression = re.sub(r'\b(\d+)u\b', r'\1', expression)
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    expression = re.sub(r'!(?!=)', ' not ', expression)
    return calculate(ast.parse(' '.join(expression.split()), mode='eval'), values)


def guards():
    return re.findall(r'^    if \((.*?)\)\n        return 0;', helper(), re.S | re.M)


def root_values():
    layout = source.preimages()['readOnlyLayouts']['net/factory-device.c']['text']
    values = {}
    for name, kind in fields(layout, 'lsf_factory_device_state').items():
        if kind in ('struct lsf_prepaid_key', 'struct lsf_prepaid_ticket'):
            values.update({'device_'+name+'_slot':0, 'device_'+name+'_generation':0})
        else:
            values['device_'+name] = 0
    values.update(factory_pages=1, device=1, factory_pool_initialized=1,
        factory_pool_stopped=1, factory_pool_next_generation=3, no_application=1,
        device_key_slot=63, device_key_generation=1, device_root_slot=1,
        device_root_generation=2, device_bootstrap_state=4,
        LSF_DEVICE_OWNER_SLOT=63, LSF_FACTORY_BOOTSTRAP_CLOSED=4)
    return values


def literal_recipe(nodes, outputs, replace):
    """Read the fixed string edits, with no executable-source evaluation."""
    values = {'outputs':outputs}

    def read(node):
        if isinstance(node, ast.Constant) and type(node.value) in (str, int):
            return node.value
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id == 'outputs':
            return outputs[read(node.slice)]
        if isinstance(node, ast.Call) and not node.keywords:
            if isinstance(node.func, ast.Name) and node.func.id == 'replace' and len(node.args) in (3,4):
                return replace(*(read(n) for n in node.args))
            if isinstance(node.func, ast.Attribute) and not node.args:
                value = read(node.func.value)
                if node.func.attr == 'decode' and type(value) is bytes:
                    return value.decode()
                if node.func.attr == 'encode' and type(value) is str:
                    return value.encode()
        raise ValueError('unknown-literal-recipe-expression')

    for node in nodes:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            raise ValueError('unknown-literal-recipe-statement')
        target = node.targets[0]
        value = read(node.value)
        if isinstance(target, ast.Name) and target.id in ('text','name','include'):
            values[target.id] = value
        elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) \
                and target.value.id == 'outputs':
            outputs[read(target.slice)] = value
        else:
            raise ValueError('unknown-literal-recipe-target')


class NoBeginRootSource(unittest.TestCase):
    def test_whole_parent_and_layout_authentication_refuses_every_changed_input(self):
        old = parents()
        old['unrelated.c'] = b'unchanged actual source'
        new = source.transform(old)
        self.assertEqual(new['unrelated.c'], old['unrelated.c'])
        self.assertEqual({n for n in new if new[n] != old.get(n)},
            set(source.preimages()['parentDerived']) | {'net/factory-cleanup-no-begin-root-final-free.c'})
        for name in source.preimages()['parentDerived']:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'parent-whole-preimage'):
                source.transform(dict(old, **{name:old[name]+b'\n'}))
        for name in source.preimages()['readOnlyLayouts']:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'actual-layout'):
                source.transform(dict(old, **{name:old[name]+b'\n'}))
        self.assertFalse(source.preimages()['actualNoBeginCollection'])
        self.assertFalse(source.preimages()['nativeQuotaRelease'])
        self.assertFalse(source.preimages()['productionInstallation'])

    def test_owned_device_and_record_layout_recipes_bind_whole_actual_sources(self):
        fixture = source.preimages()
        for target, recipe_name, initial in (('net/factory-device.c', 'layoutRecipe', 'factory-device.c'),
                ('net/prepaid.h', 'recordLayoutRecipe', 'prepaid.h')):
            outputs = {target:(source.OWNED/initial).read_text().encode()}
            for row in fixture[recipe_name]:
                module = importlib.import_module('tools.'+Path(row['module']).stem)
                actual = ast.parse(Path(module.__file__).read_text())
                nodes = ast.parse(row['statements']).body
                # Exact statement sequence must remain present in its owned function.
                sequence = '\n'.join(ast.unparse(n) for n in nodes)
                self.assertTrue(any(sequence in '\n'.join(ast.unparse(n) for n in f.body)
                    for f in actual.body if isinstance(f, ast.FunctionDef)))
                literal_recipe(nodes, outputs, module.replace)
            self.assertEqual(outputs[target], fixture['readOnlyLayouts'][target]['text'].encode())
        with self.assertRaisesRegex(ValueError, 'unknown-literal-recipe-expression'):
            literal_recipe(ast.parse("text = arbitrary_call('never executed')").body, {}, None)
        outputs = root.transform({n:r['text'].encode() for n,r in root.preimages()['parentDerived'].items()})
        self.assertEqual(late.factory(outputs['net/factory.c'].decode()).encode(),
            parents()['net/factory.c'])
        self.assertEqual(late.collector(outputs['net/factory-cleanup-root-final-free.c'].decode()).encode(),
            parents()['net/factory-cleanup-root-final-free.c'])
        self.assertEqual(outputs['kernel/lsf-cleanup-irq.c'], parents()['kernel/lsf-cleanup-irq.c'])
        e = Editor(outputs['include/net/lsf_stream_cleanup_provider_executor.h'].decode())
        e.edit('#endif\n', late.DECLARATIONS+'#endif\n')
        self.assertEqual(e.finish().encode(), parents()['include/net/lsf_stream_cleanup_provider_executor.h'])
        self.assertEqual((source.OWNED/'factory-cleanup-late-fd-final-free.c').read_bytes(),
            parents()['net/factory-cleanup-late-fd-final-free.c'])

    def test_actual_whole_root_guard_covers_every_typed_member_and_refuses_each_noninitial_value(self):
        layout = source.preimages()['readOnlyLayouts']['net/factory-device.c']['text']
        actual = fields(layout, 'lsf_factory_device_state')
        referenced = set(re.findall(r'device->([a-z_]+)', helper()))
        self.assertEqual(referenced, set(actual))  # Unknown future member cannot disappear silently.
        for name, kind in actual.items():
            if kind in ('struct lsf_prepaid_key', 'struct lsf_prepaid_ticket'):
                for member in ('slot', 'generation'):
                    self.assertIn('device->'+name+'.'+member, helper())
        predicate = guards()[0]
        baseline = root_values()
        self.assertFalse(interpret(predicate, baseline))
        for name in baseline:
            if name.startswith('device_') or name in ('device', 'factory_pages',
                    'factory_pool_initialized', 'factory_pool_stopped',
                    'factory_pool_next_generation', 'no_application'):
                with self.subTest(member=name):
                    wrong = 0 if baseline[name] else 1
                    self.assertTrue(interpret(predicate, dict(baseline, **{name:wrong})))
        for member, historical in (('factory_pool_next_generation', 4),
                ('device_key_generation', 2), ('device_root_generation', 3)):
            self.assertTrue(interpret(predicate, dict(baseline, **{member:historical})))
        self.assertIn('memset(state, 0, sizeof(*state));', layout)
        # Padding is initialized by actual birth, never read as an authority;
        # geometry uses real sizeof, while all named fields are independently checked.
        self.assertNotIn('memcmp', helper())
        self.assertIn('(sizeof(*device) + 63u) & ~(lsf_u64)63u', helper())

    def test_actual_allocation_and_embedded_route_guards_cover_every_record_field(self):
        fixture = source.preimages()
        record = fields(fixture['readOnlyLayouts']['net/prepaid.h']['text'], 'lsf_prepaid_view')
        self.assertEqual(set(record), set(re.findall(r'record->([a-z_]+)', helper())))
        route = fixture['readOnlyLayouts']['net/route-cache-owner.h']['text']
        route_fields = fields(route, 'lsf_route_cache_owner')
        route_predicate = re.search(r'    return (.*?);', route, re.S)[1]
        self.assertEqual(set(route_fields), set(re.findall(r'owner->([a-z_]+)', route_predicate)))
        values = {'owner_'+n:0 for n in route_fields}
        self.assertTrue(interpret(route_predicate, values))
        for member in values:
            with self.subTest(route_member=member):
                self.assertFalse(interpret(route_predicate, dict(values, **{member:1})))
        self.assertEqual(helper().count('!lsf_route_cache_empty(&record->route_cache)'), 2)
        predicate = re.search(r'        if \((record->phase.*?)\)\n            return 0;',
            helper(), re.S)[1]
        baseline = {'record_'+n:0 for n in record if n != 'route_cache'}
        baseline.update(route_empty=1, LSF_PREPAID_LIVE=1, LSF_PREPAID_EMPTY=0, LSF_BACKING_BYTES=524288)
        for index in range(256):
            if index == 1:
                continue
            current = dict(baseline, i=index, record_phase=int(index == 0),
                record_bytes=524288 if index == 0 else 0)
            self.assertFalse(interpret(predicate, current))
            self.assertTrue(interpret(predicate, dict(current, record_phase=2)))  # RETURNED history.
            for member in ['record_'+n for n in record if n != 'route_cache']+['route_empty']:
                with self.subTest(index=index, member=member):
                    wrong = 0 if current[member] else 1
                    self.assertTrue(interpret(predicate, dict(current, **{member:wrong})))
        self.assertIn('i < LSF_ALLOCATION_SLOTS', helper())
        self.assertIn('if (i == 1u)', helper())

    def test_actual_owner_and_root_identity_refuse_noncanonical_births(self):
        owner_predicate = guards()[1]
        baseline = dict(owner_generation=1, owner_cursor=384, rounded=384, owner_live=1,
            owner_continuations=0, owner_closed=1, owner_poisoned=0)
        self.assertFalse(interpret(owner_predicate, baseline))
        for name in baseline.keys()-{'rounded'}:
            with self.subTest(member=name):
                self.assertTrue(interpret(owner_predicate,
                    dict(baseline, **{name:0 if baseline[name] else 1})))
        old = parents()['net/factory-cleanup-root-final-free.c'].decode()
        new = source.transform(parents())['net/factory-cleanup-root-final-free.c'].decode()
        original = function(old, 'static int lsf_cleanup_root_no_application_locked(')
        self.assertEqual(original, function(new, 'static int lsf_cleanup_root_no_application_locked('))
        for name in ('generation', 'cursor', 'live', 'continuations', 'poisoned', 'closed', 'scope.identity[word]'):
            self.assertIn('context->'+name, original)
        self.assertIn('i < LSF_OWNER_SLOTS', original)
        self.assertIn('owner->scope.identity[word]', helper())
        predicate = guards()[2]
        baseline = dict(record_phase=1, record_generation=2, record_owner=63,
            record_owner_generation=1, record_kind=42, record_deferred=2,
            record_offset=327680, record_bytes=384, rounded=384, record_cache_bucket=0,
            record_cache_anchor=0, route_empty=1, record_security_cache_location=0,
            record_security_cache_identity=0, device=1, record_address=1,
            LSF_PREPAID_LIVE=1, LSF_DEVICE_OWNER_SLOT=63, LSF_DEVICE_ROOT=42,
            LSF_PREPAID_PUBLISHED=2, LSF_FACTORY_INFRA_OFFSET=327680)
        self.assertFalse(interpret(predicate, baseline))
        for name in [n for n in baseline if n.startswith('record_')]+['route_empty']:
            with self.subTest(root_member=name):
                self.assertTrue(interpret(predicate,
                    dict(baseline, **{name:0 if baseline[name] else 1})))

    def test_actual_empty_irq_guard_and_one_way_terminal_never_follow_descriptor(self):
        output = source.transform(parents())['kernel/lsf-cleanup-irq.c'].decode()
        body = function(output, 'int lsf_prepaid_cleanup_irq_unborn(void)\n')
        expression = re.search(r'    return (.*?);', body, re.S)[1]
        members = set(re.findall(r'lsf_cleanup_irq_hint((?:\.[a-z_]+)+)', expression))
        baseline = {'lsf_cleanup_irq_hint'+m.replace('.', '_'):0 for m in members
            if m not in ('.phase', '.uncertain')}
        baseline.update(phase=0, uncertain=0, interrupt=0, LSF_CLEANUP_IRQ_EMPTY=0)
        self.assertTrue(interpret(expression, baseline))
        for member in baseline.keys()-{'LSF_CLEANUP_IRQ_EMPTY'}:
            with self.subTest(member=member):
                self.assertFalse(interpret(expression, dict(baseline, **{member:1})))
        release = function(output, 'int lsf_prepaid_cleanup_irq_release_unborn(void)\n')
        self.assertIn('LSF_CLEANUP_IRQ_EMPTY,\n        LSF_CLEANUP_IRQ_RELEASED)', release)
        for forbidden in ('->', 'irq_work_sync', 'irq_work_queue', 'atomic_set', 'memset'):
            self.assertNotIn(forbidden, body+release)
        old = parents()['kernel/lsf-cleanup-irq.c'].decode()
        for prefix in ('int lsf_prepaid_cleanup_stack_release(', 'int lsf_prepaid_cleanup_irq_prepare(',
                'int lsf_prepaid_cleanup_irq_closed(', 'int lsf_prepaid_cleanup_irq_release('):
            self.assertEqual(function(output.split('#else\n')[0], prefix),
                function(old.split('#else\n')[0], prefix))
        hook = function(output.split('#else\n')[0], 'int lsf_prepaid_cleanup_stack_release(')
        early = hook[:hook.index('    base = lsf_cleanup_irq_hint.bank_base;')]
        self.assertIn('LSF_CLEANUP_IRQ_EMPTY', early)
        self.assertIn('LSF_CLEANUP_IRQ_RELEASED', early)
        self.assertIn('return 0;', early)

    def test_fd_only_routing_copies_profile_before_custody_without_expanding_pending(self):
        new = source.transform(parents())
        old = parents()['net/factory-cleanup-late-fd-final-free.c'].decode()
        actual = new['net/factory-cleanup-late-fd-final-free.c'].decode()
        handoff = function(actual, 'static int lsf_cleanup_root_fd_handoff_locked(')
        self.assertLess(handoff.index('no_begin = !returned &&'), handoff.index('factory.opened = 2u'))
        self.assertIn('result = returned ? 1 : (no_begin ? 3 : 2);', handoff)
        self.assertIn('if (transferred == 1 || transferred == 3)', new['net/factory.c'].decode())
        for prefix in ('static int lsf_cleanup_root_pending_locked(',
                'int lsf_factory_cleanup_root_pending(', 'void lsf_factory_cleanup_root_drain('):
            self.assertEqual(function(actual, prefix), function(old, prefix))
        self.assertIn('cleanup_request_returned == 1u', function(actual,
            'static int lsf_cleanup_root_pending_locked('))
        after = handoff[handoff.index('factory.opened = 2u'):]
        self.assertNotIn('factory.device', after)
        self.assertNotIn('lsf_cleanup_root_no_begin_locked()', after)

    def test_child_guards_page_preflight_and_physical_ref_order_are_byte_exact(self):
        old = parents()['net/factory-cleanup-root-final-free.c'].decode()
        new = source.transform(parents())['net/factory-cleanup-root-final-free.c'].decode()
        for prefix in ('static int lsf_cleanup_root_pages_locked(',
                'static int lsf_cleanup_root_records_locked(',
                'static void lsf_cleanup_root_release_physical('):
            self.assertEqual(function(old, prefix), function(new, prefix))
        old_take = function(old, 'static int lsf_cleanup_root_release_take_locked(')
        new_take = function(new, 'static int lsf_cleanup_root_release_take_locked(')
        start = old_take.index('    if (source.owner.slot != LSF_DEVICE_OWNER_SLOT')
        end = old_take.index('    owner = lsf_device_context(', start)
        self.assertIn('    if (!no_begin) {\n'+old_take[start:end]+'    }\n', new_take)
        for guard in ('lsf_cleanup_root_no_application_locked()', 'lsf_cleanup_root_pages_locked()',
                'lsf_cleanup_root_records_locked(source)', 'lsf_prepaid_cleanup_irq_closed(source, base)',
                'lsf_prepaid_cleanup_irq_release(source, base)'):
            self.assertIn(guard, new_take)
        self.assertIn('no_begin ? lsf_prepaid_cleanup_irq_release_unborn()', new_take)
        failure = new_take[new_take.index('factory.pool.poisoned = 1;'):]
        self.assertNotIn('factory.device->', failure)
        self.assertNotIn('device->', failure)
        self.assertNotIn('root->', failure)

    def test_actual_captured_routing_cannot_promote_pending_handoff(self):
        actual = source.transform(parents())['net/factory-cleanup-late-fd-final-free.c'].decode()
        body = function(actual, 'static int lsf_cleanup_root_fd_handoff_locked(')
        capture = re.search(r'    no_begin = (.*?);', body)[1]
        capture = capture.replace('lsf_cleanup_root_no_begin_locked()', 'initial_candidate')
        routing = re.search(r'result = (returned) \? (1) : \((no_begin) \? (3) : (2)\);', body)
        self.assertIsNotNone(routing)
        for returned, initial_candidate, expected in ((1,0,1),(1,1,1),(0,0,2),(0,1,3)):
            values = dict(returned=returned, initial_candidate=initial_candidate)
            no_begin = interpret(capture, values)
            values['no_begin'] = no_begin
            actual_route = int(routing[2] if interpret(routing[1], values)
                else routing[4] if interpret(routing[3], values) else routing[5])
            self.assertEqual(actual_route, expected)
        # Child pending remains route2 even if its unrelated initial-candidate
        # input were asserted: the actual initial guard rejects its born fields.
        initial = root_values()
        for member in ('device_cleanup_request_slot', 'device_cleanup_attempted',
                'device_cleanup_request_returned', 'device_bootstrap_expires_ns'):
            self.assertTrue(interpret(guards()[0], dict(initial, **{member:1})))

    def test_exact_reviewed_inverse_restores_every_parent_byte(self):
        old = parents()
        new = source.transform(old)
        projected = dict(new)
        name = 'net/factory.c'
        projected[name] = projected[name].replace(b'    if (transferred == 1 || transferred == 3)\n',
            b'    if (transferred == 1)\n')
        name = 'net/factory-cleanup-late-fd-final-free.c'
        projected[name] = projected[name].replace(
            b'    unsigned int returned, observed_pending = 0, no_begin;\n',
            b'    unsigned int returned, observed_pending = 0;\n').replace(
            b'    no_begin = !returned && lsf_cleanup_root_no_begin_locked();\n', b'').replace(
            b'    result = returned ? 1 : (no_begin ? 3 : 2);\n', b'    result = returned ? 1 : 2;\n')
        name = 'net/factory-cleanup-root-final-free.c'
        value = projected[name].decode().replace('#include "factory-cleanup-no-begin-root-final-free.c"\n\n', '')
        value = value.replace('    int result = 0, no_begin;\n', '    int result = 0;\n')
        original = old[name].decode()
        start = original.index('    if (source.owner.slot != LSF_DEVICE_OWNER_SLOT')
        end = original.index('    owner = lsf_device_context(', start)
        child = original[start:end]
        value = value.replace('    no_begin = lsf_cleanup_root_no_begin_locked();\n'
            '    if (!no_begin) {\n'+child+'    }\n', child)
        value = value.replace(
            '        (!no_begin && !lsf_cleanup_root_records_locked(source)) ||\n'
            '        !lsf_cleanup_root_pages_locked() ||\n'
            '        !(no_begin ? lsf_prepaid_cleanup_irq_unborn() :\n'
            '            lsf_prepaid_cleanup_irq_closed(source, base)))\n',
            '        !lsf_cleanup_root_records_locked(source) || !lsf_cleanup_root_pages_locked() ||\n'
            '        !lsf_prepaid_cleanup_irq_closed(source, base))\n')
        value = value.replace(
            '        !(no_begin ? lsf_prepaid_cleanup_irq_release_unborn() :\n'
            '            lsf_prepaid_cleanup_irq_release(source, base))) {\n',
            '        !lsf_prepaid_cleanup_irq_release(source, base)) {\n')
        projected[name] = value.encode()
        name = 'kernel/lsf-cleanup-irq.c'
        projected[name] = projected[name].replace(source.IRQ_HELPERS.encode(), b'').replace(
            source.IRQ_FALLBACK.encode(), b'')
        name = 'include/net/lsf_stream_cleanup_provider_executor.h'
        projected[name] = projected[name].replace(source.DECLARATIONS.encode(), b'')
        del projected['net/factory-cleanup-no-begin-root-final-free.c']
        self.assertEqual(projected, old)


if __name__ == '__main__':
    unittest.main()
