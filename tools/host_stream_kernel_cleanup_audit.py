"""Real enabled audit task filtering/context/key births, source only.

The existing real audit switch, filters, audit_log_lost and every destructor
remain. Runtime audit-context transition/work graphs still need qualification.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_perf as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_cleanup_audit.json'
FIXTURE_SHA = 'f10052fc5d4ae907648ba145e42d86261d4427b4b140846d953e734ab6ef032b'
require = prior.require
replace = prior.replace


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 64 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-audit-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-audit-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        value['archiveSha256'] == prior.preimages()['archiveSha256'] and
        len(value['source']) == 1 and len(value['sections']) == 9 and len(value['parentDerived']) == 5 and
        all(value[name] is False for name in ('taskCreated', 'executorReady',
            'runtimeAuditContextTransitionsQualified', 'bootstrapQualified',
            'fullConstructorClosure', 'completeAllocationClosure', 'productionInstallation')),
        'cleanup-audit-source-origin')
    return value


def definition(name):
    return preimages()['sections'][name]['text']


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-audit-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'], 'cleanup-audit-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-audit-definition-preimage')


GEOMETRY = '''int lsf_prepaid_cleanup_audit_geometry(unsigned int kind, unsigned long *bytes,
    unsigned long *alignment)
{
    if (!bytes || !alignment)
        return -EINVAL;
    if (kind == LSF_CLEANUP_AUDIT_CONTEXT) {
        *bytes = sizeof(struct audit_context);
        *alignment = __alignof__(struct audit_context);
    } else if (kind == LSF_CLEANUP_AUDIT_KEY) {
        *bytes = AUDIT_MAX_KEY_LEN + 1u;
        *alignment = ARCH_KMALLOC_MINALIGN;
    } else {
        return -EOPNOTSUPP;
    }
    return 0;
}

static char *lsf_cleanup_audit_key(struct lsf_cleanup_task_source source,
    struct task_struct *task, const char *key)
{
    char *copy;
    size_t bytes;
    if (!key)
        return NULL; /* Exact original kstrdup(NULL) semantics. */
    bytes = strnlen(key, AUDIT_MAX_KEY_LEN + 1u);
    if (bytes > AUDIT_MAX_KEY_LEN) {
        lsf_factory_cleanup_stack_poison(source);
        return NULL;
    }
    copy = lsf_factory_cleanup_child_new(source, task, LSF_CLEANUP_AUDIT_KEY, task);
    if (copy)
        memcpy(copy, key, bytes + 1u); /* Fully charged BEFORE the first copy. */
    return copy;
}
'''


def private_audit():
    filter_task = replace(definition('audit_filter_task'),
        'static enum audit_state audit_filter_task(struct task_struct *tsk, char **key)\n',
        'static enum audit_state lsf_cleanup_audit_filter_task(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *tsk, char **key)\n')
    filter_task = replace(filter_task, '\t\t\t\t*key = kstrdup(e->rule.filterkey, GFP_ATOMIC);\n',
        '\t\t\t\t*key = lsf_cleanup_audit_key(source, tsk, e->rule.filterkey);\n')
    context = replace(definition('audit_alloc_context'),
        'static inline struct audit_context *audit_alloc_context(enum audit_state state)\n',
        'static struct audit_context *lsf_cleanup_audit_alloc_context(struct lsf_cleanup_task_source source,\n'
        '    struct task_struct *task, enum audit_state state)\n')
    context = replace(context, '\tcontext = kzalloc(sizeof(*context), GFP_KERNEL);\n',
        '\tcontext = lsf_factory_cleanup_child_new(source, task, LSF_CLEANUP_AUDIT_CONTEXT, task);\n')
    task = replace(definition('audit_alloc'), 'int audit_alloc(struct task_struct *tsk)\n',
        'int lsf_prepaid_cleanup_audit_alloc(struct lsf_cleanup_task_source source, struct task_struct *tsk)\n')
    task = replace(task, '\tchar *key = NULL;\n', '\tchar *key = NULL;\n\n'
        '\tif (!lsf_factory_cleanup_constructor_current(source, tsk))\n\t\treturn -EOPNOTSUPP;\n')
    task = replace(task, '\tstate = audit_filter_task(tsk, &key);\n',
        '\tstate = lsf_cleanup_audit_filter_task(source, tsk, &key);\n')
    task = replace(task, '\tcontext = audit_alloc_context(state);\n',
        '\tcontext = lsf_cleanup_audit_alloc_context(source, tsk, state);\n')
    task = replace(task, '\t\tkfree(key);\n',
        '\t\tif (key)\n\t\t\t(void)lsf_factory_cleanup_child_finish(key, LSF_CLEANUP_AUDIT_KEY);\n')
    return GEOMETRY + '\n' + filter_task + '\n' + context + '\n' + task


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'], 'cleanup-audit-parent-preimage')
    outputs = dict(outputs)
    name = 'include/net/lsf_stream_cleanup_descendants.h'
    outputs[name] = replace(outputs[name].decode(), '    LSF_CLEANUP_CHILD_KINDS\n',
        '    LSF_CLEANUP_AUDIT_CONTEXT,\n    LSF_CLEANUP_AUDIT_KEY,\n    LSF_CLEANUP_CHILD_KINDS\n').encode()
    name = 'net/device-prepaid.h'
    text = replace(outputs[name].decode(), '    LSF_DEVICE_CLEANUP_TASK_SECURITY,\n',
        '    LSF_DEVICE_CLEANUP_TASK_SECURITY,\n    LSF_DEVICE_CLEANUP_AUDIT_CONTEXT,\n'
        '    LSF_DEVICE_CLEANUP_AUDIT_KEY,\n')
    outputs[name] = replace(text, '        kind == LSF_DEVICE_CLEANUP_TASK_SECURITY ||\n',
        '        kind == LSF_DEVICE_CLEANUP_TASK_SECURITY ||\n'
        '        kind == LSF_DEVICE_CLEANUP_AUDIT_CONTEXT || kind == LSF_DEVICE_CLEANUP_AUDIT_KEY ||\n').encode()
    name = 'net/factory-cleanup-descendants.c'
    outputs[name] = replace(outputs[name].decode(),
        '    case LSF_CLEANUP_TASK_SECURITY: return LSF_DEVICE_CLEANUP_TASK_SECURITY;\n',
        '    case LSF_CLEANUP_TASK_SECURITY: return LSF_DEVICE_CLEANUP_TASK_SECURITY;\n'
        '    case LSF_CLEANUP_AUDIT_CONTEXT: return LSF_DEVICE_CLEANUP_AUDIT_CONTEXT;\n'
        '    case LSF_CLEANUP_AUDIT_KEY: return LSF_DEVICE_CLEANUP_AUDIT_KEY;\n').encode()
    include = '#include <net/lsf_stream_cleanup_audit.h>\n'
    name = 'kernel/lsf-cleanup-descendants.c'
    text = replace(outputs[name].decode(), '    case LSF_CLEANUP_PID:\n',
        '    case LSF_CLEANUP_AUDIT_CONTEXT:\n    case LSF_CLEANUP_AUDIT_KEY:\n'
        '#ifdef CONFIG_AUDITSYSCALL\n'
        '        return lsf_prepaid_cleanup_audit_geometry(kind, bytes, alignment);\n'
        '#else\n        return -EOPNOTSUPP;\n#endif\n'
        '    case LSF_CLEANUP_PID:\n')
    outputs[name] = (include + text).encode()
    name = 'kernel/lsf-cleanup-constructor.c'
    text = replace(outputs[name].decode(), '\tretval = audit_alloc(p);\n',
        '#ifdef CONFIG_AUDITSYSCALL\n\tretval = lsf_prepaid_cleanup_audit_alloc(source, p);\n'
        '#else\n\tretval = audit_alloc(p);\n#endif\n')
    outputs[name] = (include + text).encode()
    name = 'kernel/auditsc.c'
    text = inputs[name].decode()
    original = definition('audit_free')
    updated = replace(original, '\tif (!context)\n\t\treturn;\n',
        '\tif (!context)\n\t\treturn;\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (lsf_factory_cleanup_child_live(context, LSF_CLEANUP_AUDIT_CONTEXT) < 0)\n'
        '\t\treturn;\n#endif\n')
    text = replace(text, original, updated)
    original = definition('audit_free_context')
    updated = replace(original, '{\n', '{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tint origin = lsf_factory_cleanup_child_defer(context, LSF_CLEANUP_AUDIT_CONTEXT);\n'
        '\tif (origin < 0)\n\t\treturn;\n#endif\n')
    updated = replace(updated, '\tkfree(context);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (origin)\n\t\t(void)lsf_factory_cleanup_child_finish(context, LSF_CLEANUP_AUDIT_CONTEXT);\n'
        '\telse\n#endif\n\t\tkfree(context);\n')
    text = replace(text, original, updated)
    # Both original reset/replacement sites and the original final key return.
    for pointer in ('ctx->filterkey', 'context->filterkey'):
        needle = '\tkfree(' + pointer + ');\n'
        count = text.count(needle)
        require(count == (2 if pointer == 'ctx->filterkey' else 1), 'cleanup-audit-key-return-sites')
        text = text.replace(needle, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tif (!lsf_factory_cleanup_child_finish(' + pointer + ', LSF_CLEANUP_AUDIT_KEY))\n'
            '#endif\n\t\tkfree(' + pointer + ');\n')
    outputs[name] = (include + text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-cleanup-audit.c"\n#endif\n').encode()
    outputs['kernel/lsf-cleanup-audit.c'] = private_audit().encode()
    outputs['include/net/lsf_stream_cleanup_audit.h'] = (OWNED / 'cleanup-audit-private.h').read_bytes()
    return outputs
