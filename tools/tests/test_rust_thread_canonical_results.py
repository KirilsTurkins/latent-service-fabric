"""Encoded result proof controls, distinct from authentic guest execution."""
from __future__ import annotations

import copy
import unittest

from tools import rust_thread_canonical_results as result
from tools import rust_thread_callback_paths as paths
from tools import rust_thread_object_graph as graph


def fixture(*, area=512, length_offset=8, deallocator=2):
    u, s, section = paths.unsigned, paths.signed, paths.section

    def name(value):
        raw = value.encode()
        return u(len(raw)) + raw

    post = (b'\x01\x01\x7f\x02\x40\x20\0\x28\x02' + u(length_offset) +
            b'\x22\x01\x45\x0d\0\x20\0\x28\x02\x04\x20\x01\x41\x01\x10' +
            u(deallocator) + b'\x0b\x0b')
    bodies = [b'\0\x41' + s(area) + b'\x0f\x0b', post, b'\0\x0b', b'\0\x0b']
    core = (b'\0asm\1\0\0\0' +
            section(1, b'\x03\x60\0\x01\x7f\x60\x01\x7f\0\x60\x03\x7f\x7f\x7f\0') +
            section(3, b'\x04\0\x01\x02\x02') + section(5, b'\x01\0\x01') +
            section(6, b'\x02\x7f\x01\x41' + s(2048) + b'\x0b\x7f\0\x41' + s(1024) + b'\x0b') +
            section(7, b'\x04' + name('public') + b'\0\0' + name('post') + b'\0\x01' +
                    name('__stack_pointer') + b'\x03\0' + name('__stack_low') + b'\x03\x01') +
            section(10, u(len(bodies)) + b''.join(u(len(body)) + body for body in bodies)))
    # This is explicit encoded API mechanism input, never a trusted catalogue
    # or proof of original Rust execution. All returned authority gates stayfalse.
    observed = {'coreDigest': graph.digest(core), 'failures': [], 'unresolvedReferents': [],
                'instructionDecodeFailures': [],
                'matchedBindings': [{'kind': 1, 'actual': 768, 'sourceBytes': 32, 'bodyMatched': True},
                                    {'kind': 0, 'actual': 3, 'bodyMatched': True}],
                'compilerDelegators': [{'function': 2, 'delegate': 3,
                                       'originalSymbol': 'encoded_control14___rust_dealloc'}]}
    return core, observed


