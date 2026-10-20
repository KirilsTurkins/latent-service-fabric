"""Fresh resource greeting on the authenticated historical94d Go normal bundle."""
from __future__ import annotations
import argparse
import copy
from pathlib import Path
import sys

if __package__ in {None,''}:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from tools import qualify_go_node_stop as producer
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_embedded_resources import HELPERS, campaign
from tools.qualify_sdk_scratch import _prepared_with_inputs, current_inputs
from tools.rust_capsule_project import ROOT, read_json, write_json

HELPER = 'run_rust_capsule_workflow.py'
RESOURCE_HELPER = {'sha256':'sha256:7c32777ab230a9c1da5a8ad99b1edce1fd2518fad81525c52376a66ec27b67d7','bytes':34233}
ORIGINAL_RUNTIME = {'sha256':'sha256:d1d1507dc96ad0477edb06ec12af301e44c6a63d28abf9cb3c6e839d65b35738',
    'files':3299,'bytes':25834970,'scope':'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
    'hermetic':False,'implicitCompilerInputs':'not-attested'}
# Git94d..6b296e changes only this one native-scope TEST file. No native
# implementation is relabelled as compiled from the present checkout.
STARTUP_TEST_RUNTIME = {**ORIGINAL_RUNTIME,
    'sha256':'sha256:410f3bea073b8a650b7539c28e3ec1ff2a766b6c2e1ecdd43d41cad459f76c4f','bytes':25835711}
STARTUP_TEST = 'apps/latentd/tests/standalone_node/startup.rs'
MATERIALS = (*HELPERS,'tools/replay_go_embedded_resources.py','tools/qualify_go_node_stop.py',
    'tools/qualify_sdk_scratch.py',STARTUP_TEST)


def compatible_source(original,current):
    require(type(original) is dict and type(current) is dict and original.keys() == current.keys()
        and original['runtime'] == ORIGINAL_RUNTIME and current['runtime'] == STARTUP_TEST_RUNTIME
        and original['helpers'][HELPER] == producer.ORIGINAL_HELPER
        and current['helpers'][HELPER] == RESOURCE_HELPER, 'embedded-Go-closed-source-preimages')
    normalized = copy.deepcopy(current)
    normalized['runtime'] = ORIGINAL_RUNTIME
    normalized['helpers'][HELPER] = producer.ORIGINAL_HELPER
    require(normalized == original, 'embedded-Go-no-native-SDK-WIT-used-helper-drift')
    return {'compiledSource':producer.PRODUCER_HEAD,'compiledRuntime':ORIGINAL_RUNTIME,
        'currentRuntime':STARTUP_TEST_RUNTIME,'nativeImplementationChanged':False,
        'nativeTestOnlyChange':STARTUP_TEST,'unusedNormalWorkflowHelper':RESOURCE_HELPER,
        'currentNativeCompilationClaimed':False,'normalReceiptRelabelled':False}


def selected(normal):
    original = read_json(normal/'source-inputs.json',16*1024**2)
    compatibility = compatible_source(original,current_inputs('go'))
    binaries,companions,ancestry = _prepared_with_inputs(normal,'go',original)
    node = read_json(normal/'node/workflow.json',1024**2)
    require(len(node['invocations']) == 27, 'embedded-Go-original27-required')
    ancestry = {**ancestry,'compatibility':compatibility,
        'normalActivations':[row['activation'] for row in node['invocations']],
        'physicalSamples':len(node['samples']),'idleSamples':len(node['providerIdle'])}
    return binaries,companions,ancestry


def replay(normal,metadata,output):
    origin = producer.validate_producer(read_json(metadata,1024**2))
    before = {name:file_identity(ROOT/name) for name in dict.fromkeys(MATERIALS)}
    binaries,companions,ancestry = selected(normal)
    for path in binaries.values(): path.chmod(0o700)
    result = campaign('go',output,binaries,companions,{**ancestry,'producer':origin})
    require(selected(normal)[2] == ancestry
        and before == {name:file_identity(ROOT/name) for name in before}, 'embedded-Go-final-material-drift')
    write_json(output/'replay.json',{'status':result['status'],'producer':origin,'inherited':ancestry,
        'materials':before,'qualification':file_identity(output/'qualified.json'),
        'nativeHostRebuilt':False,'normalReceiptFabricated':False,'freshComponents':1,
        'companionComponentsRecompiled':False})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-producer',action='store_true')
    for name in ('normal-qualification','producer-receipt','output'):
        parser.add_argument('--'+name,type=Path,required=name=='output')
    args = parser.parse_args()
    if args.record_producer:
        require(args.normal_qualification is None and args.producer_receipt is None,
            'embedded-Go-producer-metadata-only')
        producer.record_producer(args.output)
    else:
        require(args.normal_qualification is not None and args.producer_receipt is not None,
            'embedded-Go-explicit-original-normal-required')
        print(replay(args.normal_qualification.resolve(strict=True),args.producer_receipt,
            args.output.absolute())['status'])
