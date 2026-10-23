"""Actual finite FD bootstrap and authenticated full provider creator routing.

Committed normal source remains unselected. Isolated qualification selection
is an explicit exact-body source projection, never a runtime/operator toggle.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_constructor_wait as prior
from tools.host_stream_kernel_device_security import function

OWNED = prior.OWNED
require, replace = prior.require, prior.replace
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_cleanup_native.json'
FIXTURE_SHA = '0482e88f5a600443744c7b4dba159143bead9fc2548fc3066ab8a045eeb768fb'
QUALIFICATION_OFF = '''static inline int lsf_factory_constructor_qualification(void)
{
    return 0;
}
'''
QUALIFICATION_ON = QUALIFICATION_OFF.replace('return 0;', 'return 1;')


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 8192 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-native-fixed-parent')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-native-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        not value['source'] and len(value['parentDerived']) == 5 and
        all(value[key] is False for key in ('actualLinuxExecution', 'consumerSelected',
            'completeAllocationClosure', 'productionInstallation')),
        'cleanup-native-unqualified-source')
    return value


def transform(outputs, inputs):
    require(not inputs, 'cleanup-native-no-new-upstream')
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-native-parent-preimage')
    outputs = dict(outputs)
    name = 'net/factory-private.h'
    text = outputs[name].decode()
    require(function(text, 'static inline const struct lsf_factory_consumer *lsf_factory_selected_consumer(')
        .endswith('    return NULL;\n}\n'), 'cleanup-native-production-consumer-still-null')
    outputs[name] = replace(text, '#endif\n', QUALIFICATION_OFF+'#endif\n').encode()
    name = 'net/factory-device.c'
    outputs[name] = replace(outputs[name].decode(), '    unsigned int pci_attempted, constructor_active;\n',
        '    unsigned int pci_attempted, constructor_active;\n'
        '    u64 bootstrap_expires_ns;\n'
        '    unsigned int bootstrap_state, bootstrap_busy, bootstrap_error;\n').encode()
    name = 'include/net/lsf_stream_cleanup_provider_executor.h'
    outputs[name] = replace(outputs[name].decode(), '#endif\n',
        'int lsf_factory_cleanup_provider_creator_request(const void *, unsigned long,\n'
        '    struct lsf_cleanup_task_source *);\n#endif\n').encode()
    name = 'kernel/kthread.c'
    text = replace(outputs[name].decode(),
        'static void lsf_cleanup_create_kthread(struct lsf_cleanup_request *);\n',
        'static void lsf_cleanup_create_kthread(struct lsf_cleanup_request *);\n'
        'static void lsf_cleanup_dispatch_kthread(struct lsf_cleanup_request *);\n')
    text = replace(text, '\t\t\t\tlsf_cleanup_create_kthread(owned);\n',
        '\t\t\t\tlsf_cleanup_dispatch_kthread(owned);\n')
    # The maintained full definition and legacy refusal remain byte-exact.
    # Only this real pending consumer dispatches an immutable provider birth.
    text = replace(text, '#include "lsf-cleanup-clone-args.c"\n',
        '#include "lsf-cleanup-clone-args.c"\n'
        'static void lsf_cleanup_dispatch_kthread(struct lsf_cleanup_request *owned)\n'
        '{\n    struct lsf_cleanup_task_source source;\n'
        '    if (lsf_factory_cleanup_provider_creator_request(owned, sizeof(*owned), &source))\n'
        '        lsf_cleanup_create_kthread_full(owned);\n'
        '    else\n        lsf_cleanup_create_kthread(owned);\n}\n')
    outputs[name] = text.encode()
    name = 'net/factory.c'
    text = replace(outputs[name].decode(), '#include <linux/fs.h>\n',
        '#include <linux/fs.h>\n#include <linux/init.h>\n#include <linux/timekeeping.h>\n')
    old = function(text, 'static int lsf_factory_open(')
    new = replace(old, '    unsigned int cleanup_close = 0;\n', '')
    new = replace(new, '    if (!lsf_factory_selected_consumer())\n',
        '    if (!lsf_factory_selected_consumer() && !lsf_factory_constructor_qualification())\n')
    begin = new.index('    /* opened and original mm/tgid/cred/net borrows are published.')
    end = new.index('    file->private_data = &factory;\n', begin)
    new = new[:begin]+new[end:]
    new = replace(new, '    if (cleanup_close)\n        lsf_prepaid_cleanup_worker_destroy_full();\n', '')
    text = replace(text, old, new)
    text = replace(text, 'static ssize_t lsf_factory_write(',
        '#include "factory-cleanup-native-bootstrap.c"\n\nstatic ssize_t lsf_factory_write(')
    old = function(text, 'static ssize_t lsf_factory_write(')
    new = replace(old, '    if (!consumer)\n',
        '    if (count == sizeof(struct lsf_factory_bootstrap_request))\n'
        '        return lsf_factory_bootstrap_write(file, buffer, count);\n'
        '    if (!consumer)\n')
    new = replace(new, '    error = lsf_factory_device_firmware_retirement_error();\n',
        '    if (!factory.device || factory.device->bootstrap_state != LSF_FACTORY_BOOTSTRAP_READY) {\n'
        '        error = -EAGAIN;\n        goto out;\n    }\n'
        '    error = lsf_factory_device_firmware_retirement_error();\n')
    text = replace(text, old, new)
    old = function(text, 'static ssize_t lsf_factory_read(')
    new = replace(old, '    mutex_lock(&factory_lock);\n',
        '    if (count == sizeof(struct lsf_factory_bootstrap_status))\n'
        '        return lsf_factory_bootstrap_read(file, buffer, count);\n'
        '    if (count == sizeof(struct lsf_factory_bootstrap_diagnostic))\n'
        '        return lsf_factory_bootstrap_diagnostic_read(file, buffer, count);\n'
        '    mutex_lock(&factory_lock);\n')
    new = replace(new, '    else if (lsf_factory_device_firmware_retirement_error())\n',
        '    else if (!factory.device || factory.device->bootstrap_state != LSF_FACTORY_BOOTSTRAP_READY)\n'
        '        error = -EAGAIN;\n'
        '    else if (lsf_factory_device_firmware_retirement_error())\n')
    text = replace(text, old, new)
    old = function(text, 'static int lsf_factory_release(')
    new = replace(old, '    lsf_cleanup_admission_close();\n',
        '    if (file->private_data == &factory && factory.device)\n'
        '        factory.device->bootstrap_state = LSF_FACTORY_BOOTSTRAP_CLOSED;\n'
        '    lsf_cleanup_admission_close();\n')
    text = replace(text, old, new)
    old = function(text, 'int lsf_factory_register(')
    new = replace(old, '    if (!lsf_factory_selected_consumer())\n',
        '    if (!lsf_factory_selected_consumer() && !lsf_factory_constructor_qualification())\n')
    outputs[name] = replace(text, old, new).encode()
    outputs['net/factory-cleanup-native-bootstrap.c'] = (OWNED/'factory-cleanup-native-bootstrap.c').read_bytes()
    return outputs


def qualification_projection(outputs):
    """The image owner records this exact sole output difference and identities."""
    name = 'net/factory-private.h'
    require(function(outputs[name].decode(),
        'static inline const struct lsf_factory_consumer *lsf_factory_selected_consumer(')
        .endswith('    return NULL;\n}\n'), 'cleanup-native-projection-no-socket-consumer')
    result = dict(outputs)
    result[name] = replace(outputs[name].decode(), QUALIFICATION_OFF, QUALIFICATION_ON).encode()
    require([key for key in result if result[key] != outputs[key]] == [name],
        'cleanup-native-only-one-qualification-body')
    return result
