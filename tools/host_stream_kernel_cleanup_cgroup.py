"""Actual selected cgroup callback inventory and pinned root-css constructor.

All original callback loops, accounting, cancellation and post-fork paths
remain. No runtime/bootstrap or observer qualification follows from this map.
"""
import hashlib
import json
from pathlib import Path
import re
from tools import host_stream_kernel_cleanup_io as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_cgroup.json'
FIXTURE_SHA = '6ef07c08b42688e585b8bebf2175eb12f2ab66ebb15a8d630c174346f26fc0a8'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 64 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-cgroup-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-cgroup-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 18 and len(value['registrations']) == 14 and
        len(value['sections']) == 13 and len(value['parentDerived']) == 1 and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'actualCgroupExecution', 'bootstrapQualified', 'observerClosure',
            'fullConstructorClosure', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-cgroup-source-origin')
    return value


def definition(name):
    return preimages()['sections'][name]['text']


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-cgroup-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-cgroup-whole-source')
        if 'gitBlob' in expected:
            require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() ==
                expected['gitBlob'], 'cleanup-cgroup-upstream-git-blob')
    for expected in list(value['sections'].values()) + list(value['registrations'].values()):
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-cgroup-definition-preimage')
    config = inputs['selected.config'].decode()
    for expected in value['registrations'].values():
        require(expected['selectedConfig'] + '=y\n' in config, 'cleanup-cgroup-actual-subsystem-selection')
        actual = {name: target for name, target in re.findall(r'\.(\w+)\s*=\s*([A-Za-z0-9_]+)', expected['text'])
            if name in ('can_fork', 'cancel_fork', 'fork', 'exit', 'release', 'free')}
        require(actual == expected['taskHooks'], 'cleanup-cgroup-actual-registered-task-hooks')


def private_cgroup():
    text = replace(definition('cgroup_can_fork'),
        'int cgroup_can_fork(struct task_struct *child, struct kernel_clone_args *kargs)\n',
        'int lsf_prepaid_cleanup_cgroup_can_fork(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *child, struct kernel_clone_args *kargs)\n')
    text = replace(text, '\tint i, j, ret;\n', '\tint i, j, ret;\n\n'
        '\tif (!kargs || kargs->flags != LSF_CLEANUP_CLONE_FLAGS || kargs->cgrp || kargs->cset ||\n'
        '\t    !lsf_factory_cleanup_constructor_current(source, child))\n\t\treturn -EOPNOTSUPP;\n')
    text = replace(text,
        '\tret = cgroup_css_set_fork(kargs);\n\tif (ret)\n\t\treturn ret;\n',
        '\tret = cgroup_css_set_fork(kargs);\n\tif (ret)\n\t\treturn ret;\n\n'
        '\t/* Inspect the actual pinned cset under the original fork/migration\n'
        '\t * serialization. Never infer root membership from a task name. */\n'
        '\tif (kargs->cset != &init_css_set) {\n'
        '\t\tcgroup_css_set_put_fork(kargs);\n\t\treturn -EOPNOTSUPP;\n\t}\n')
    return text


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'], 'cleanup-cgroup-parent-preimage')
    outputs = dict(outputs)
    include = '#include <net/lsf_stream_cleanup_cgroup.h>\n'
    name = 'kernel/lsf-cleanup-constructor.c'
    text = replace(outputs[name].decode(), '\tretval = cgroup_can_fork(p, args);\n',
        '#ifdef CONFIG_CGROUPS\n\tretval = lsf_prepaid_cleanup_cgroup_can_fork(source, p, args);\n'
        '#else\n\tretval = cgroup_can_fork(p, args);\n#endif\n')
    outputs[name] = (include + text).encode()
    name = 'kernel/cgroup/cgroup.c'
    # This whole ordinary TU is unchanged; private selection is appended.
    require(name not in outputs or outputs[name] == inputs[name], 'cleanup-cgroup-ordinary-whole-preimage')
    outputs[name] = (include.encode() + inputs[name] + b'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        b'#include "lsf-cleanup-cgroup.c"\n#endif\n')
    outputs['kernel/cgroup/lsf-cleanup-cgroup.c'] = private_cgroup().encode()
    outputs['include/net/lsf_stream_cleanup_cgroup.h'] = (OWNED / 'cleanup-cgroup-private.h').read_bytes()
    return outputs
