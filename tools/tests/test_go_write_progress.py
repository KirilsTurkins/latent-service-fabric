"""Exact method projection, bounded source counterexample and strict receipts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from tools import qualify_go_write_progress as q

ROOT=Path(__file__).resolve().parents[2]

class GoWriteProgressTests(unittest.TestCase):
    def result(self, old=False):
        rows=[{'Package':'example.invalid/streamwrite','Action':'start'}]
        cases=[q.CASES[0]] if old else q.CASES
        for case in cases:
            if old:rows.append({'Package':'example.invalid/streamwrite','Action':'output','Test':case,'Output':'chunk-boundary-copy: n=16384 error=write: short write accepted=16384'})
            rows.append({'Package':'example.invalid/streamwrite','Action':'fail' if old else 'pass','Test':case})
        rows.append({'Package':'example.invalid/streamwrite','Action':'fail' if old else 'pass'})
        return rows
    def encoded(self,rows):return b'\n'.join(json.dumps(row).encode() for row in rows)+b'\n'
    def test_exact_production_method_is_projected_without_rewriting_its_body(self):
        raw=(ROOT/q.TEMPLATE).read_bytes();body=q.method(raw)
        self.assertEqual(q.projected(raw),b'package streamwrite\nimport ("context"; lsfIO "io")\n'+body+b'\n')
        self.assertEqual(raw.count(body),1)
        for invalid in (raw+body,raw.replace(b'\n',b'\r\n'),b'x'*65537,raw.replace(b'func (c *lsfStreamConn) Write(',b'func changed('),raw.replace(b'const lsfStreamMaximumChunk = 16384',b'const lsfStreamMaximumChunk = 32768')):
            with self.assertRaises(ValueError):q.method(invalid)
    def test_old_source_is_authenticated_and_genuinely_has_the_single_chunk_counterexample(self):
        old=subprocess.check_output(['git','show',q.BASELINE+':'+q.TEMPLATE],cwd=ROOT)
        body=q.method(old);self.assertEqual(hashlib.sha256(body).hexdigest(),q.OLD_SHA)
        self.assertIn(b'if int(r.Ok()) < len(bytes)',body)
        self.assertNotIn(b'for written < len(bytes)',body)
        self.assertEqual(q.observed(self.encoded(self.result(True)),True),[q.CASES[0]])
    def test_original_counterexample_requires_exact_failed_case_not_a_compile_or_setup_failure(self):
        for rows in ([],self.result(),self.result(True)[:-1],[{'Action':'fail','Package':'wrong'}]):
            with self.assertRaises(ValueError):q.observed(self.encoded(rows),True)
        rows=self.result(True);rows[1]['Output']='compiler failed'
        with self.assertRaises(ValueError):q.observed(self.encoded(rows),True)
    def test_current_requires_all_eight_successes_and_no_skipped_duplicate_or_unknown_cases(self):
        self.assertEqual(q.observed(self.encoded(self.result()),False),list(q.CASES))
        for transform in (lambda r:r[:-2]+r[-1:],lambda r:r[:2]+[r[1]]+r[2:],lambda r:[dict(r[0],Action='skip')]+r[1:],lambda r:[dict(r[0],Package='private')]+r[1:]):
            with self.assertRaises(ValueError):q.observed(self.encoded(transform(self.result())),False)
        raw=self.encoded(self.result()).replace(b'"Action": "start"',b'"Action": "start", "Action": "pass"',1)
        with self.assertRaisesRegex(ValueError,'duplicate-field'):q.observed(raw,False)
    def test_write_preserves_one_owner_actual_prefix_and_original_absolute_deadline(self):
        body=q.method((ROOT/q.TEMPLATE).read_bytes()).decode()
        self.assertEqual(body.count('c.begin(true)'),1);self.assertEqual(body.count('defer release()'),1)
        self.assertIn('part := bytes[written:]',body)
        self.assertIn('failure.AcceptedPrefixBytes += uint32(written)',body)
        self.assertIn('written += int(r.Ok())',body)
        loop=body.index('for written < len(bytes)')
        self.assertLess(loop,body.index('lsfStreamTimeout(deadline)'))
        self.assertLess(body.index('lsfStreamTimeout(deadline)'),body.index('WriteContext('))
        self.assertIn('if r.Ok() == 0',body)
        self.assertNotIn('go func',body);self.assertNotIn('make(',body);self.assertNotIn('ConnectContext',body)
    def test_protocol_doubles_and_go_cases_are_explicit_and_do_not_claim_guest_or_provider_evidence(self):
        source=(ROOT/q.TESTS).read_text()
        for case in q.CASES:self.assertEqual(source.count('func '+case+'('),1)
        self.assertRegex(source, r'payload\(40\s*\*\s*1024\)')
        self.assertRegex(source, r'streamFailure\{7,\s*true\}')
        for marker in ('io.Copy(', 'per-fragment-timeout-reset', 'foreign-count-dispatched-again'):
            self.assertIn(marker,source)
        runner=(ROOT/'tools/qualify_go_write_progress.py').read_text()
        self.assertIn("GOPROXY='off'",runner)
        self.assertIn("'signedGuestExecuted': False",runner)
        self.assertNotIn("'cargo'",runner);self.assertNotIn('compiler.compile(',runner)
    def test_direct_help_works_outside_repo_without_import_path_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,str(ROOT/'tools/qualify_go_write_progress.py'),'--help'],cwd=directory,env=dict(os.environ,PYTHONPATH=''),capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr.decode());self.assertIn(b'--output',result.stdout)

if __name__=='__main__':unittest.main()
