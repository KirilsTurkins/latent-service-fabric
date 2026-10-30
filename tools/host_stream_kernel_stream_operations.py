"""Separate, unselected stream operations on the original protected factory.

The original observation image is a preimage, never an eligible operation
image. This source projection alone cannot select a consumer or install a
provider. A fresh complete kernel and physical-allocation qualification remain
required. Constructor-v2, observation mint and Root collector stay original.
"""
import hashlib

from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_cleanup_native import OWNED, require


FACTORY_BYTES = 34800
FACTORY_SHA = 'a183864a8b9408e032876cb292a303a08aa48cdbde03f8069768a7c071f0870f'
HEADER = 'net/stream-operation-private.h'
OPERATIONS = 'net/factory-stream-operations.c'


def factory(raw):
    require(type(raw) is bytes and len(raw) == FACTORY_BYTES
        and hashlib.sha256(raw).hexdigest() == FACTORY_SHA,
        'stream-operations-original-factory-preimage')
    editor = Editor(raw.decode())
    editor.edit('#include "factory-private.h"\n',
        '#include "factory-private.h"\n#include "stream-operation-private.h"\n')
    editor.edit('    lsf_u64 lease;\n};\n',
        '    lsf_u64 lease;\n    struct lsf_stream_context stream;\n};\n')
    editor.edit('    struct lsf_factory_reply reply;\n',
        '    struct lsf_factory_reply reply;\n'
        '    struct lsf_stream_request stream_request;\n'
        '    struct lsf_stream_response stream_response;\n')
    editor.edit('static ssize_t lsf_factory_write(struct file *file, const char __user *buffer,\n',
        '#include "factory-stream-operations.c"\n\n'
        'static ssize_t lsf_factory_write(struct file *file, const char __user *buffer,\n')
    # Original read(2) may consume only its original reply tag. The new stream
    # protocol uses readv(2)/writev(2); neither may consume the other's reply.
    # Ordinary constructor-v2 execution sees exactly the same tag1 predicate.
    editor.edit('    else if (count == sizeof(factory.reply) && factory.reply_pending) {\n',
        '    else if (count == sizeof(factory.reply) && factory.reply_pending == 1) {\n')
    editor.edit('    .write = lsf_factory_write,\n',
        '    .write = lsf_factory_write,\n'
        '    .read_iter = lsf_factory_stream_read_iter,\n'
        '    .write_iter = lsf_factory_stream_write_iter,\n')
    # Editor.finish verifies the whole reverse projection, including every
    # original constructor/actor/LSM/mint/close/Root line outside these anchors.
    return editor.finish().encode()


def transform(outputs):
    require(type(outputs) is dict and HEADER not in outputs and OPERATIONS not in outputs,
        'stream-operations-fresh-source-stage')
    result = dict(outputs)
    result['net/factory.c'] = factory(outputs.get('net/factory.c'))
    for name in (HEADER, OPERATIONS):
        raw = (OWNED/name.rsplit('/', 1)[1]).read_bytes()
        require(0 < len(raw) <= 32*1024 and b'\r' not in raw,
            'stream-operations-owned-source-bound')
        result[name] = raw
    require({name for name in result if result[name] != outputs.get(name)}
        == {'net/factory.c', HEADER, OPERATIONS}, 'stream-operations-exact-source-delta')
    return result
