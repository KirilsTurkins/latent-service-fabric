"""Encoded object mechanics; these fixtures claim no upstream/runtime execution."""
from __future__ import annotations

import unittest

from tools import rust_thread_object_graph as graph


def leb(value):
    output = bytearray()
    while True:
        part = value & 127
        value >>= 7
        output.append(part | (128 if value else 0))
        if not value:
            return bytes(output)


def string(value):
    raw = value.encode()
    return leb(len(raw)) + raw


def section(kind, raw):
    return bytes([kind]) + leb(len(raw)) + raw


def fixture(*, helper=42, destination=1, extra_caller=False):
    # Both functions have () -> i32; the first calls the second through a
    # genuine padded five-byte Wasm relocation. No original bytes are omitted.
    header = b'\0asm\1\0\0\0'
    types = section(1, b'\x01\x60\x00\x01\x7f')
    count = 3 if extra_caller else 2
    functions = section(3, leb(count) + b'\0' * count)
    first = b'\0\x10' + bytes([destination | 128, 128, 128, 128, 0]) + b'\x0b'
    second = b'\0\x41' + bytes([helper]) + b'\x0b'
    bodies = [first, second]
    if extra_caller:
        bodies.append(b'\0\x10\0\x0b')
    code = section(10, leb(count) + b''.join(leb(len(body)) + body for body in bodies))
    exported = section(7, b'\x01' + string('hook') + b'\0\0')
    core = header + types + functions + exported + code
    original_code = section(10, b'\x02' + leb(len(first)) +
                            b'\0\x10\x81\x80\x80\x80\0\x0b' +
                            leb(4) + b'\0\x41\x2a\x0b')
    symbols = b'\x02\0\0\0' + string('hook') + b'\0\0\x01' + string('helper')
    linking = section(0, string('linking') + b'\x02\x08' + leb(len(symbols)) + symbols)
    # CODE is original section ordinal2. First body starts at2, and the call
    # relocation occupies exactly bytes4..9 of its section payload.
    reloc = section(0, string('reloc.CODE') + b'\x02\x01\0\x04\x01')
    original = header + types + section(3, b'\x02\0\0') + original_code + linking + reloc
    name = 'mechanism.o/'.ljust(16)
    ar_header = (name + '0'.ljust(12) + '0'.ljust(6) + '0'.ljust(6) +
                 '100644'.ljust(8) + str(len(original)).ljust(10) + '`\n').encode()
    archive = b'!<arch>\n' + ar_header + original + (b'\n' if len(original) % 2 else b'')
    library = graph.Library('encoded-control.rlib', archive, graph.digest(archive))
    return core, (library,)


class OriginalObjectGraph(unittest.TestCase):
    def test_complete_body_and_real_referent_closure_reject_both_mutations(self):
        original, libraries = fixture()
        observed = graph.observe_objects(original, libraries, ('hook',))
        self.assertEqual(observed['matchedFunctionDefinitions'], 2)
        self.assertEqual(observed['failures'], [])
        self.assertEqual(observed['unresolvedReferents'], [])
        changed_body, _ = fixture(helper=43)
        wrong_referent, _ = fixture(destination=0)
        for changed in (changed_body, wrong_referent):
            with self.subTest(core=graph.digest(changed)):
                result = graph.observe_objects(changed, libraries, ('hook',))
                self.assertTrue(result['failures'])
                self.assertEqual(result['failures'][0]['kind'], 'full-body-or-signature')

    def test_unmatched_incoming_caller_is_retained_and_receipt_mismatch_refuses(self):
        core, libraries = fixture(extra_caller=True)
        result = graph.observe_objects(core, libraries, ('hook',))
        self.assertEqual(result['failures'], [])
        self.assertEqual(result['incomingPrivateReferences'], [
            {'caller': 2, 'offset': 1, 'operation': 16, 'arguments': [0],
             'callerBodyMatched': False}])
        original = libraries[0]
        corrupt = graph.Library(original.label, original.content + b'x', original.expected_digest)
        with self.assertRaisesRegex(ValueError, 'rust-object-library-receipt-mismatch'):
            graph.observe_objects(core, (corrupt,), ('hook',))


    def test_compiler_forwarder_and_original_heap_geometry_require_exact_bounds(self):
        signature = ((0x7f, 0x7f), (0x7f,))
        forward = b'\0\x20\0\x20\x01\x10\x07\x0f\x0b'
        self.assertEqual(graph.compiler_delegator(forward, signature, signature, 2), 7)
        wrong_argument = b'\0\x20\x01\x20\x01\x10\x07\x0f\x0b'
        with self.assertRaisesRegex(ValueError, 'rust-object-compiler-delegator-body'):
            graph.compiler_delegator(wrong_argument, signature, signature, 2)
        core = (b'\0asm\x01\0\0\0' + section(5, b'\x01\0\x01') +
                section(6, b'\x02\x7f\x01\x41\x80\x10\x0b'
                           b'\x7f\0\x41\x80\x08\x0b'))
        exports = {'__stack_pointer': (3, 0), '__stack_low': (3, 1)}
        self.assertEqual(graph.original_linker_layout(core, exports, 65536),
                         {'stackLow': 1024, 'stackHigh': 2048, 'activeDataHigh': 0,
                          'initialMemoryBytes': 65536})
        # Two authentic active bytes at1023 cross the original stack low1024.
        overlapping = core + section(11, b'\x01\0\x41\xff\x07\x0b\x02ab')
        with self.assertRaisesRegex(ValueError, 'rust-object-layout-original-stack-data-or-memory'):
            graph.original_linker_layout(overlapping, exports, 65536)


if __name__ == '__main__':
    unittest.main()
