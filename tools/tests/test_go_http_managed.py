"""Explicit managed HTTP selection; source controls are not signed qualification."""
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from tools import go_http_tenant_fixture as fixture, go_http_tenant_node as node
from tools.go_guest.activation import INITIALIZER_PROFILE, MANAGED_PROFILE
from tools.go_standard_http_node import configuration
from tools.phase2_operator_process import WorkflowError
from tools.qualify_go_http_tenants import qualify
from tools.rust_capsule_project import ROOT


class ManagedGoHttpSourceControls(unittest.TestCase):
    def test_maintenance_slots_plus_original_application_headroom_are_all_charged(self):
        source = (ROOT/'sdk/go-guest/runtime/managed_idle.go.in').read_text()
        count = int(re.search(r'const lsfManagedCapacity = ([0-9]+)',source)[1])
        self.assertEqual(count,8)
        self.assertIn('lsfRegister(1, 0, 0, 0, unsafe.Pointer(&result))',source)
        original = node.limits(INITIALIZER_PROFILE)
        managed = node.limits(MANAGED_PROFILE)
        self.assertEqual(original,node.RUNTIME_LIMITS)
        self.assertEqual(managed['tasks'],original['tasks']+count)
        self.assertEqual(managed['tasks'],16)
        self.assertEqual({k:v for k,v in original.items() if k != 'tasks'},
            {k:v for k,v in managed.items() if k != 'tasks'})

    def test_unknown_profile_and_nonboolean_programme_selector_fail_before_capture(self):
        for value in ('go-component-activation-v6','go-component-async-v1','',True,1,None):
            with self.subTest(value=value),patch.object(fixture,'capture_source',side_effect=AssertionError('must not capture')):
                with self.assertRaises(ValueError):fixture.project(Path('unused'),Path('unused'),'unused',runtime_profile=value)
                with self.assertRaises(WorkflowError):node.limits(value)
        for value in (1,None,'true'):
            with self.assertRaises(WorkflowError):qualify(Path('unused'),Path('unused'),managed_runtime=value)

    def test_both_profiles_preserve_identical_client_private_worker_sdk_wit_and_budget_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);apps = []
            for name,profile in (('old',INITIALIZER_PROFILE),('managed',MANAGED_PROFILE)):
                app,library = fixture.project(root/name,root/(name+'-private'),
                    'outside.example.test/http-library/managed-control',runtime_profile=profile)
                apps.append(({p.relative_to(app).as_posix():p.read_bytes() for p in app.rglob('*') if p.is_file()},
                    {p.relative_to(library).as_posix():p.read_bytes() for p in library.rglob('*') if p.is_file()}))
            (old,old_private),(managed,managed_private) = apps
            first = json.loads(old.pop('capsule-project.json'));second = json.loads(managed.pop('capsule-project.json'))
            self.assertEqual(first.pop('runtimeProfile'),INITIALIZER_PROFILE)
            self.assertEqual(second.pop('runtimeProfile'),MANAGED_PROFILE)
            self.assertEqual(first,second)
            main = managed['src/main.go']
            self.assertEqual(main.count(fixture.MANAGED_DEADLINE),1)
            managed['src/main.go'] = main.replace(fixture.MANAGED_DEADLINE,fixture.DEADLINE)
            # The normal capture lock binds this owned source derivation.
            before_lock=json.loads(old.pop('sdk-lock.json'));after_lock=json.loads(managed.pop('sdk-lock.json'))
            self.assertNotEqual(before_lock['template']['sourceDigest'],after_lock['template']['sourceDigest'])
            after_lock['template']['sourceDigest']=before_lock['template']['sourceDigest']
            self.assertEqual(before_lock,after_lock)
            self.assertEqual(old,managed)
            self.assertEqual(old_private,managed_private)

    def test_default_node_stays_v4_and_managed_selection_changes_only_original_task_capacity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);(root/'node').mkdir();(root/'releases').mkdir()
            (root/'releases/policy.json').write_bytes(b'{}')
            origins = {tenant:{'destinations':[{'origin':{'scheme':'http','host':'127.0.0.1','port':19001+i}}]}
                for i,tenant in enumerate(node.TENANTS)}
            credentials = {tenant:root/tenant/'authorization' for tenant in node.TENANTS}
            before = json.loads(configuration(root/'node',root/'releases',origins['examples'],credentials['examples']).read_bytes())
            default = node.settings(before,origins,credentials)
            explicit = node.settings(before,origins,credentials,runtime_profile=INITIALIZER_PROFILE)
            managed = node.settings(before,origins,credentials,runtime_profile=MANAGED_PROFILE)
            self.assertEqual(default,explicit)
            adjusted = copy.deepcopy(managed)
            self.assertEqual(adjusted['providers']['activationRuntime']['limits']['tasks'],16)
            adjusted['providers']['activationRuntime']['limits']['tasks'] = 8
            self.assertEqual(adjusted,default)
            self.assertEqual(before['providers']['activationRuntime']['limits']['tasks'],8)

    def test_old_component_cannot_be_relabelled_managed_at_signed_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);artifact = root/'build';artifact.mkdir()
            (artifact/'build-observation.json').write_bytes(json.dumps({'parameters':{'runtime':INITIALIZER_PROFILE}}).encode())
            with self.assertRaises(WorkflowError):
                node.run(artifact,{},root/'output',0,runtime_profile=MANAGED_PROFILE)
            self.assertFalse((root/'output').exists())


if __name__ == '__main__':unittest.main()
