"""Fixed retained bytes and original compiler provenance, without recompilation."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import java_http_retained_component as retained
from tools.phase2_operator_process import WorkflowError


class JavaHttpRetainedComponentTests(unittest.TestCase):
    def test_fixed_fifty_five_material_pins_are_the_historical_source_bytes(self):
        pins=retained.pins()
        self.assertEqual(len(pins),55)
        self.assertEqual(pins['component.wasm'],{'sha256':
            'sha256:1cfb94306437ffc5e63ba76d981c04cba9ba98419c2b2b3c536f5d91005a6a53','bytes':17034179})
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/retained.PINS;path.parent.mkdir(parents=True)
            path.write_text('{}')
            with patch.object(retained,'ROOT',root),self.assertRaisesRegex(WorkflowError,'fixed-pin-source'):
                retained.pins()

    def test_paths_reject_roots_aliases_parent_segments_windows_drives_and_streams(self):
        retained.safe('package/layers/component.wasm')
        for name in (None,'','.', '../file','/file','a/../file','a//file','a/./file',
                'a\\file','C:/file','file:stream'):
            with self.subTest(name=name),self.assertRaises(WorkflowError):retained.safe(name)

    def test_original_git_objects_are_complete_regular_and_both_object_and_sha256_bound(self):
        data=b'original source\n';oid=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data,
            usedforsecurity=False).hexdigest()
        rows={f'source/{i:03}.txt':{'digest':retained.digest(data),'size':len(data)} for i in range(271)}
        tree=b''.join(b'100644 blob '+oid.encode()+b'\t'+name.encode()+b'\0' for name in rows)
        batch=(oid.encode()+b' blob '+str(len(data)).encode()+b'\n'+data+b'\n')*271
        with patch.object(retained.subprocess,'check_output',side_effect=[tree,batch]) as git:
            retained.git_preimages(rows)
        self.assertEqual(git.call_args_list[0].args[0][3],retained.SOURCE)
        for malformed_tree,malformed_batch in ((tree.replace(b'100644',b'120000',1),batch),
                (tree[:-1]+b'extra\0',batch),(tree,batch.replace(data,b'changed source!\n',1)),
                (tree,batch+b'not-framed')):
            with self.subTest(tree=malformed_tree[:12],batch=len(malformed_batch)), \
                    patch.object(retained.subprocess,'check_output',side_effect=[malformed_tree,malformed_batch]), \
                    self.assertRaises((WorkflowError,ValueError)):
                retained.git_preimages(rows)
        with self.assertRaisesRegex(WorkflowError,'compiler-source-count'):
            retained.git_preimages(dict(list(rows.items())[:-1]))

    def archive(self, *, change=None):
        selected={f'original/{i:02}.json':b'{}' for i in range(55)}
        pins={name:{'sha256':retained.digest(data),'bytes':len(data)} for name,data in selected.items()}
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            for name,data in selected.items():
                info=zipfile.ZipInfo(retained.PREFIX+name)
                if change=='link' and name=='original/00.json':info.external_attr=(0o120777<<16)
                if change=='escape' and name=='original/00.json':info.filename='../outside'
                archive.writestr(info,data)
            for i in range(12):archive.writestr(f'logs/{i:02}.txt',b'not selected')
        return buffer.getvalue(),pins

    def test_archive_selects_only_fifty_five_exact_members_before_validation(self):
        raw,pins=self.archive();artifact={'size_in_bytes':len(raw),'digest':retained.digest(raw)}
        with tempfile.TemporaryDirectory() as temporary,patch.object(retained,'ARTIFACT',artifact), \
                patch.object(retained,'pins',return_value=pins),patch.object(retained,'validate',return_value='checked') as validate:
            output=Path(temporary)/'build'
            self.assertEqual(retained.extract(raw,output),'checked')
            validate.assert_called_once_with(output)
            self.assertEqual({p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()},set(pins))
            self.assertFalse((output/'logs').exists())

    def test_archive_hash_symlink_escape_changed_member_and_wrong_count_are_refused(self):
        for change in ('hash','link','escape','member','count'):
            raw,pins=self.archive(change=change);artifact={'size_in_bytes':len(raw),'digest':retained.digest(raw)}
            if change=='hash':artifact['digest']='sha256:'+'0'*64
            if change=='member':pins['original/00.json']['sha256']='sha256:'+'0'*64
            if change=='count':pins.pop('original/00.json')
            with self.subTest(change=change),tempfile.TemporaryDirectory() as temporary, \
                    patch.object(retained,'ARTIFACT',artifact),patch.object(retained,'pins',return_value=pins), \
                    patch.object(retained,'validate') as validate,self.assertRaises(WorkflowError):
                retained.extract(raw,Path(temporary)/'build')
            validate.assert_not_called()

    def test_only_exact_reviewed_current_differences_are_allowed_after_original_source_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);build=root/'build';build.mkdir()
            sdk={f'vendor/lsf/sdk/file{i:03}':{'digest':retained.digest(b'old'),'size':3} for i in range(199)}
            recipe={f'recipe/file{i:03}':{'digest':retained.digest(b'old'),'size':3} for i in range(70)}
            recipe.update({name.removeprefix('vendor/lsf/'):row for name,row in list(sdk.items())[:3]})
            snapshot={**sdk,'src/dev/latent/app/Capsule.java':{'digest':retained.digest(b'app'),'size':3},
                'wit/world.wit':{'digest':retained.digest(b'wit'),'size':3}}
            (build/'source-inputs.json').write_text(json.dumps(snapshot))
            (build/'recipe-inputs.json').write_text(json.dumps(recipe))
            for name in {**{k.removeprefix('vendor/lsf/'):v for k,v in sdk.items()},**recipe}:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'old')
            for name,data in ((retained.APP_SOURCE,b'app'),(retained.APP_WORLD,b'wit')):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            changed=root/'sdk/file000';changed.write_bytes(b'new')
            with patch.object(retained,'ROOT',root),patch.object(retained,'git_preimages') as original, \
                    patch.object(retained,'CURRENT_DIFFERENCES',{'sdk/file000':retained.digest(b'new')}):
                result=retained.source_proof(build)
                self.assertEqual(len(original.call_args.args[0]),271)
                self.assertEqual(set(result['differences']),{'sdk/file000'})
                self.assertFalse(result['currentComponentCompilationClaimed'])
                self.assertFalse(result['compiledRecipeBytesEqualCurrent'])
                (root/'sdk/file001').write_bytes(b'unreviewed')
                with self.assertRaisesRegex(WorkflowError,'unreviewed-source-drift'):
                    retained.source_proof(build)
                snapshot['vendor/lsf/sdk/file001']['size']=999
                (build/'source-inputs.json').write_text(json.dumps(snapshot))
                with self.assertRaisesRegex(WorkflowError,'overlapping-source-identity'):
                    retained.source_proof(build)
