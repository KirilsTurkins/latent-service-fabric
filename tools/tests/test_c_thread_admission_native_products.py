"""Immutable actual f2443+f6252 lineage and failed-producer refusals."""
import copy
import json
from pathlib import Path
import unittest
from tools import c_thread_admission_native_products as native


class CompositeAdmissionProducts(unittest.TestCase):
    def setUp(self):
        self.value=json.loads((Path(__file__).parent/'fixtures/c-thread-admission-f244-records.json').read_bytes())
        self.original=copy.deepcopy(self.value)

    def validate(self):
        expected=self.original
        native.validate_overlay(self.value['overlay'],self.value['snapshot'],expected['snapshot']['native'],
            expected['snapshot']['inheritedNativeSource'],expected['originalSnapshot']['materials'],
            expected['snapshot']['materials'],expected['snapshot']['reviewedNativeChanges'])

    def test_actual_seven_commands_keep_three_new_and_two_original_compiler_identities(self):
        self.validate()
        record,source=native.assembled(self.value['overlay'],self.value['original'],
            self.value['originalSnapshot']['materials'])
        self.assertEqual(set(record['products']),set(native.PRODUCTS))
        self.assertEqual(len(source['materials']),134)
        self.assertEqual(len(self.value['snapshot']['materials']),160)
        self.assertEqual(record['productsBuilt'],list(native.BUILT))
        self.assertEqual(record['productsInherited'],list(native.INHERITED))
        for name in native.PRODUCTS:
            expected=self.value['overlay'] if name in native.BUILT else self.value['original']
            self.assertEqual(record['products'][name],expected['products'][name])
            identity=source['perProductCompilation'][name]
            self.assertEqual(identity['sourceRevision'],native.SOURCE if name in native.BUILT else native.inherited.SOURCE)
            self.assertEqual(identity['nativeSource'],expected['nativeSource'] if name in native.BUILT else expected['source'])
        self.assertNotEqual(source['perProductCompilation']['latent']['nativeSource'],
            source['perProductCompilation']['examples/package']['nativeSource'])
        self.assertFalse(record['signedQualification'])
        self.assertFalse(record['guestComponentsCompiled'])

    def test_actual_failed_missing_reordered_or_unqualified_control_records_cannot_supply_products(self):
        for kind in ('status','controls','signed','guest','backend','command','reordered','missing','bool',
                'duration','infinite','compiler','extra-product','build-identity','inherited-source','stage'):
            self.value=copy.deepcopy(self.original);r=self.value['overlay']
            if kind=='status':r['status']='failed'
            elif kind=='controls':r['focusedControlsPassed']=False
            elif kind=='signed':r['signedQualification']=True
            elif kind=='guest':r['guestCompiled']=True
            elif kind=='backend':r['backendCompiled']=True
            elif kind=='command':r['commands'][-1]['exitCode']=1
            elif kind=='reordered':r['commands'][1:3]=reversed(r['commands'][1:3])
            elif kind=='missing':r['commands'].pop()
            elif kind=='bool':r['commands'][0]['exitCode']=False
            elif kind=='duration':r['commands'][0]['seconds']=1321
            elif kind=='infinite':r['elapsedSeconds']=float('inf')
            elif kind=='compiler':r['compiler']='rustc 1.96.0 (wrong)'
            elif kind=='extra-product':r['products']['examples/package']=r['products']['latent']
            elif kind=='build-identity':r['builtProductIdentities']['latent']['bytes']+=1
            elif kind=='inherited-source':r['inheritedProducts']['sourceRevision']=native.SOURCE
            else:r['commands'][0]['stage']='foreign'
            with self.subTest(kind=kind),self.assertRaises(RuntimeError):self.validate()

    def test_all_six_source_fields_auxiliary_rows_and_five_preimages_are_mandatory(self):
        for kind in ('native','hermetic','scope','implicit','fields','old','aux','producer-helper','preimage','count'):
            self.value=copy.deepcopy(self.original);s=self.value['snapshot']
            if kind=='native':s['native']['sha256']='sha256:'+'0'*64
            elif kind=='hermetic':s['native']['hermetic']=True
            elif kind=='scope':s['native']['scope']='other'
            elif kind=='implicit':s['native']['implicitCompilerInputs']='attested'
            elif kind=='fields':s['native'].pop('scope')
            elif kind=='old':s['inheritedNativeSource']['bytes']+=1
            elif kind in {'aux','producer-helper'}:
                names=set(s['materials'])
                original=set(self.original['originalSnapshot']['materials'])
                chosen=sorted(original if kind=='aux' else names-original)[0]
                s['materials'][chosen]['bytes']+=1
            elif kind=='preimage':s['reviewedNativeChanges'][native.CHANGED[0]]['inherited']['bytes']+=1
            else:s['allOtherNativeFilesByteExact']=3321
            with self.subTest(kind=kind),self.assertRaises(RuntimeError):self.validate()


if __name__=='__main__':unittest.main()
