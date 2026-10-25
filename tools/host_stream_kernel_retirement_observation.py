"""One authenticated outside-bank observation file; no native refund.

This additive projection is not selected by the historical constructor recipe.
Its whole preimages are the actual qualified no-BEGIN/late-FD kernel source.
"""
import hashlib
import json
from pathlib import Path

from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_cleanup_native import OWNED, function, require
from tools import host_stream_kernel_no_begin_root_final_free as parent

FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_retirement_observation.json'
FIXTURE_SHA = '875b063d62d47f25d6ce2ae1ba9dc894dd9c6f433fb442bfc4767362882eae29'
FRAGMENT = 'net/factory-retirement-observation.c'


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 8*1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'retirement-observation-fixed-preimages')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-retirement-observation-source.v1'
        and value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e'
        and value['historicalKernelSource'] == '0f1e453448bc10a7d2c60453ab69140283834182'
        and len(value['parentDerived']) == 2 and len(value['readOnlyLayouts']) == 3
        and all(value[name] is False for name in ('actualKernelExecution',
            'actualNativeObservation', 'nativeQuotaRelease', 'productionInstallation')),
        'retirement-observation-source-only')
    return value


def original_sources():
    # Authenticated embedded WHOLE sources, not handwritten replacement bodies.
    value = parent.preimages()
    inputs = {name:row['text'].encode() for group in ('parentDerived','readOnlyLayouts')
        for name,row in value[group].items()}
    result = parent.transform(inputs)
    authenticate(result)
    return result


def authenticate(outputs):
    value = preimages()
    for group in ('parentDerived','readOnlyLayouts'):
        for name,bound in value[group].items():
            raw = outputs.get(name)
            require(type(raw) is bytes and len(raw) == bound['bytes'] and
                hashlib.sha256(raw).hexdigest() == bound['sha256'],
                'retirement-observation-whole-preimage')


def factory(original):
    editor = Editor(original)
    editor.edit('#include "factory-cleanup-root-final-free.c"\n',
        '#include "factory-retirement-observation.c"\n'
        '#include "factory-cleanup-root-final-free.c"\n')
    editor.edit('    .write = lsf_factory_write,\n',
        '    .write = lsf_factory_write,\n'
        '    .unlocked_ioctl = lsf_factory_retirement_ioctl,\n')
    return editor.finish()


def collector(original):
    editor = Editor(original)
    editor.edit('    struct net *net;\n};\n',
        '    struct net *net;\n'
        '    struct lsf_retirement_publication retirement;\n};\n')
    old = function(editor.text, 'static int lsf_cleanup_root_release_take_locked(')
    changed = Editor(old)
    changed.edit('    struct lsf_cleanup_task_source source;\n',
        '    struct lsf_cleanup_task_source source;\n'
        '    struct lsf_retirement_publication retirement = {0};\n')
    changed.edit('    /* Exact actual Control finish entails original restoration, registration\n',
        '    /* Last scalar observation capture while actual Root payload is live.\n'
        '     * This cannot authorize, veto or wait for the existing Root take. */\n'
        '    retirement = lsf_retirement_capture_locked(source,\n'
        '        factory.device->bootstrap_expires_ns);\n'
        '    /* Exact actual Control finish entails original restoration, registration\n')
    changed.edit('        factory.tgid, factory.cred, factory.net};\n',
        '        factory.tgid, factory.cred, factory.net, retirement};\n')
    editor.edit(old, changed.finish())
    editor.edit('    mmdrop(release.mm);\n',
        '    mmdrop(release.mm);\n'
        '    lsf_retirement_publish_after_physical(release.retirement);\n')
    return editor.finish()


def transform(outputs):
    authenticate(outputs)
    result = dict(outputs)
    for name,change in (('net/factory.c',factory),
            ('net/factory-cleanup-root-final-free.c',collector)):
        result[name] = change(result[name].decode()).encode()
    require(FRAGMENT not in result, 'retirement-observation-no-preexisting-file')
    raw = (OWNED/Path(FRAGMENT).name).read_bytes()
    bound = preimages()['fragment']
    require(len(raw) == bound['bytes'] and hashlib.sha256(raw).hexdigest() == bound['sha256'],
        'retirement-observation-fragment-identity')
    result[FRAGMENT] = raw
    require({name for name in result if result[name] != outputs.get(name)} ==
        set(preimages()['parentDerived']) | {FRAGMENT}, 'retirement-observation-exact-three-delta')
    return result
