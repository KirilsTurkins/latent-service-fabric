"""Explicit phase ABI/policy parity; source controls do not qualify transport execution."""
import copy
import hashlib
import json
from pathlib import Path
import re
import struct
import unittest

from jsonschema import Draft202012Validator
from tools.tests import test_capability_policy_schema as policy_controls

ROOT = Path(__file__).resolve().parents[2]
PHASE = 'latent:http/phase-timing@0.4.0'


class HttpPhaseContract(unittest.TestCase):
    def test_explicit_v7_matrix_retains_v6_sources_and_exact_native_identity(self):
        previous = json.loads((ROOT/'wit/host-abi-phase3-v6.json').read_bytes())
        matrix = json.loads((ROOT/'wit/host-abi-phase3-v7.json').read_bytes())
        Draft202012Validator(json.loads((ROOT/'schemas/host-abi-profile.schema.json').read_bytes())).validate(matrix)
        self.assertEqual(matrix['interfaces'][:-1], previous['interfaces'])
        self.assertEqual(matrix['interfaces'][-1]['interface'], PHASE)
        self.assertIs(matrix['interfaces'][-1]['installed'], False)
        self.assertEqual(matrix['id'], 'lsf-host-abi-phase3-v7')
        self.assertEqual(matrix['world'], 'latent:platform/capsule@0.7.0')
        self.assertEqual(matrix['wasmtimeVersion'], previous['wasmtimeVersion'])
        self.assertEqual(matrix['guestGenerator'], previous['guestGenerator'])
        digest = hashlib.sha256(b'lsf-host-abi-profile-v1\0')
        def frame(value):
            digest.update(struct.pack('<Q',len(value)));digest.update(value)
        frame(matrix['id'].encode());digest.update(struct.pack('<Q',len(matrix['interfaces'])))
        for entry in matrix['interfaces']:
            raw=(ROOT/entry['source']).read_bytes()
            self.assertNotIn(b'\r',raw)
            self.assertEqual(entry['sourceSha256'],'sha256:'+hashlib.sha256(raw).hexdigest())
            frame(entry['interface'].encode());frame(entry['package'].encode())
            digest.update(bytes([entry['binding']=='provider',entry['asynchronous']]))
            frame(raw)
        self.assertEqual(matrix['digest'],'sha256:'+digest.hexdigest())
        world=(ROOT/'wit/platform/runtime-phase3-http-phases/world.wit').read_text()
        self.assertEqual(set(re.findall(r'^\s*import ([^;]+);',world,re.M)),
            {entry['interface'] for entry in matrix['interfaces']})

    def test_v7_never_changes_the_frozen_default_or_old_manifest(self):
        self.assertEqual(hashlib.sha256((ROOT/'wit/host-abi-phase3-v6.json').read_bytes()).hexdigest(),
            '64464b6e67fc84d6fa18495bfe8a8c00b08135aa7f8fe49bcb00039809275632')
        core=(ROOT/'crates/latent-core/src/host_profile.rs').read_text()
        self.assertIn('pub const PHASE3_HOST_ABI_CURRENT: HostAbiProfile = PHASE3_HOST_ABI_V5;',core)
        selected=re.search(r'const PHASE3_V7_INTERFACES:.*?= \[(.*?)\n\];',core,re.S).group(1)
        self.assertEqual([int(x) for x in re.findall(r'PHASE3_V6_INTERFACES\[(\d+)\]',selected)],list(range(16)))
        self.assertIn('interface: "'+PHASE+'"',selected)
        self.assertIn('http_phase_timing: false',(ROOT/'crates/latent-wasmtime/src/config.rs').read_text())

    def test_new_schema_rules_preserve_every_original_constraint(self):
        expected={'capability-policy':'61da651075da1823bd7b3e7b5e4d05485e9269a418cc9a1f712fe2f024ea351c',
            'capability-provider-binding':'58095d3571f1c06ce0f3c0d6229e3ea3357ef284e51c0977b7ea077fbe310c51'}
        for name,identity in expected.items():
            value=json.loads((ROOT/f'schemas/{name}.schema.json').read_bytes())
            subject=value['$defs']['rule'] if name=='capability-policy' else value
            subject['properties']['capability']['enum'].remove(PHASE)
            added=[row for row in subject['allOf'] if row['if']['properties']['capability']['const']==PHASE]
            self.assertEqual(len(added),1)
            original=next(row for row in subject['allOf']
                if row['if']['properties']['capability']['const']=='latent:http/streaming@0.3.0')
            same=copy.deepcopy(added[0]);same['if']['properties']['capability']['const']='latent:http/streaming@0.3.0'
            self.assertEqual(same,original)
            subject['allOf'].remove(added[0])
            canonical=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
            self.assertEqual(hashlib.sha256(canonical).hexdigest(),identity)

    def test_explicit_phase_policy_retains_http_resources_limits_and_closed_operations(self):
        validator=policy_controls.CapabilityPolicySchemaTests().validator('capability-policy')
        rule={'id':'phase','effect':'allow','principals':[{'kind':'user','subject':'alice'}],
            'services':['test'],'publications':['publication:sha256:'+'1'*64],
            'capability':PHASE,'operations':['open','finish','read'],
            'resources':{'kind':'http','origins':[{'scheme':'http','host':'127.0.0.1','port':80}],
                'methods':['GET'],'paths':['/'],'pathPrefixes':[]},
            'ceiling':{'operations':3,'inputBytes':0,'outputBytes':128,'wallTimeMillis':100}}
        value={'formatVersion':1,'tenant':'test','rules':[rule]}
        validator.validate(value)
        for changes in ({'operations':['connect']},{'operations':['open','open']},
                {'resources':{'kind':'context'}},{'capability':'latent:http/phase-timing@0.3.0'},
                {'ceiling':{**rule['ceiling'],'outputBytes':67108865}}):
            self.assertFalse(validator.is_valid({**value,'rules':[{**rule,**changes}]}))
