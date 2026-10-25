"""Synthetic pinned-printer syntax controls; no compiler/runtime qualification.

These exercise the real reader's complete-body and unknown-edge decisions.
Actual compiler outputs and paired source variants are mandatory hosted gates.
"""
import unittest

from tools import guest_compiler_edges as edges
from tools.dev_workflow.common import digest
from tools.dev_workflow.common import encode

BINDINGS = {key: digest(key.encode()) for key in
            ('sourceDigest', 'componentDigest', 'compilerDigest', 'recipeDigest', 'graphDigest')}

LLVM = b'''define i32 @gate(i32 %seed) {
entry:
  br i1 %condition, label %selected, label %done
selected:
  %value = call i32 @outside.denied(i32 %seed)
  br label %done
done:
  ret i32 %seed
}
'''
MIR = b'''fn gate(_1: u32) -> u32 {
    let mut _0: u32;
    bb0: {
        _0 = outside::denied(copy _1) -> [return: bb1, unwind unreachable];
    }
    bb1: {
        return;
    }
}
'''
GO = b'''gate func(uint32) uint32
  b1:
    (?) v1 = InitMem <mem>
    (+4) v2 = WasmLoweredStaticCall <(uint32,mem)> {outside.denied} v1
    Plain -> b2
  b2: <- b1
    Ret v2
'''


