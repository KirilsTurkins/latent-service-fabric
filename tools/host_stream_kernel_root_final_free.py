"""Exact already-retired constructor Root collector; no execution claim.

No late-close worker, native refund, reopen or production consumer is added.
The original Task/Request/Control physical returns and one-birth seals remain.
"""
import hashlib
import json
from pathlib import Path

from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_cleanup_native import OWNED, function, require

FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_root_final_free.json'
FIXTURE_SHA = '2cc535153d4bd3fb40da2f355a41642cf963e6facc56d3565b038dce2c2bf81c'
DECLARATIONS = '''int lsf_prepaid_cleanup_irq_closed(struct lsf_cleanup_task_source, unsigned long);
int lsf_prepaid_cleanup_irq_release(struct lsf_cleanup_task_source, unsigned long);
'''
IRQ_HELPERS = '''/* Only immutable permanent hint fields, never former bank payload. The
 * original pool_lock may disable IRQs; no hardirq/softirq/NMI caller is valid. */
int lsf_prepaid_cleanup_irq_closed(struct lsf_cleanup_task_source source,
    unsigned long bank_base)
{
    return !in_interrupt() &&
        atomic_read_acquire(&lsf_cleanup_irq_hint.phase) == LSF_CLEANUP_IRQ_CLOSED &&
        !atomic_read(&lsf_cleanup_irq_hint.uncertain) &&
        bank_base == lsf_cleanup_irq_hint.bank_base &&
        lsf_cleanup_irq_source_equal(source, lsf_cleanup_irq_hint.source);
}

int lsf_prepaid_cleanup_irq_release(struct lsf_cleanup_task_source source,
    unsigned long bank_base)
{
    if (!lsf_prepaid_cleanup_irq_closed(source, bank_base))
        return 0;
    /* One-way/no-reset. Original allocator free/next allocation publication
     * supplies the happens-before edge to any future ordinary Task at these
     * addresses. Cached old ARMED readers can never win their CAS again. */
    return atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, LSF_CLEANUP_IRQ_CLOSED,
        LSF_CLEANUP_IRQ_RELEASED) == LSF_CLEANUP_IRQ_CLOSED;
}

'''
IRQ_FALLBACK = '''int lsf_prepaid_cleanup_irq_closed(struct lsf_cleanup_task_source source,
    unsigned long bank_base) { (void)source; (void)bank_base; return 0; }
int lsf_prepaid_cleanup_irq_release(struct lsf_cleanup_task_source source,
    unsigned long bank_base) { (void)source; (void)bank_base; return 0; }
'''


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 64*1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'root-final-free-fixed-preimages')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-root-final-free-source.v1' and
        value['sourceHead'] == '000860214497535901b1aee49ea8f58e4823be2d' and
        value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e' and
        len(value['parentDerived']) == 4 and len(value['headers']) == 2 and
        all(value[name] is False for name in ('actualLinuxFinalFree',
            'nativeQuotaRelease', 'productionInstallation')), 'root-final-free-original-scope')
    for row in value['parentDerived'].values():
        raw = row['text'].encode()
        require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'],
            'root-final-free-embedded-whole-preimage')
    return value


def factory(original):
    editor = Editor(original)
    editor.edit('#include "factory-cleanup-native-bootstrap.c"\n',
        '#include "factory-cleanup-native-bootstrap.c"\n'
        '#include "factory-cleanup-root-final-free.c"\n')
    old = function(editor.text, 'static int lsf_factory_release(')
    body = Editor(old)
    body.edit('    unsigned int i;\n',
        '    unsigned int i;\n    struct lsf_cleanup_root_release release;\n')
    body.edit('    /* Closing a descriptor is not final-free. No __free_pages, object release,\n'
        '     * owner recycling, reference refund or reopen is justified here. Original\n'
        '     * node backing and occupancy must stay in bounded native quarantine. */\n',
        '    /* Only a graph ALREADY physically retired at this final FD release\n'
        '     * may unpublish its Root. Late close/cancellation remains held. */\n'
        '    (void)lsf_cleanup_root_release_take_locked(file, &release);\n')
    body.edit('    mutex_unlock(&factory_lock);\n    return 0;\n',
        '    mutex_unlock(&factory_lock);\n'
        '    lsf_cleanup_root_release_physical(release);\n    return 0;\n')
    editor.edit(old, body.finish())
    return editor.finish()