class CanonicalResults(unittest.TestCase):
    def test_original_panic_binding_never_exempts_other_import_or_callback_paths(self):
        from tools import rust_thread_guard_controls as guard_controls
        # Encoded mechanism fixture only. This is not an authentic std object
        # or host catalogue; every resulting qualification flag stays false.
        core = guard_controls.fixture()
        _, imports, bodies = graph.code(core)
        panic = bodies[12-len(imports)]
        original = {'coreDigest': graph.digest(core), 'failures': [], 'unresolvedReferents': [],
                    'instructionDecodeFailures': [], 'matchedBindings': [{
                        'kind': 0, 'bodyMatched': True, 'actual': 12,
                        'object': 'libcore-encoded-fixture.rlib/control.o',
                        'originalSymbol': 'encoded_fixture_4core9panicking9panic_fmt',
                        'sourceBodyDigest': graph.digest(panic)[7:], 'sourceBytes': len(panic)}]}
        observed = result.observe_system_panic_trap(core, original, guard_controls.POST, 'cabi_realloc')
        self.assertEqual(observed['originalFunction'], 12)
        self.assertEqual(observed['linkedOriginalBodyDigest'], graph.digest(panic))
        self.assertFalse(observed['trustedSourceCatalogueAuthenticated'])
        for field, value, reason in [('actual', 13, 'original-signature'),
                                     ('sourceBytes', len(panic)+1, 'original-body-binding'),
                                     ('object', 'untrusted-other.rlib/control.o', 'original-source-binding')]:
            changed = copy.deepcopy(original)
            changed['matchedBindings'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, reason):
                result.observe_system_panic_trap(core, changed, guard_controls.POST, 'cabi_realloc')
        # A direct context import outside the exact panic body still refuses.
        changed = core.replace(b'\0\x20\0\x1a\x0b', b'\0\x10\0\x1a\x0b', 1)
        changed_graph = {**original, 'coreDigest': graph.digest(changed)}
        with self.assertRaisesRegex(ValueError, 'remaining-import-or-lifecycle'):
            result.observe_system_panic_trap(changed, changed_graph, guard_controls.POST, 'cabi_realloc')

    def test_structured_exits_require_one_static_area_and_reject_branch_or_dynamic_bypass(self):
        constant = b'\x41' + paths.signed(512)
        body = b'\0\x41\x01\x04\x40' + constant + b'\x0f\x05' + constant + b'\x0f\x0b\0\x0b'
        self.assertEqual(result.static_return_area(body), (512, 2))
        for changed, reason in [
                (body.replace(constant, b'\x41' + paths.signed(516), 1), 'distinct-static-return'),
                (b'\0' + constant + b'\x0c\0\x0b', 'function-label-branch'),
                (b'\0\x20\0\x0f\x0b', 'dynamic-or-unqualified-return'),
                (b'\0\x02\x7f' + constant + b'\x0c\0\x0b\x0f\x0b', 'unqualified-return')]:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                result.static_return_area(changed)
        # Operator retention refuses before appending beyond its paid budget.
        with self.assertRaisesRegex(ValueError, 'operator-bound'):
            graph.bounded_instructions(b'\0\x01\x01\x0b', remaining=2)

    def test_whole_post_body_original_allocator_and_private_bss_ranges_are_required(self):
        wit = {'result': {'ok': 'string', 'err': 'string'}}
        surface = {'worlds': [{'name': 'service', 'exports': {'interface-0': {'interface': {'id': 0}}}}],
                   'interfaces': [{'name': 'api', 'package': 0, 'functions': {'run': {
                       'name': 'run', 'kind': 'freestanding', 'params': [], 'result': 0}}}],
                   'packages': [{'name': 'examples:guard@1.0.0'}], 'types': [{'kind': wit}]}
        self.assertEqual(result.select_wit_result(surface, 'service', 'examples:guard/api@1.0.0#run'), wit)
        with self.assertRaisesRegex(ValueError, 'public-binding'):
            result.select_wit_result(surface, 'service', 'outside:other/api@1.0.0#run')
        aliased = copy.deepcopy(surface)
        aliased['types'][0] = {'kind': {'type': 0}}
        with self.assertRaisesRegex(ValueError, 'cycle-or-depth'):
            result.select_wit_result(aliased, 'service', 'examples:guard/api@1.0.0#run')
        core, observed = fixture()
        report = result.observe_canonical_result(core, 'public', 'post', observed, wit)
        self.assertEqual((report['staticResultArea'], report['postOriginalAllocatorBody']), (512, 3))
        self.assertFalse(report['canonicalResultAreaAuthenticated'])
        for args, reason in [({'area': 768}, 'private-data-alias'),
                             ({'length_offset': 4}, 'post-whole-body'),
                             ({'deallocator': 3}, 'original-deallocator-binding')]:
            changed, inputs = fixture(**args)
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, reason):
                result.observe_canonical_result(changed, 'public', 'post', inputs, wit)
        missing = copy.deepcopy(observed)
        missing['matchedBindings'].pop()
        with self.assertRaisesRegex(ValueError, 'original-deallocator-binding'):
            result.observe_canonical_result(core, 'public', 'post', missing, wit)
        with self.assertRaisesRegex(ValueError, 'wit-layout-not-qualified'):
            result.observe_canonical_result(core, 'public', 'post', observed, {'result': 'string'})


if __name__ == '__main__':
    unittest.main()
