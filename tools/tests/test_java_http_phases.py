"""Selected Java phase adapter controls; these are not signed component execution."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock

from tools import java_http_client as client
from tools import guest_compatibility_build as compatibility
from tools.dev_workflow.common import DevError
from tools.java_guest.compiler import Compiler
from tools.rust_capsule_project import ROOT, digest

PHASE = 'lsf.java.httpurlconnection.phase-timing.v1'
INTERFACE = 'latent:http/phase-timing@0.4.0'


class JavaHttpPhases(unittest.TestCase):
    def test_new_profile_is_explicit_and_original_selection_remains_exact(self):
        self.assertEqual(client.selection({'profile':client.PROFILE_ID}),{'profile':client.PROFILE_ID})
        self.assertEqual(client.selection({'profile':PHASE}),{'profile':PHASE})
        for value in (True,PHASE,{'profile':True},{'profile':PHASE,'fallback':True},
                {'profile':'lsf.java.httpurlconnection.phase-timing.v2'}):
            with self.assertRaises(ValueError):client.selection(value)

    def test_derived_adapter_is_bound_to_captured_preimage_and_existing_owner_limits(self):
        original=(ROOT/'sdk/java-guest/client/dev/latent/guest/client/Connection.java').read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);target=root/'dev/latent/guest/client/Connection.java'
            target.parent.mkdir(parents=True);target.write_bytes(original)
            result=client.stage_phase(ROOT/'sdk/java-guest',root)
            self.assertEqual(result['originalDigest'],digest(original))
            self.assertEqual(result['replacementDigest'],digest(target.read_bytes()))
            self.assertEqual(result['profile'],PHASE)
            transformed=target.read_text()
            for required in ('LatentHttpPhaseTiming.open','LatentHttpPhaseTiming.finish',
                    'LatentHttpPhaseTiming.read','new SocketTimeoutException',
                    'BODY_BYTES = 262144','CHUNK_BYTES = 4096','declaredBytes - acceptedBytes'):
                self.assertIn(required,transformed)
            self.assertNotIn('LatentHttpStreaming.open(',transformed)
            self.assertNotIn('separate connect/read timeout phases are not qualified',transformed)
            self.assertEqual((ROOT/'sdk/java-guest/client/dev/latent/guest/client/Connection.java').read_bytes(),original)

    def test_changed_sdk_or_staged_class_refuses_without_replacing_any_bytes(self):
        original=(ROOT/'sdk/java-guest/client/dev/latent/guest/client/Connection.java').read_bytes()
        for selected in ('sdk','target'):
            with self.subTest(selected=selected),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);sdk=root/'sdk';java=root/'java'
                relative='dev/latent/guest/client/Connection.java'
                source=sdk/'client'/relative;source.parent.mkdir(parents=True);source.write_bytes(original)
                target=java/relative;target.parent.mkdir(parents=True);target.write_bytes(original)
                changed=source if selected=='sdk' else target;changed.write_bytes(original+b'\n// unreviewed\n')
                before=target.read_bytes()
                with self.assertRaisesRegex(ValueError,'phase.*(preimage|source)'):
                    client.stage_phase(sdk,java)
                self.assertEqual(target.read_bytes(),before)

    def test_phase_compiler_selection_requires_explicit_fiber_io_before_creating_outputs(self):
        compiler=object.__new__(Compiler);compiler.run=Mock()
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);output=root/'uncreated'
            for flags in ({'http_client_phase_profile':True},
                    {'http_client_phase_profile':True,'http_client_profile':True,'activation_profile':True},
                    {'http_client_phase_profile':1,'http_client_profile':True,'activation_profile':True,'fiber_io_profile':True}):
                with self.assertRaisesRegex(ValueError,'phase.*profile'):
                    compiler.compile(root/'src',root/'wit','test:app/guest@1.0.0',output,**flags)
                self.assertFalse(output.exists())
            compiler.run.assert_not_called()

    def test_declared_phase_import_selects_only_v7_and_cannot_mix_transaction_authority(self):
        v4=compatibility.DEFAULT_PROFILE
        self.assertEqual(compatibility.declared_host_abi({'imports':[INTERFACE]}),'lsf-host-abi-phase3-v7')
        self.assertEqual(compatibility.declared_host_abi({'imports':['latent:http/phase-timing@0.5.0']}),v4)
        self.assertEqual(compatibility.declared_host_abi({'imports':['latent:http/streaming@0.3.0']}),v4)
        with self.assertRaisesRegex(DevError,'phase.*transaction'):
            compatibility.declared_host_abi({'imports':[INTERFACE,'latent:state/key-value@0.2.0']})
        manifest=compatibility.host_manifest('lsf-host-abi-phase3-v7')
        entry=next(row for row in manifest['interfaces'] if row['interface']==INTERFACE)
        self.assertIs(entry['installed'],False)

    def test_profile_receipt_binds_selected_transformation_and_preserves_old_boundary(self):
        sdk=ROOT/'sdk/java-guest'
        old=json.loads(client.profile(sdk,b'recipe',b'source',b'component'))
        new=json.loads(client.profile(sdk,b'recipe',b'source',b'component',phase_timing=True))
        self.assertEqual(old['profile'],client.PROFILE_ID)
        self.assertEqual(old['responseMetadata']['unavailableMessage'],None)
        self.assertEqual(new['profile'],PHASE)
        self.assertNotEqual(old['runtimeAdapterDigest'],new['runtimeAdapterDigest'])
        self.assertEqual(new['qualification'],'pending')
        self.assertEqual(new['limits'],old['limits'])
        self.assertEqual(new['sourceTransform']['replacementDigest'],
            digest(client.phase_source((sdk/'client/dev/latent/guest/client/Connection.java').read_bytes())))
        for recipe,source,component in ((b'new',b'source',b'component'),(b'recipe',b'new',b'component'),
                (b'recipe',b'source',b'new')):
            self.assertNotEqual(new,json.loads(client.profile(sdk,recipe,source,component,phase_timing=True)))


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'Installed JDK required for host-only adapter reference')
class JavaHttpPhaseHostReference(unittest.TestCase):
    def test_actual_adapter_exception_identity_timeout_selection_reason_bytes_and_old_profile(self):
        import subprocess
        from tools.build_observation import build_environment
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            original=(ROOT/'sdk/java-guest/client/dev/latent/guest/client/Connection.java').read_bytes()
            for variant,expected in (('phase','phase-reference:27'),('legacy','legacy-reference:4')):
                work=root/variant;work.mkdir();sources=work/'sources';sources.mkdir();output=work/'classes';output.mkdir()
                selected={'dev/latent/guest/client/Connection.java':client.phase_source(original) if variant=='phase' else original}
                for name in ('Option','Result','Unsigned64'):
                    relative='dev/latent/guest/'+name+'.java'
                    selected[relative]=(ROOT/'sdk/java-guest/runtime'/relative).read_bytes()
                relative='dev/latent/guest/client/HttpFailure.java'
                selected[relative]=(ROOT/'sdk/java-guest/client'/relative).read_bytes()
                for name in ('Bindings.java','PhaseReference.java'):
                    selected['dev/latent/generated/'+name if name=='Bindings.java' else name]=(
                        ROOT/'tools/fixtures/java-http-phase-reference'/name).read_bytes()
                paths=[]
                for relative,raw in selected.items():
                    path=sources/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);paths.append(str(path))
                environment=build_environment(work)
                commands=([shutil.which('javac'),'-J-Xmx128m','-Xmaxerrs','8','-Xmaxwarns','8','--release','17',
                    '-encoding','UTF-8','-d',str(output),*paths],
                    [shutil.which('java'),'-Xmx64m','-XX:MaxMetaspaceSize=64m','-cp',str(output),'PhaseReference',variant])
                for command in commands:
                    result=subprocess.run(command,cwd=work,env=environment,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
                    self.assertLessEqual(len(result.stdout),262144)
                    self.assertEqual(result.returncode,0,result.stdout.decode('utf-8','replace'))
                self.assertEqual(result.stdout.decode().strip(),expected)
            self.assertEqual((ROOT/'sdk/java-guest/client/dev/latent/guest/client/Connection.java').read_bytes(),original)
