"""Source campaign accounting cannot count malformed negatives as proof."""
from pathlib import Path
import tempfile
import unittest

from tools import qualify_rust_thread_routing as gate
from tools.dev_workflow.common import DevError


class ThreadRoutingCampaign(unittest.TestCase):
    def test_unknown_or_ambiguous_encoder_preimages_fail_closed(self):
        for text in ('absent', 'route route'):
            with self.subTest(text=text), self.assertRaisesRegex(DevError, 'preimage-drift'):
                gate.replace(text, 'route', 'replacement')
        self.assertEqual(gate.replace('route', 'route', 'replacement'), 'replacement')

    def test_existing_output_rejects_before_tool_or_source_consumption(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(DevError, 'output-not-fresh'):
                gate.run(Path(directory), Path('absent-transformer'), Path('absent-encoder'))

    def test_invalid_negative_never_reaches_verifier_or_counts_as_rejection(self):
        for failed in ('parse', 'validate'):
            commands = []
            def command(argv, **kwargs):
                commands.append(argv[1])
                if argv[1] == failed:
                    raise DevError('actual-encoder-failed')
            with tempfile.TemporaryDirectory() as directory:
                with self.subTest(failed=failed), self.assertRaisesRegex(DevError, 'actual-encoder-failed'):
                    gate.negative(command, Path(directory), 'transformer', 'encoder',
                                  'invalid', '(component)', 'expected-reason')
            self.assertNotIn('verify-component', commands)

    def test_passing_negative_requires_validation_then_exact_rejection_and_bound_binary(self):
        commands = []
        def command(argv, **kwargs):
            commands.append((argv[1], kwargs))
            if argv[1] == 'parse':
                argv[-1].write_bytes(b'controlled source-test binary')
        with tempfile.TemporaryDirectory() as directory:
            record = gate.negative(command, Path(directory), 'transformer', 'encoder',
                                   'controlled', '(component)', 'exact-reason')
        self.assertEqual(commands, [('parse', {}), ('validate', {}),
                                    ('verify-component', {'expect': 'exact-reason'})])
        self.assertEqual(record['component']['digest'],
                         'sha256:c38c407c65e9e71ec8df6015068bc6df19e0ae98e1241722822e5323f921dd4f')
        self.assertTrue(record['wasmValidated'])


if __name__ == '__main__':
    unittest.main()
