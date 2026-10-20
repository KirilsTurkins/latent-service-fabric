"""Closed private observation bounds; no component qualification claims."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

from tools import diagnose_java_resource_failure as private
from tools import java_resource_private_observer as observer
from tools.rust_capsule_project import ROOT


class JavaResourcePrivateObserver(unittest.TestCase):
    def row(self,variant='cannot-block-sync-task',frames=None):
        frames=[] if frames is None else frames
        return observer.PREFIX+json.dumps({'trapVariant':variant,'available':bool(frames),
            'truncated':False,'frames':frames}).encode()+b'\n'

    def test_closed_variant_and_numeric_frames_are_observed_without_error_text(self):
        row=observer.capture(self.row(frames=[{'functionIndex':41,'functionOffset':24,'moduleOffset':3121}]))
        self.assertEqual(row['status'],'observed')
        self.assertEqual(row['records'][0]['trapVariant'],'cannot-block-sync-task')
        self.assertEqual(row['records'][0]['frames'][0]['functionIndex'],41)
        self.assertFalse(row['qualification'])
        self.assertFalse(row['rawNodeOutputRetained'])

    def test_unknown_variant_nonnumeric_frame_overflow_and_extra_fields_are_refused(self):
        invalid=[self.row('arbitrary-error-text'),self.row(frames=[{'functionIndex':'name',
            'functionOffset':24,'moduleOffset':3121}]),self.row()*17,b'x'*262145,
            observer.PREFIX+b'{"trapVariant":"cannot-block-sync-task","available":false,"truncated":false,"frames":[],"message":"unknown"}\n']
        for raw in invalid:
            with self.subTest(raw=raw[:64]),self.assertRaises(RuntimeError):observer.capture(raw)
        frame={'functionIndex':1,'functionOffset':None,'moduleOffset':None}
        value=observer.capture(self.row(frames=[frame]*20)+self.row(frames=[frame]*20))
        self.assertEqual(sum(len(row['frames']) for row in value['records']),32)
        self.assertTrue(value['records'][-1]['truncated'])

    def test_only_two_authenticated_private_overlays_change_before_public_classification(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary);sources,overlays=observer.overlay_sources(ROOT,path)
            self.assertEqual(set(sources),set(observer.PREIMAGES))
            for generated,original in overlays:
                self.assertEqual('sha256:'+hashlib.sha256(original.read_bytes()).hexdigest(),
                    sources[original.relative_to(ROOT).as_posix()]['original'])
            text=(path/'containment.rs').read_text()
            self.assertLess(text.index('let private_variant'),text.index('let label = trap_label'))
            self.assertIn('wasmtime::Trap::CannotBlockSyncTask',text)
            self.assertIn('wasm_backtrace_max_frames(std::num::NonZeroUsize::new(32))',(path/'engine.rs').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name in observer.PREIMAGES:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
            (root/next(iter(observer.PREIMAGES))).write_bytes(b'changed original')
            with self.assertRaisesRegex(RuntimeError,'original-preimage'):observer.overlay_sources(root,root)

    def test_fixed_complete_member_preimages_refuse_missing_changed_or_foreign_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);rows=[]
            for index in range(225):
                name=f'public-{index:03}.json';(root/name).write_bytes(b'x')
                rows.append({'path':name,'bytes':1,'sha256':'sha256:'+hashlib.sha256(b'x').hexdigest()})
            spec={'memberCount':225,'members':rows};private.verify_members(root,spec)
            (root/'public-000.json').write_bytes(b'y')
            with self.assertRaisesRegex(RuntimeError,'preimage'):private.verify_members(root,spec)
            (root/'public-000.json').write_bytes(b'x');(root/'public-001.json').unlink()
            with self.assertRaisesRegex(RuntimeError,'complete-members'):private.verify_members(root,spec)
            (root/'public-001.json').write_bytes(b'x');(root/'foreign.json').write_bytes(b'x')
            with self.assertRaisesRegex(RuntimeError,'unlisted-member'):private.verify_members(root,spec)

    def test_original_jobs_steps_commands_and_deadlines_remain_exact(self):
        old=yaml.safe_load(subprocess.check_output(['git','show','063be0a52eac35d6d0acf836089479437c9ce07b:.github/workflows/java-resource-runtime.yml'],cwd=ROOT))
        new=yaml.safe_load((ROOT/'.github/workflows/java-resource-runtime.yml').read_bytes())
        projected=copy.deepcopy(new)
        projected[True]['workflow_dispatch']['inputs'].pop('observe_retained_failure')
        projected['jobs'].pop('private-observer')
        for name in old['jobs']:projected['jobs'][name]['if']=old['jobs'][name]['if']
        self.assertEqual(projected,old)
        job=new['jobs']['private-observer']
        self.assertEqual(job['timeout-minutes'],20)
        self.assertIn('inputs.observe_retained_failure',job['if'])
        self.assertFalse(new[True]['workflow_dispatch']['inputs']['observe_retained_failure']['default'])
