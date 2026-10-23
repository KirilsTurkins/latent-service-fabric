"""Original final-FD custody and kthreadd Root collection; source only.

No extra Task, workqueue, owner ledger, native refund or production selection.
The predecessor's complete terminal/IRQ/page/ref guards remain mandatory.
"""
import hashlib
import json
from pathlib import Path

from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_cleanup_native import OWNED, function, require

FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_late_fd_final_free.json'
FIXTURE_SHA = '6083b5e7cb33cd074a6af1babe90dcb6712934bec000307272b06e055534770b'
DECLARATIONS = '''int lsf_factory_cleanup_root_pending(void);
void lsf_factory_cleanup_root_drain(void);
'''


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 8*1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'late-fd-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-late-fd-root-source.v1' and
        value['sourceHead'] == 'eef89f053e7729c314235471a5ec984b0541a474' and
        value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e' and
        len(value['parentDerived']) == 4 and
        all(value[name] is False for name in ('actualLateFdCollection',
            'nativeQuotaRelease', 'productionInstallation')), 'late-fd-source-scope')
    row = value['kthreadd']
    raw = row['text'].encode()
    require(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'],
        'late-fd-selected-kthreadd')
    return value


def authenticate(outputs):
    for name, row in preimages()['parentDerived'].items():
        raw = outputs.get(name)
        require(type(raw) is bytes and len(raw) == row['bytes'] and
            hashlib.sha256(raw).hexdigest() == row['sha256'], 'late-fd-parent-whole-preimage')


def factory(original):
    editor = Editor(original)
    editor.edit('#include "factory-cleanup-root-final-free.c"\n',
        '#include "factory-cleanup-root-final-free.c"\n'
        '#include "factory-cleanup-late-fd-final-free.c"\n')
    old = function(editor.text, 'static int lsf_factory_release(')
    body = Editor(old)
    body.edit('    struct lsf_cleanup_root_release release;\n',
        '    struct lsf_cleanup_root_release release = {0};\n'
        '    int transferred;\n')
    body.edit('    /* Only a graph ALREADY physically retired at this final FD release\n'
        '     * may unpublish its Root. Late close/cancellation remains held. */\n'
        '    (void)lsf_cleanup_root_release_take_locked(file, &release);\n',
        '    /* Actual final VFS custody transfers AFTER the last FD cache/Root\n'
        '     * use. This never authorizes a physical return by itself. */\n'
        '    transferred = lsf_cleanup_root_fd_handoff_locked(file);\n'
        '    if (transferred)\n'
        '        (void)lsf_cleanup_root_release_take_locked(&release);\n')
    body.edit('    lsf_cleanup_root_release_physical(release);\n    return 0;\n',
        '    lsf_cleanup_root_release_physical(release);\n'
        '    if (transferred)\n'
        '        wake_up_process(kthreadd_task);\n    return 0;\n')
    editor.edit(old, body.finish())
    return editor.finish()


def collector(original):
    editor = Editor(original)
    editor.edit('static int lsf_cleanup_root_release_take_locked(struct file *file,\n'
        '    struct lsf_cleanup_root_release *release)\n',
        'static int lsf_cleanup_root_release_take_locked(\n'
        '    struct lsf_cleanup_root_release *release)\n')
    editor.edit('    if (file->private_data != &factory || !lsf_factory_constructor_qualification() ||\n'
        '        lsf_factory_selected_consumer() || !factory.opened || !factory.pages || !factory.device ||\n'
        '        file->f_cred != factory.cred ||\n',
        '    if (factory.opened != 2u || !lsf_factory_constructor_qualification() ||\n'
        '        lsf_factory_selected_consumer() || !factory.pages || !factory.device ||\n')
    editor.edit('    factory.net = NULL;\n    file->private_data = NULL;\n    result = 1;\n',
        '    factory.net = NULL;\n    result = 1;\n')
    editor.edit('/* Called once by actual final FD .release after its existing close and cache\n'
        ' * scans; factory_lock held. Not-ready/uncertain graphs remain quarantined.\n',
        '/* Common original-owner take after authenticated final FD handoff;\n'
        ' * factory_lock held. Not-ready/uncertain graphs remain quarantined.\n')
    return editor.finish()


def kthreadd_function(original):
    row = preimages()['kthreadd']
    require(original == row['text'], 'late-fd-exact-kthreadd-function')
    editor = Editor(original)
    editor.edit('\t\t    && !lsf_factory_cleanup_request_pending()\n',
        '\t\t    && !lsf_factory_cleanup_request_pending()\n'
        '\t\t    && !lsf_factory_cleanup_root_pending()\n')
    editor.edit('\t\t       || lsf_factory_cleanup_request_pending()\n',
        '\t\t       || lsf_factory_cleanup_request_pending()\n'
        '\t\t       || lsf_factory_cleanup_root_pending()\n')
    editor.edit('\t\t\tif (lsf_factory_cleanup_final_pending()) {\n',
        '\t\t\tif (lsf_factory_cleanup_root_pending()) {\n'
        '\t\t\t\tspin_unlock(&kthread_create_lock);\n'
        '\t\t\t\tlsf_factory_cleanup_root_drain();\n'
        '\t\t\t\tspin_lock(&kthread_create_lock);\n'
        '\t\t\t\tcontinue;\n\t\t\t}\n'
        '\t\t\tif (lsf_factory_cleanup_final_pending()) {\n')
    editor.edit('\t\t\t}\n#endif\n\t\t\tstruct kthread_create_info *create;\n',
        '\t\t\t}\n'
        '\t\t\t/* A competing FD fast take may consume the only private\n'
        '\t\t\t * reason after the while test. Every private branch has had\n'
        '\t\t\t * its chance; ordinary extraction still requires a member. */\n'
        '\t\t\tif (list_empty(&kthread_create_list))\n\t\t\t\tcontinue;\n'
        '#endif\n\t\t\tstruct kthread_create_info *create;\n')
    return editor.finish()


def transform(outputs):
    authenticate(outputs)
    result = dict(outputs)
    for name, change in (('net/factory.c', factory),
            ('net/factory-cleanup-root-final-free.c', collector)):
        result[name] = change(result[name].decode()).encode()
    name = 'kernel/kthread.c'
    editor = Editor(result[name].decode())
    original = function(editor.text, 'int kthreadd(')
    editor.edit(original, kthreadd_function(original))
    result[name] = editor.finish().encode()
    name = 'include/net/lsf_stream_cleanup_provider_executor.h'
    editor = Editor(result[name].decode())
    editor.edit('#endif\n', DECLARATIONS+'#endif\n')
    result[name] = editor.finish().encode()
    name = 'net/factory-cleanup-late-fd-final-free.c'
    require(name not in result, 'late-fd-no-preexisting-collector')
    result[name] = (OWNED/'factory-cleanup-late-fd-final-free.c').read_bytes()
    require({name for name in result if result[name] != outputs.get(name)} ==
        set(preimages()['parentDerived']) | {'net/factory-cleanup-late-fd-final-free.c'},
        'late-fd-exact-five-source-delta')
    return result
