"""Refuse partial/ignored native control evidence and retain real failure logs."""
from __future__ import annotations
from pathlib import Path
import tempfile
import unittest
from tools import qualify_host_codec_native as owner
from tools.phase2_operator_process import WorkflowError

class HostCodecNative(unittest.TestCase):
    def test_exact_discovery_refuses_empty_missing_extra_and_duplicate_cases(self):
        expected = ('suite::first', 'suite::last')
        good = b'suite::first: test\nsuite::last: test\n2 tests, 0 benchmarks\n'
        owner.exact_list(good, expected)
        for value in (b'', good.replace(b'suite::last: test\n', b''),
                      good+b'suite::extra: test\n', good+b'suite::first: test\n'):
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                owner.exact_list(value, expected)
        with self.assertRaises(WorkflowError): owner.exact_list(good, ())

    def test_exact_execution_refuses_missing_failed_ignored_and_foreign_cases(self):
        expected = ('suite::first', 'suite::last')
        good = b'test suite::first ... ok\ntest suite::last ... ok\n\ntest result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 3 filtered out; finished in 0.01s\n'
        owner.exact_result(good, expected)
        for value in (b'', good.replace(b'test suite::last ... ok\n',b''),
                      good.replace(b'suite::last',b'suite::foreign'),
                      good.replace(b'0 failed',b'1 failed'), good.replace(b'0 ignored',b'1 ignored'),
                      good.replace(b'last ... ok',b'last ... ignored'), good+good):
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                owner.exact_result(value, expected)

    def test_failed_command_still_retains_argv_and_actual_log_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary); (output/'logs').mkdir()
            class Failed:
                records = []
                def run(self, stage, *argv):
                    self.records.append({'stage':stage,'exitCode':1,'seconds':0.25})
                    for stream,raw in [('stdout',b'partial'),('stderr',b'real bounded failure')]:
                        (output/'logs'/f'00-{stage}.{stream}.txt').write_bytes(raw)
                    raise ValueError('failed')
            stages = owner.Stages(Failed(),output)
            with self.assertRaises(ValueError): stages.run('actual','cargo','test','--locked')
            self.assertEqual(stages.records[0]['argv'],['cargo','test','--locked'])
            self.assertEqual(stages.records[0]['exitCode'],1)
            for stream in ('stdout','stderr'):
                observed = stages.records[0]['logs'][stream]
                self.assertEqual({k:v for k,v in observed.items() if k!='path'},owner.file_identity(output/observed['path']))
            self.assertTrue((output/'commands.json').is_file())

    def test_timeout_without_streams_keeps_prerecorded_stage_after_prior_snapshot(self):
        import json
        from tools.build_process import BuildProcessError
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary); (output/'logs').mkdir()
            class Bounded:
                def __init__(self): self.records = []
                def run(self, stage, *argv):
                    observed = json.loads((output/'current-stage.json').read_text())
                    self_check = (observed['stage']==stage and observed['argv']==list(argv)
                                  and observed['status']=='running' and not observed['streamsRetained'])
                    if not self_check: raise AssertionError('stage must be durable before execution')
                    if stage=='first':
                        self.records.append({'stage':stage,'exitCode':0,'seconds':0.25})
                        for stream in ('stdout','stderr'):
                            (output/'logs'/f'00-{stage}.{stream}.txt').write_bytes(b'')
                        return b''
                    raise BuildProcessError('command-output-limit')
            stages = owner.Stages(Bounded(),output)
            stages.run('first','cargo','check')
            with self.assertRaises(BuildProcessError): stages.run('second','cargo','test')
            self.assertEqual(len(json.loads((output/'commands.json').read_text())),1)
            current = json.loads((output/'current-stage.json').read_text())
            self.assertEqual(current['stage'],'second')
            self.assertEqual(current['reason'],'command-output-limit')
            self.assertEqual(current['status'],'failed')
            self.assertFalse(current['streamsRetained'])
            self.assertNotIn('logs',current)
            self.assertEqual(len(list((output/'logs').iterdir())),2)