class CompilerEdges(unittest.TestCase):
    def test_Go_result_tuple_preserves_unknown_indirect_and_function_pointer_producers(self):
        raw = (b'gate func() int32\n b1:\n (?) v1 = InitMem <mem>\n'
               b' (?) v2 = Const32 <int32> [0]\n'
               b' (?) v3 = MakeResult <int32,mem> v2 v1\n Ret v3\n')
        observed = edges.observe('go-ssa', raw, 'gate', 'outside.denied', BINDINGS)
        self.assertEqual(observed['state'], 'edge-not-observed')
        for instruction in (
                b' (?) v2 = WasmLoweredClosureCall <int32,mem> v4 v1',
                b' (?) v2 = Addr <func()> {outside.denied} v1'):
            changed = raw.replace(b' (?) v2 = Const32 <int32> [0]', instruction)
            self.assertEqual(edges.observe('go-ssa', changed, 'gate', 'outside.denied', BINDINGS)['state'], 'unknown')

    def read(self, kind, raw):
        target = 'outside::denied' if kind == 'rust-mir' else 'outside.denied'
        return edges.observe(kind, raw, 'gate', target, BINDINGS)

    def test_all_three_real_readers_follow_complete_cfgs_and_bind_raw_inputs(self):
        for kind, raw in (('c-llvm', LLVM), ('rust-mir', MIR), ('go-ssa', GO)):
            with self.subTest(kind=kind):
                row = self.read(kind, raw)
                self.assertEqual(row['state'], 'observed-direct-edge')
                self.assertEqual(row['directEdges'], 1)
                self.assertTrue(row['completeSelectedBody'])
                self.assertEqual(row['rawDigest'], digest(raw))
                self.assertEqual({key: row[key] for key in BINDINGS}, BINDINGS)
                self.assertEqual(row['runtimeExecution'], 'not-observed')

    def test_complete_no_call_bodies_are_not_labelled_api_eliminated(self):
        inputs = (('c-llvm', b'define i32 @gate(i32 %seed) {\nentry:\n ret i32 %seed\n}\n'),
                  ('rust-mir', b'fn gate(_1: u32) -> u32 {\n bb0: {\n _0 = copy _1;\n return;\n }\n}\n'),
                  ('go-ssa', b'gate func(uint32) uint32\n b1:\n (?) v1 = Const32 <uint32> [7]\n Ret v1\n'))
        for kind, raw in inputs:
            with self.subTest(kind=kind):
                row = self.read(kind, raw)
                self.assertEqual((row['state'], row['directEdges'], row['apiSupport']),
                                 ('edge-not-observed', 0, 'unknown'))
                self.assertNotIn('unsupported-eliminated', str(row))

    def test_unreachable_compiler_block_is_not_misreported_as_a_reached_edge(self):
        raw = LLVM.replace(b'br i1 %condition, label %selected, label %done', b'br label %done')
        row = self.read('c-llvm', raw)
        self.assertEqual((row['state'], row['directEdges'], row['reachableBlocks']),
                         ('edge-not-observed', 0, 2))

    def test_truncation_or_missing_successor_cannot_supply_a_negative(self):
        inputs = (('c-llvm', LLVM[:-2]), ('rust-mir', MIR[:-2]),
                  ('go-ssa', GO.replace(b' b2: <- b1\n    Ret v2\n', b'')))
        for kind, raw in inputs:
            with self.subTest(kind=kind):
                self.assertEqual(self.read(kind, raw)['state'], 'unknown')

    def test_indirect_calls_and_unknown_instructions_refuse_closed_negative(self):
        inputs = (('c-llvm', LLVM.replace(b'@outside.denied', b'%callback')),
                  ('rust-mir', MIR.replace(b'outside::denied', b'_2')),
                  ('go-ssa', GO.replace(b'WasmLoweredStaticCall', b'WasmLoweredClosureCall')),
                  ('go-ssa', GO.replace(b'WasmLoweredStaticCall', b'FutureInvoke')),
                  ('c-llvm', LLVM.replace(b'call i32 @outside.denied(i32 %seed)', b'futureInvoke i32 1')))
        for kind, raw in inputs:
            with self.subTest(kind=kind, raw=raw):
                self.assertEqual(self.read(kind, raw)['state'], 'unknown')

    def test_ir_comments_strings_and_substrings_never_count_as_calls(self):
        raw = b'''@private = private constant [20 x i8] c"@outside.denied()\\00"
define i32 @gate(i32 %seed) {
entry:
 ; call i32 @outside.denied(i32 1)
 %x = call i32 @outside.deniedExtra(i32 %seed)
 ret i32 %x
}
'''
        self.assertEqual(self.read('c-llvm', raw)['directEdges'], 0)

    def test_duplicate_root_blocks_or_unbounded_source_are_rejected(self):
        for raw in (LLVM + LLVM, LLVM.replace(b'done:\n', b'entry:\n')):
            with self.assertRaises(ValueError):
                self.read('c-llvm', raw)
        for raw in (b'x' * (edges.MAX_BYTES + 1), b'x' * (edges.MAX_LINE_BYTES + 1), b'\0'):
            with self.assertRaises(ValueError):
                self.read('c-llvm', raw)

    def test_post_terminator_instructions_and_malformed_branch_geometry_are_unknown(self):
        raw = LLVM.replace(b'ret i32 %seed', b'ret i32 %seed\n %x = add i32 1, 2')
        self.assertEqual(self.read('c-llvm', raw)['state'], 'unknown')
        raw = GO.replace(b'Plain -> b2', b'Plain -> b2 b1')
        self.assertEqual(self.read('go-ssa', raw)['state'], 'unknown')

    def test_fixed_pair_requires_actual_whole_source_inventories_and_unchanged_library(self):
        from tools.rust_capsule_project import inventory
        before = {'src/main.c': b'int main() { if (0) { /* lsf-api-root-edge */ denied(); } }',
                  'captured/child.c': b'int denied(void) { return -1; }'}
        after = {**before, 'src/main.c': before['src/main.c'].replace(b'if (0)', b'if (1)')}
        negative = edges.observe('c-llvm', b'define i32 @gate(i32 %seed) {\nentry:\n ret i32 %seed\n}\n',
            'gate', 'outside.denied', {**BINDINGS, 'sourceDigest': digest(inventory(before))})
        positive = edges.observe('c-llvm', LLVM, 'gate', 'outside.denied',
            {**BINDINGS, 'sourceDigest': digest(inventory(after)), 'componentDigest': digest(b'other component')})
        proof = edges.controlled_pair(negative, positive, before, after, 'src/main.c')
        self.assertEqual(proof['scope'], 'one-controlled-compiler-call-edge')
        self.assertEqual(proof['apiSupport'], 'unknown')
        with self.assertRaises(ValueError):
            edges.controlled_pair(negative, positive, before,
                {**after, 'captured/child.c': b'int denied(void) { return 0; }'}, 'src/main.c')
        with self.assertRaises(ValueError):
            edges.controlled_pair(negative, positive, before,
                {**after, 'src/main.c': after['src/main.c'] + b' /* another mutation */'}, 'src/main.c')

    def test_even_rehashed_invalid_shape_and_stale_context_refuse(self):
        original = self.read('c-llvm', LLVM)
        for field, wrong in (('blocks', True), ('state', 'unsupported-eliminated'),
                             ('apiSupport', 'qualified'), ('authority', 'execution')):
            row = {**original, field: wrong}
            row['identity'] = digest(encode({key: item for key, item in row.items() if key != 'identity'}))
            with self.assertRaises(ValueError):
                edges.validate(row)
        with self.assertRaises(ValueError):
            edges.validate(original, bindings={**BINDINGS, 'compilerDigest': digest(b'changed compiler')})


if __name__ == '__main__':
    unittest.main()
