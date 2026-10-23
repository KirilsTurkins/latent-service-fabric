"""Four real module/helper failure boundaries for a born private current Task.

Unselected source prototype. Ordinary callers retain whole original bodies;
foreign preprepared-info cleanup remains explicitly unqualified.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_observer as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_worker_operations.json'
FIXTURE_SHA = '09a942e111b2aa05c7d993cf39fd64f9baf3e5f21a83e667e9fee1ffea50b6f7'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 32 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-worker-operations-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-worker-operations-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 7 and len(value['sections']) == 9 and len(value['parentDerived']) == 1 and
        all(value[key] is False for key in ('operationExecuted', 'factoryCallsFullWorkerCreate',
            'pendingConsumerCallsFullClone', 'taskCreated', 'executorReady', 'foreignInfoCleanupQualified',
            'publishedWorkerLsmQualified', 'observerClosure', 'bootstrapQualified',
            'fullConstructorClosure', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-worker-operations-source-origin')
    return value


def definition(name):
    return preimages()['sections'][name]['text']


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-worker-operations-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-worker-operations-whole-source')
        if 'gitBlob' in expected:
            require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() ==
                expected['gitBlob'], 'cleanup-worker-operations-upstream-git-blob')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-worker-operations-definition-preimage')
    require(inputs['selected.config'].decode().splitlines().count('CONFIG_MODULES=y') == 1,
        'cleanup-worker-operations-actual-modules-profile')


def guard_integer():
    return ('#ifdef CONFIG_LSF_STREAM_FACTORY\n\t{\n'
        '\t\tint owned = lsf_factory_cleanup_worker_operation_current();\n'
        '\t\tif (owned)\n\t\t\treturn owned < 0 ? -EIO : -EOPNOTSUPP;\n'
        '\t}\n#endif\n')


def request_module():
    return replace(definition('request_module'), '\tint ret, dup_ret;\n',
        '\tint ret, dup_ret;\n' + guard_integer())


def helper():
    return replace(definition('helper'),
        '\tgfp_t gfp_mask = (wait == UMH_NO_WAIT) ? GFP_ATOMIC : GFP_KERNEL;\n',
        '\tgfp_t gfp_mask = (wait == UMH_NO_WAIT) ? GFP_ATOMIC : GFP_KERNEL;\n' + guard_integer())


def setup():
    return replace(definition('setup'), '\tstruct subprocess_info *sub_info;\n',
        '\tstruct subprocess_info *sub_info;\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t/* This real pointer API accepts NULL failure, never ERR_PTR. */\n'
        '\tif (lsf_factory_cleanup_worker_operation_current())\n\t\treturn NULL;\n#endif\n')


def execute():
    return replace(definition('exec'), '\tint retval = 0;\n',
        '\tint retval = 0;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n\t{\n'
        '\t\tint owned = lsf_factory_cleanup_worker_operation_current();\n'
        '\t\tif (owned) {\n'
        '\t\t\t/* Original consuming-error contract: cleanup exactly once,\n'
        '\t\t\t * before helper_lock, queueing or new helper Task. */\n'
        '\t\t\tcall_usermodehelper_freeinfo(sub_info);\n'
        '\t\t\treturn owned < 0 ? -EIO : -EOPNOTSUPP;\n'
        '\t\t}\n\t}\n#endif\n')


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-worker-operations-parent-preimage')
    outputs = dict(outputs)
    for name, raw in inputs.items():
        if name != 'selected.config' and name not in outputs:
            outputs[name] = raw
    include = '#include <net/lsf_stream_cleanup_worker_operations.h>\n'
    name = 'kernel/module/kmod.c'
    require(outputs[name] == inputs[name], 'cleanup-worker-operations-module-whole-original')
    text = replace(outputs[name].decode(), definition('request_module'), request_module())
    outputs[name] = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n' + include + '#endif\n' + text).encode()
    name = 'kernel/umh.c'
    require(outputs[name] == inputs[name], 'cleanup-worker-operations-helper-whole-original')
    text = outputs[name].decode()
    for key, new in [('helper', helper()), ('setup', setup()), ('exec', execute())]:
        text = replace(text, definition(key), new)
    outputs[name] = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n' + include + '#endif\n' + text).encode()
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <net/lsf_stream_cleanup_observer.h>\n',
        '#include <net/lsf_stream_cleanup_observer.h>\n' + include)
    outputs[name] = replace(text, '#include "factory-cleanup-observer.c"\n',
        '#include "factory-cleanup-observer.c"\n#include "factory-cleanup-worker-operations.c"\n').encode()
    outputs['include/net/lsf_stream_cleanup_worker_operations.h'] = (
        OWNED/'cleanup-worker-operations-private.h').read_bytes()
    outputs['net/factory-cleanup-worker-operations.c'] = (OWNED/'factory-cleanup-worker-operations.c').read_bytes()
    return outputs
