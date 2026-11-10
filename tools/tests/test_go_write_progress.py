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
from tools import go_network_deadline_reference as deadline
from tools import go_network_empty_read_reference as empty_read
from tools import go_network_half_close_reference as half_close

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
        timeout = deadline.method(raw)
        self.assertEqual(raw.count(timeout),1)
        self.assertEqual(deadline.projected(raw).count(timeout),1)
        for invalid in (raw+timeout,raw.replace(b'\n',b'\r\n'),b'x'*65537,
                        raw.replace(b'func lsfStreamTimeout(',b'func changedTimeout(')):
            with self.assertRaises(ValueError):deadline.method(invalid)
        for invalid in (raw+body,raw.replace(b'\n',b'\r\n'),b'x'*65537,raw.replace(b'func (c *lsfStreamConn) Write(',b'func changed('),raw.replace(b'const lsfStreamMaximumChunk = 16384',b'const lsfStreamMaximumChunk = 32768')):
            with self.assertRaises(ValueError):q.method(invalid)
    def test_old_source_is_authenticated_and_genuinely_has_the_single_chunk_counterexample(self):
        old=subprocess.check_output(['git','show',q.BASELINE+':'+q.TEMPLATE],cwd=ROOT)
        body=q.method(old);self.assertEqual(hashlib.sha256(body).hexdigest(),q.OLD_SHA)
        self.assertIn(b'if int(r.Ok()) < len(bytes)',body)
        self.assertNotIn(b'for written < len(bytes)',body)
        self.assertEqual(q.observed(self.encoded(self.result(True)),True),[q.CASES[0]])
        self.assertEqual(hashlib.sha256(deadline.method(old)).hexdigest(),deadline.OLD_SHA)
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
        def deadline_rows(old=False):
            package='example.invalid/streamdeadline'
            cases=[deadline.CASES[0]] if old else deadline.CASES
            rows=[{'Package':package,'Action':'start'}]
            for case in cases:
                if old:rows.append({'Package':package,'Action':'output','Test':case,
                    'Output':'provider-timeout-argument-rejected: value=11000 present=true error=<nil>'})
                rows.append({'Package':package,'Action':'fail' if old else 'pass','Test':case})
            rows.append({'Package':package,'Action':'fail' if old else 'pass'})
            return rows
        self.assertEqual(deadline.observed(self.encoded(deadline_rows()),False),list(deadline.CASES))
        self.assertEqual(deadline.observed(self.encoded(deadline_rows(True)),True),[deadline.CASES[0]])
        rows=deadline_rows(True);rows[1]['Output']='compiler error'
        with self.assertRaises(ValueError):deadline.observed(self.encoded(rows),True)
        rows=deadline_rows();rows.insert(2,rows[1])
        with self.assertRaises(ValueError):deadline.observed(self.encoded(rows),False)
        rows=deadline_rows();rows[1]['Action']='skip'
        with self.assertRaises(ValueError):deadline.observed(self.encoded(rows),False)
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
        for case in deadline.CASES:
            self.assertEqual((ROOT/deadline.TESTS).read_text().count('func '+case+'('),1)
        materials={name:(ROOT/name).read_bytes() for name in deadline.MATERIALS}
        deadline.contract((ROOT/q.TEMPLATE).read_bytes(),materials)
        for name, marker in ((deadline.MATERIALS[0],b'self.limits.absolute_timeout_millis > 10_000'),
                             (deadline.MATERIALS[3],b'r := raw.ConnectContext(ctx, request)')):
            altered=dict(materials);altered[name]=altered[name].replace(marker,b'changed',1)
            with self.assertRaises(ValueError):deadline.contract((ROOT/q.TEMPLATE).read_bytes(),altered)
    def test_close_guard_is_inside_each_fragment_and_has_a_pinned_actual_counterexample(self):
        body=q.method((ROOT/q.TEMPLATE).read_bytes()).decode()
        loop=body.index('for written < len(bytes)')
        self.assertLess(loop,body.index('closed := c.closing || c.writeShut'))
        self.assertLess(body.index('closed := c.closing || c.writeShut'),body.index('WriteContext('))
        self.assertIn('return written, c.opError("write", ErrClosed)',body)
        old=subprocess.check_output(['git','show',q.CLOSE_BASELINE+':'+q.TEMPLATE],cwd=ROOT)
        self.assertEqual(hashlib.sha256(q.method(old)).hexdigest(),q.CLOSE_SHA)
        self.assertNotIn(b'closed := c.closing || c.writeShut',q.method(old))
        rows=[{'Package':'example.invalid/streamwrite','Action':'output','Output':'close-between-fragments: n=40960 error=<nil> calls=3'},
              {'Package':'example.invalid/streamwrite','Action':'fail','Test':q.CASES[-1]},
              {'Package':'example.invalid/streamwrite','Action':'fail'}]
        self.assertEqual(q.observed(self.encoded(rows),True,close=True),[q.CASES[-1]])
        with self.assertRaises(ValueError):q.observed(self.encoded(rows),False)
    def test_empty_read_projection_keeps_exact_methods_and_bounded_fixture(self):
        raw=(ROOT/q.TEMPLATE).read_bytes()
        methods=empty_read.methods(raw)
        projected=empty_read.projected(raw)
        for method in methods:
            self.assertEqual(raw.count(method),1)
            self.assertEqual(projected.count(method),1)
        fixture=(ROOT/empty_read.TESTS).read_text()
        for case in empty_read.CASES:
            self.assertEqual(fixture.count('func '+case+'('),1)
        for invalid in (raw+methods[-1],raw.replace(b'\n',b'\r\n'),b'x'*65537,
                        raw.replace(b'func (c *lsfStreamConn) Read(',b'func renamedRead(')):
            with self.assertRaises(ValueError):empty_read.methods(invalid)
    def test_empty_read_counterexample_and_full_controls_fail_closed(self):
        package='example.invalid/emptyread'
        old=[{'Package':package,'Action':'output','Test':empty_read.CASES[0],
              'Output':'empty-expired: n=0 err=read: i/o timeout calls=0 busy=false'},
             {'Package':package,'Action':'fail','Test':empty_read.CASES[0]},
             {'Package':package,'Action':'fail'}]
        current=[{'Package':package,'Action':'pass','Test':case} for case in empty_read.CASES]
        current.append({'Package':package,'Action':'pass'})
        self.assertEqual(empty_read.observed(self.encoded(old),True),[empty_read.CASES[0]])
        self.assertEqual(empty_read.observed(self.encoded(current),False),list(empty_read.CASES))
        for rows,old_flag in ((old[1:],True),(current[:-2]+current[-1:],False),
                              (current+[current[0]],False),([dict(current[0],Action='skip')]+current[1:],False),
                              ([dict(current[0],Package='unexpected')]+current[1:],False)):
            with self.assertRaises(ValueError):empty_read.observed(self.encoded(rows),old_flag)
        duplicate=b'{"Package":"example.invalid/emptyread","Action":"pass","Action":"fail"}'
        with self.assertRaisesRegex(ValueError,'duplicate-field'):empty_read.observed(duplicate,False)

    def test_half_close_projects_actual_adapter_and_owner_without_rewriting(self):
        raw=(ROOT/q.TEMPLATE).read_bytes()
        sdk=(ROOT/half_close.SDK).read_bytes()
        for method in half_close.methods(raw,half_close.PATTERNS):
            self.assertEqual(raw.count(method),1)
            self.assertEqual(half_close.projected(raw).count(method),1)
        for method in half_close.methods(sdk,half_close.SDK_PATTERNS):
            self.assertEqual(sdk.count(method),1)
            self.assertEqual(half_close.projected_sdk(sdk).count(method),1)
        fixture=(ROOT/half_close.TESTS).read_text()
        for case in half_close.CASES:
            self.assertEqual(fixture.count('func '+case+'('),1)
        for invalid in (raw+half_close.methods(raw,half_close.PATTERNS)[3],
                        raw.replace(b'\n',b'\r\n'),b'x'*65537,
                        raw.replace(b'func (c *lsfStreamConn) CloseWrite(',b'func renamed(')):
            with self.assertRaises(ValueError):half_close.methods(invalid,half_close.PATTERNS)
        for invalid in (sdk+half_close.methods(sdk,half_close.SDK_PATTERNS)[0],
                        sdk.replace(b'func (c *Connection) ShutdownContext(',b'func renamed(')):
            with self.assertRaises(ValueError):half_close.methods(invalid,half_close.SDK_PATTERNS)

    def test_half_close_counterexample_and_full_controls_fail_closed(self):
        package='example.invalid/halfclose'
        old=[{'Package':package,'Action':'output','Test':half_close.CASES[0],
              'Output':'expired-half-close: err=closewrite: i/o timeout calls=0 shut=false'},
             {'Package':package,'Action':'fail','Test':half_close.CASES[0]},
             {'Package':package,'Action':'fail'}]
        current=[{'Package':package,'Action':'pass','Test':case} for case in half_close.CASES]
        current.append({'Package':package,'Action':'pass'})
        self.assertEqual(half_close.observed(self.encoded(old),True),[half_close.CASES[0]])
        self.assertEqual(half_close.observed(self.encoded(current),False),list(half_close.CASES))
        for rows,old_flag in ((old[1:],True),(current[:-2]+current[-1:],False),
                              (current+[current[0]],False),([dict(current[0],Action='skip')]+current[1:],False),
                              ([dict(current[0],Package='unexpected')]+current[1:],False)):
            with self.assertRaises(ValueError):half_close.observed(self.encoded(rows),old_flag)
        duplicate=b'{"Package":"example.invalid/halfclose","Action":"pass","Action":"fail"}'
        with self.assertRaisesRegex(ValueError,'duplicate-field'):half_close.observed(duplicate,False)

    def test_direct_help_works_outside_repo_without_import_path_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,str(ROOT/'tools/qualify_go_write_progress.py'),'--help'],cwd=directory,env=dict(os.environ,PYTHONPATH=''),capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr.decode());self.assertIn(b'--output',result.stdout)

if __name__=='__main__':unittest.main()