def irq(original):
    editor = Editor(original)
    editor.edit('    LSF_CLEANUP_IRQ_CONSUMED\n',
        '    LSF_CLEANUP_IRQ_CONSUMED,\n'
        '    LSF_CLEANUP_IRQ_CLOSED,\n    LSF_CLEANUP_IRQ_RELEASED\n')
    editor.edit('    if (phase == LSF_CLEANUP_IRQ_EMPTY || phase == LSF_CLEANUP_IRQ_PREPARING)\n',
        '    if (phase == LSF_CLEANUP_IRQ_EMPTY || phase == LSF_CLEANUP_IRQ_PREPARING ||\n'
        '        phase == LSF_CLEANUP_IRQ_RELEASED)\n')
    editor.edit(' * There is ONE birth, no reset/reuse/ABA, and no current backing-return path.\n'
        ' * A future physical bank return MUST close this hint before releasing pages;\n'
        ' * no such return or production installation is claimed by this source layer. */\n',
        ' * There is ONE birth, no reset/reuse/ABA. CLOSED follows actual descriptor\n'
        ' * synchronization while Request remains owned. RELEASED precedes the\n'
        ' * original already-retired bank return; identity remains immutable. */\n')
    editor.edit('#else\nunsigned long lsf_prepaid_cleanup_irq_bootstrap_bytes(void)',
        IRQ_HELPERS+'#else\n'+IRQ_FALLBACK+
        'unsigned long lsf_prepaid_cleanup_irq_bootstrap_bytes(void)')
    return editor.finish()


def close(original):
    editor = Editor(original)
    editor.edit('    return atomic_read(&lsf_cleanup_irq_hint.uncertain) ? -EIO : 0;\n',
        '    if (atomic_read(&lsf_cleanup_irq_hint.uncertain))\n        return -EIO;\n'
        '    /* Request is still physically owned. Refuse every intermediate\n'
        '     * phase; no descriptor may be followed after this one-way close. */\n'
        '    return atomic_cmpxchg(&lsf_cleanup_irq_hint.phase, phase,\n'
        '        LSF_CLEANUP_IRQ_CLOSED) == phase ? 0 : -EIO;\n')
    return editor.finish()


def transform(outputs):
    expected = preimages()['parentDerived']
    for name, row in expected.items():
        raw = outputs.get(name)
        require(type(raw) is bytes and len(raw) == row['bytes'] and
            hashlib.sha256(raw).hexdigest() == row['sha256'], 'root-final-free-actual-000860-preimage')
    result = dict(outputs)
    for name, operation in (('net/factory.c', factory),
            ('kernel/lsf-cleanup-irq.c', irq), ('kernel/lsf-cleanup-close.c', close)):
        result[name] = operation(result[name].decode()).encode()
    name = 'include/net/lsf_stream_cleanup_provider_executor.h'
    editor = Editor(result[name].decode())
    editor.edit('#endif\n', DECLARATIONS+'#endif\n')
    result[name] = editor.finish().encode()
    result['net/factory-cleanup-root-final-free.c'] = (OWNED/'factory-cleanup-root-final-free.c').read_bytes()
    require({name for name in result if result[name] != outputs.get(name)} ==
        set(expected) | {'net/factory-cleanup-root-final-free.c'}, 'root-final-free-exact-five-source-delta')
    return result


def authenticate_headers(originals):
    for name, row in preimages()['headers'].items():
        raw = originals.get(name)
        require(type(raw) is bytes and len(raw) == row['bytes'] and
            hashlib.sha256(raw).hexdigest() == row['sha256'], 'root-final-free-original-page-header')
