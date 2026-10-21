"""Source-only failure injection; no compiler, process or C runtime executes."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_c_canonical_abi as campaign
from tools.build_process import BuildProcessError


class CCanonicalReceiptTests(unittest.TestCase):
    def tools(self):
        return {name:Path(__file__).resolve() for name in
                ('zig','wit-bindgen','wasm-tools','node','transformer')}

    def test_timeout_keeps_attempted_stage_without_completed_or_cleanup_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'control'
            primary = BuildProcessError('command-timeout')
            with patch.object(campaign.sys,'platform','linux'), \
                 patch.object(campaign,'run_bounded_result',side_effect=primary) as process:
                with self.assertRaises(BuildProcessError) as observed:
                    campaign.execute(output,self.tools())
            self.assertIs(observed.exception,primary)
            process.assert_called_once()
            report = json.loads((output/'report.json').read_text())
            self.assertEqual(report['failedStage'],'zig-version')
            self.assertEqual(report['commands'],[{'stage':'zig-version','program':Path(__file__).name}])
            self.assertFalse(report['actualGeneratedCAbiExecuted'])
            self.assertFalse(report['actualComponentGraphAuthenticated'])

    def test_only_real_completed_return_gets_elapsed_and_descendant_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'control'
            completed = subprocess.CompletedProcess(['modeled-tool'],0,b'0.16.0\n',b'')
            primary = BuildProcessError('command-output-limit')
            with patch.object(campaign.sys,'platform','linux'), \
                 patch.object(campaign,'run_bounded_result',side_effect=[completed,primary]):
                with self.assertRaises(BuildProcessError) as observed:
                    campaign.execute(output,self.tools())
            self.assertIs(observed.exception,primary)
            report = json.loads((output/'report.json').read_text())
            first,second = report['commands']
            self.assertTrue(first['completed'] and first['descendantsCleaned'])
            self.assertGreaterEqual(first['elapsedSeconds'],0)
            self.assertEqual(second,{'stage':'bindgen-version','program':Path(__file__).name})
            self.assertEqual(report['failedStage'],'bindgen-version')
            self.assertEqual(report['status'],'failed')

    def test_secondary_fence_failure_cannot_mask_original_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'control'
            primary = BuildProcessError('command-timeout')
            with patch.object(campaign.sys,'platform','linux'), \
                 patch.object(campaign,'sources',side_effect=[{},OSError('modeled-fence')]), \
                 patch.object(campaign,'run_bounded_result',side_effect=primary):
                with self.assertRaises(BuildProcessError) as observed:
                    campaign.execute(output,self.tools())
            self.assertIs(observed.exception,primary)
            report = json.loads((output/'report.json').read_text())
            self.assertTrue(report['inputFenceObservationRefused'])
            self.assertEqual(report['failedStage'],'zig-version')


if __name__ == '__main__':
    unittest.main()
