"""Fresh resource greeting on the authenticated historical94d Go normal bundle."""
from __future__ import annotations
import argparse
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

HELPER = producer.WORKFLOW_HELPER
RESOURCE_HELPER = producer.RESOURCE_ONLY_HELPER
ORIGINAL_RUNTIME = producer.ORIGINAL_RUNTIME
STARTUP_TEST_RUNTIME = producer.TEST_ONLY_RUNTIME
STARTUP_TEST = producer.STARTUP_TEST['path']
MATERIALS = (*HELPERS,'tools/replay_go_embedded_resources.py','tools/qualify_go_node_stop.py',
    'tools/qualify_sdk_scratch.py',STARTUP_TEST)


def compatible_source(original,current):
    compatibility = producer.compatible_normal_source(original,current)
    require(current['helpers'][HELPER] == RESOURCE_HELPER, 'embedded-Go-exact-resource-selector-required')
    return {**compatibility,'compiledSource':producer.PRODUCER_HEAD,
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
