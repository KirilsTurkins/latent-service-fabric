"""Actual source closure and strict catalogue-free TypeScript build boundaries."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import typescript_catalogue_free_build as stage
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import digest, inventory

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptCatalogueFreeTests(unittest.TestCase):
    def test_complete_real_recipe_engine_and_static_python_closure_without_catalogue(self):
        files = stage.source_files(ROOT)
        self.assertTrue(set(stage.RECIPE) <= files.keys())
        self.assertTrue(set(stage.engine_input_paths(stage.IMPORT_PROFILE)) <= files.keys())
        self.assertTrue(stage.EXTRA <= files.keys())
        self.assertNotIn('tools/compatibility_catalogue.py', files)
        self.assertFalse(any(name.startswith(('docs/', 'node_modules/', 'tools/tests/')) for name in files))
        self.assertIn('tools/typescript_guest/fetch.mjs', files)
        self.assertIn('wit/host-abi-phase3-v7.json', files)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'build-source'
            observed = stage.stage(ROOT, root)
            self.assertEqual(stage.verify(root), observed)
            self.assertEqual({name:(root/name).read_bytes() for name in files}, files)
            self.assertFalse((root/'docs').exists())
            self.assertFalse((root/'node_modules').exists())
            self.assertIs(observed['actualComponentQualified'], False)
            self.assertEqual({n for n in files if not n.endswith('.py')}, stage.DATA)

    def test_missing_engine_wit_or_selected_manifest_fails_even_after_rehash(self):
        for name in ('tools/typescript_guest/fetch.mjs', 'wit/platform/clock/package.wit',
                     'wit/platform/activation-runtime/package.wit', 'wit/host-abi-phase3-v7.json',
                     'wit/host-abi-phase3-v5.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)/'source';stage.stage(ROOT,root)
                (root/name).unlink()
                self.rehash(root, exclude={name})
                with self.assertRaises((WorkflowError, FileNotFoundError)):stage.verify(root)

    @staticmethod
    def rehash(root, *, exclude=frozenset(), extra=None):
        path=root/stage.MANIFEST;receipt=json.loads(path.read_bytes())
        names=(set(receipt['files'])-set(exclude)) | set(extra or ())
        files={name:(root/name).read_bytes() for name in names}
        receipt.update(files=json.loads(inventory(files)),fileCount=len(files),
                       sourceBytes=sum(map(len,files.values())),inventoryDigest=digest(inventory(files)))
        path.write_bytes(json.dumps(receipt).encode())

    def test_extra_catalogue_reference_or_python_reader_rejected_even_after_rehash(self):
        for name in ('docs/compatibility-catalogue/v1/catalogue.json', 'tools/optional-reference.json',
                     'tools/compatibility_catalogue.py', 'tools/unselected_reader.py'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)/'source';stage.stage(ROOT,root)
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'{}')
                self.rehash(root,extra={name})
                with self.assertRaises(WorkflowError):stage.verify(root)

    def test_source_path_link_and_original_inventory_mutation_are_refused(self):
        for name in ('../escape.py','tools/../escape.py','/tools/typescript_capsule.py'):
            with self.subTest(name=name),self.assertRaises(WorkflowError):stage.source_file(ROOT,name)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'source';stage.stage(ROOT,root)
            path=root/'tools/typescript_guest/runtime_profile.py'
            os.link(path,Path(temporary)/'second-link')
            with self.assertRaises(WorkflowError):stage.verify(root)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'source';stage.stage(ROOT,root)
            path=root/'tools/typescript_guest/fetch.mjs';path.write_bytes(path.read_bytes()+b'\n// changed\n')
            with self.assertRaises(WorkflowError):stage.verify(root)

    def test_staged_direct_cli_uses_own_closure_and_never_writes_bytecode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'source';stage.stage(ROOT,root)
            result=subprocess.run([sys.executable,str(root/stage.SELF),'--help'],cwd=temporary,
                env=dict(os.environ,PYTHONPATH=''),capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr.decode())
            for option in ('--runtime-engine','--runtime-splicer','--expect-source-digest'):
                self.assertIn(option.encode(),result.stdout)
            self.assertFalse(list(root.rglob('*.pyc')))
            stage.verify(root)


class CatalogueFreeDefaultClientTests(unittest.TestCase):
    def test_new_outside_identity_preserves_unchanged_published_default_calls_and_phase_source(self):
        from tools import qualify_typescript_catalogue_free as q
        from tools.rust_capsule_project import snapshot
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            original=q.fixture.project(root/'original')
            selected=q.project(root/'selected')
            a,b=snapshot(original),snapshot(selected)
            changed={name for name in set(a)|set(b) if a.get(name)!=b.get(name)}
            self.assertEqual(changed,{'src/default-client.ts'})
            self.assertEqual(b['src/default-client.ts'],a['src/default-client.ts'].replace(
                q.fixture.PRIVATE_NAME.encode(),q.PRIVATE_NAME.encode()))
            self.assertEqual(b['src/main.ts'],(ROOT/q.fixture.SOURCE).read_bytes())
            self.assertEqual(q.VECTORS,(('ky-json',0,'ky:'),('wretch-json',1,'wretch:'),('outside-json',2,'outside:')))
            self.assertNotEqual(q.PRIVATE_NAME,q.fixture.PRIVATE_NAME)
            self.assertNotIn(q.PRIVATE_NAME.encode(),(ROOT/'docs/compatibility-catalogue/v1/catalogue.json').read_bytes())

    def test_smoke_configuration_uses_exact_previously_qualified_owner_profile_and_phase_provider(self):
        from tools import qualify_typescript_catalogue_free as q
        from tools import qualify_typescript_published_fetch as published
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);credential=root/'credential';credential.write_bytes(b'Bearer '+b'0'*64)
            (root/'node').mkdir();(root/'signed').mkdir();(root/'signed/policy.json').write_bytes(b'{}')
            path,profile=q.phase.configuration(root/'node',root/'signed',{'destinations':[],'origins':{}},credential)
            config=json.loads(path.read_bytes())
            self.assertEqual(config['providers']['activationRuntime']['limits'],published.CLIENT_OWNER_LIMITS)
            self.assertEqual(profile['name'],published.CLIENT_OWNER_PROFILE)
            self.assertIs(config['providers']['httpStreaming']['phaseTiming'],True)
            bindings=[row for row in config['providers']['bindings'] if row['contract']==q.fixture.HTTP]
            self.assertEqual(len(bindings),1)
            self.assertEqual(config['providers']['httpStreaming']['limits']['maximumChunkBytes'],65536)

    def test_real_three_json_peer_contacts_and_closed_receipt_negatives(self):
        from contextlib import closing
        import socket,time
        from urllib.parse import urlsplit
        from tools import qualify_typescript_catalogue_free as q
        authorization=b'Bearer '+b'0'*64
        with closing(q.fixture.PhasePeer(authorization,maximum_seconds=10)) as peer:
            for _ in range(3):
                target=urlsplit(peer.url('domain-json'))
                with socket.create_connection((target.hostname,target.port),timeout=2) as client:
                    client.sendall(b'GET '+target.path.encode()+b' HTTP/1.1\r\nHost: '+target.netloc.encode()
                        +b'\r\nAuthorization: '+authorization+b'\r\n\r\n')
                    client.setblocking(False);raw=bytearray();deadline=time.monotonic()+3
                    while True:
                        self.assertLess(time.monotonic(),deadline);peer.poll(.001)
                        try:part=client.recv(8192)
                        except BlockingIOError:continue
                        if not part:break
                        raw.extend(part);self.assertLess(len(raw),8192)
                    self.assertEqual(json.loads(raw.split(b'\r\n\r\n')[1]),q.DOMAIN)
            peer.close();value=peer.observation();q.peer_evidence(value)
            for kind in ('extra','auth','cookie','role','open','mutated'):
                changed=copy.deepcopy(value)
                if kind=='extra':changed['acceptedConnections']+=1
                elif kind=='auth':changed['requests'][0]['authorizationPresent']=False
                elif kind=='cookie':changed['requests'][0]['cookiePresent']=True
                elif kind=='role':changed['requests'][0]['role']='secondary'
                elif kind=='open':changed['state']='ready'
                else:changed['committedMutations']=1
                with self.subTest(kind=kind),self.assertRaises((ValueError,WorkflowError)):q.peer_evidence(changed)


if __name__=='__main__':unittest.main()
