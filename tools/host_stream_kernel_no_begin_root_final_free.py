"""Exact initial-only Root return extension; source stage, no execution claim."""
import hashlib
import json
from pathlib import Path

from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_cleanup_native import OWNED, function, require

FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_no_begin_root_final_free.json'
FIXTURE_SHA = '32cb2357cfdc2f5579d1d75e5a9a927e600afc767d167d9eea859eec697b9c85'
DECLARATIONS = '''int lsf_prepaid_cleanup_irq_unborn(void);
int lsf_prepaid_cleanup_irq_release_unborn(void);
'''
IRQ_HELPERS = '''/* The successful-open/no-BEGIN profile never initialized a descriptor or
 * published a private Task. All hint storage stays permanently zero except
 * the one-way terminal phase; this creates no new ownership authority. */
int lsf_prepaid_cleanup_irq_unborn(void)
{
    return !in_interrupt() &&
        atomic_read_acquire(&lsf_cleanup_irq_hint.phase) == LSF_CLEANUP_IRQ_EMPTY &&
        !atomic_read(&lsf_cleanup_irq_hint.uncertain) &&
        !lsf_cleanup_irq_hint.task && !lsf_cleanup_irq_hint.request &&
        !lsf_cleanup_irq_hint.bank_base &&
        !lsf_cleanup_irq_hint.source.owner.slot && !lsf_cleanup_irq_hint.source.owner.generation &&
        !lsf_cleanup_irq_hint.source.root.slot && !lsf_cleanup_irq_hint.source.root.generation &&
        !lsf_cleanup_irq_hint.source.request.slot && !lsf_cleanup_irq_hint.source.request.generation &&
        !lsf_cleanup_irq_hint.source.task.slot && !lsf_cleanup_irq_hint.source.task.generation;
}

int lsf_prepaid_cleanup_irq_release_unborn(void)
{
    if (!lsf_prepaid_cleanup_irq_unborn())
        return 0;
    /* A cached EMPTY caller and a new RELEASED caller both return ordinary0
     * before reading identity/range/descriptor fields. No private Task ever
     * existed in this bank. Never reset the terminal phase or zero identity. */
    return atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_EMPTY,
        LSF_CLEANUP_IRQ_RELEASED) == LSF_CLEANUP_IRQ_EMPTY;
}

'''
IRQ_FALLBACK = '''int lsf_prepaid_cleanup_irq_unborn(void) { return 0; }
int lsf_prepaid_cleanup_irq_release_unborn(void) { return 0; }
'''


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 128*1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'no-begin-fixed-preimages')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-no-begin-root-source.v1' and
        value['sourceHead'] == '7baad1341327ccd36c625e3e545faf0f1306a78e' and
        value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e' and
        len(value['parentDerived']) == 5 and len(value['readOnlyLayouts']) == 3 and
        all(value[name] is False for name in ('actualNoBeginCollection',
            'nativeQuotaRelease', 'productionInstallation')), 'no-begin-source-scope')
    for row in [*value['parentDerived'].values(), *value['readOnlyLayouts'].values()]:
        raw = row['text'].encode()
        require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'],
            'no-begin-whole-embedded-source')
    return value


def authenticate(outputs):
    for name, row in preimages()['parentDerived'].items():
        raw = outputs.get(name)
        require(type(raw) is bytes and len(raw) == row['bytes'] and
            hashlib.sha256(raw).hexdigest() == row['sha256'], 'no-begin-parent-whole-preimage')
    for name, row in preimages()['readOnlyLayouts'].items():
        raw = outputs.get(name)
        require(type(raw) is bytes and len(raw) == row['bytes'] and
            hashlib.sha256(raw).hexdigest() == row['sha256'], 'no-begin-actual-layout')


def factory(original):
    editor = Editor(original)
    editor.edit('    if (transferred == 1)\n',
        '    if (transferred == 1 || transferred == 3)\n')
    return editor.finish()


