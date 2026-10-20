"""Fixed failed-reader build reuse remains source-bound and never mints a pass."""
import copy
import json
from unittest.mock import patch
import unittest

from tools import go_http_managed_component as component
from tools.go_guest.activation import MANAGED_PROFILE
from tools.phase2_operator_process import WorkflowError


def fixture():
    raw=b'owned synthetic data-only input';identity=component.identity(raw)
    row={'digest':identity['sha256'],'size':identity['bytes']}
    original={'status':'failed','stage':'signed-same-cell-two-tenant-ordinary-http','errorCategory':'RuntimeError',
        'runtimeProfile':MANAGED_PROFILE,'commands':[{'stage':'capture','exitCode':0},{'stage':'compile','exitCode':0}],
        'sourceMaterials':{'owned.py':identity},'build':{'component.wasm':identity}}
    names=['component-build','component-validate','package','inspect']+['reference-'+str(i) for i in range(18)]
    observed={'parameters':{'runtime':MANAGED_PROFILE},'componentDigest':identity['sha256']}
    inputs={f'vendor/lsf/sdk/go-guest/source-{i}.go':row for i in range(60)}
    staged={'files':{f'tools/compiler-{i}.py':row for i in range(91)},'optionalReferenceDataPresent':False}
    original['catalogueFreeCompiler']=staged
    encode=lambda value:(json.dumps(value)+'\n').encode()
    observed_raw=encode(observed);inputs_raw=encode(inputs)
    marker={'packageAssembled':True,'observationDigest':component.identity(observed_raw)['sha256'],
        'sourceDigest':component.identity(inputs_raw)['sha256'],'componentDigest':identity['sha256'],
        'commands':[{'stage':name,'exitCode':0} for name in names]}
    records={'FAILED.json':encode(original),'build/BUILD-COMPLETE.json':encode(marker),
        'build/build-observation.json':observed_raw,'build/source-inputs.json':inputs_raw,
        'build/component.wasm':raw,'catalogue-free-compiler/BUILD-SOURCE-INVENTORY.json':encode(staged)}
    return {component.PREFIX+name:value for name,value in records.items()},raw,identity


class ManagedGoBuildReuseControls(unittest.TestCase):
    def test_unknown_archive_refuses_before_zip_parsing_or_output(self):
        for value in (b'',b'not the fixed artifact','not bytes'):
            with self.subTest(value=value),patch.object(component.zipfile,'ZipFile',side_effect=AssertionError('no parse')):
                with self.assertRaises(WorkflowError):component.preflight(value)

    def test_original_failed_reader_can_supply_only_successful_exact_build_and_current_recipe_sdk(self):
        files,raw,identity=fixture()
        with patch.object(component.subprocess,'check_output',return_value=raw),patch.object(component,'file_identity',return_value=identity):
            result=component.validate_inputs(files)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['runtimeProfile'],MANAGED_PROFILE)
        self.assertEqual(len(result['catalogueFreeCompiler']['files']),91)

    def test_compile_failure_old_profile_relabel_and_original_source_component_or_current_sdk_drift_refuse(self):
        files,raw,identity=fixture()
        mutations=[]
        for name,modify in (
                ('FAILED.json',lambda value:value.update(status='passed')),
                ('FAILED.json',lambda value:value['commands'][1].update(exitCode=1)),
                ('build/build-observation.json',lambda value:value['parameters'].update(runtime='go-component-activation-v4')),
                ('build/BUILD-COMPLETE.json',lambda value:value['commands'][0].update(exitCode=1)),
                ('catalogue-free-compiler/BUILD-SOURCE-INVENTORY.json',lambda value:value.update(optionalReferenceDataPresent=True))):
            changed=copy.deepcopy(files);key=component.PREFIX+name;value=json.loads(changed[key]);modify(value);changed[key]=json.dumps(value).encode();mutations.append(changed)
        for changed in mutations:
            with self.subTest(changed=changed.keys()),patch.object(component.subprocess,'check_output',return_value=raw),patch.object(component,'file_identity',return_value=identity):
                with self.assertRaises(WorkflowError):component.validate_inputs(changed)
        with patch.object(component.subprocess,'check_output',return_value=b'changed'),patch.object(component,'file_identity',return_value=identity):
            with self.assertRaises(WorkflowError):component.validate_inputs(files)
        with patch.object(component.subprocess,'check_output',return_value=raw),patch.object(component,'file_identity',return_value={**identity,'bytes':1}):
            with self.assertRaises(WorkflowError):component.validate_inputs(files)


if __name__=='__main__':unittest.main()