def handoff(original):
    editor = Editor(original)
    editor.edit('    unsigned int returned, observed_pending = 0;\n',
        '    unsigned int returned, observed_pending = 0, no_begin;\n')
    editor.edit('    /* All FD-specific close/cache/payload accesses have finished. Keep the\n',
        '    no_begin = !returned && lsf_cleanup_root_no_begin_locked();\n'
        '    /* All FD-specific close/cache/payload accesses have finished. Keep the\n')
    editor.edit('    result = returned ? 1 : 2;\n',
        '    result = returned ? 1 : (no_begin ? 3 : 2);\n')
    return editor.finish()


def collector(original):
    editor = Editor(original)
    editor.edit('/* Existing static record identities remain valid after their own return.\n',
        '#include "factory-cleanup-no-begin-root-final-free.c"\n\n'
        '/* Existing static record identities remain valid after their own return.\n')
    body = function(editor.text, 'static int lsf_cleanup_root_release_take_locked(')
    changed = Editor(body)
    changed.edit('    int result = 0;\n', '    int result = 0, no_begin;\n')
    start = body.index('    if (source.owner.slot != LSF_DEVICE_OWNER_SLOT')
    end = body.index('    owner = lsf_device_context(', start)
    old = body[start:end]
    require(old.endswith('        goto out;\n'), 'no-begin-child-terminal-boundary')
    changed.edit(old, '    no_begin = lsf_cleanup_root_no_begin_locked();\n'
        '    if (!no_begin) {\n'+old+'    }\n')
    changed.edit('        !lsf_cleanup_root_records_locked(source) || !lsf_cleanup_root_pages_locked() ||\n'
        '        !lsf_prepaid_cleanup_irq_closed(source, base))\n',
        '        (!no_begin && !lsf_cleanup_root_records_locked(source)) ||\n'
        '        !lsf_cleanup_root_pages_locked() ||\n'
        '        !(no_begin ? lsf_prepaid_cleanup_irq_unborn() :\n'
        '            lsf_prepaid_cleanup_irq_closed(source, base)))\n')
    changed.edit('        !lsf_prepaid_cleanup_irq_release(source, base)) {\n',
        '        !(no_begin ? lsf_prepaid_cleanup_irq_release_unborn() :\n'
        '            lsf_prepaid_cleanup_irq_release(source, base))) {\n')
    editor.edit(body, changed.finish())
    return editor.finish()


def irq(original):
    editor = Editor(original)
    editor.edit('/* Only immutable permanent hint fields, never former bank payload. The\n',
        IRQ_HELPERS+'/* Only immutable permanent hint fields, never former bank payload. The\n')
    editor.edit('#else\nint lsf_prepaid_cleanup_irq_closed(',
        '#else\n'+IRQ_FALLBACK+'int lsf_prepaid_cleanup_irq_closed(')
    return editor.finish()


def transform(outputs):
    authenticate(outputs)
    result = dict(outputs)
    for name, change in (('net/factory.c', factory),
            ('net/factory-cleanup-root-final-free.c', collector),
            ('net/factory-cleanup-late-fd-final-free.c', handoff),
            ('kernel/lsf-cleanup-irq.c', irq)):
        result[name] = change(result[name].decode()).encode()
    name = 'include/net/lsf_stream_cleanup_provider_executor.h'
    editor = Editor(result[name].decode())
    editor.edit('#endif\n', DECLARATIONS+'#endif\n')
    result[name] = editor.finish().encode()
    name = 'net/factory-cleanup-no-begin-root-final-free.c'
    require(name not in result, 'no-begin-no-preexisting-helper')
    result[name] = (OWNED/'factory-cleanup-no-begin-root-final-free.c').read_bytes()
    require({name for name in result if result[name] != outputs.get(name)} ==
        set(preimages()['parentDerived']) | {name}, 'no-begin-exact-six-source-delta')
    return result
