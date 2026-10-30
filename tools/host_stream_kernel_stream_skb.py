"""Exact normal-SKB/RX namespace composition; unselected and unqualified.

The old normal body is retained verbatim inside each dispatch fallback. Only
an actual RX ticket may enter the new branch. Other private pointers still
face their original namespace guards; build cannot allocate for such pointers.
Unported RX clone/copy/expand paths refuse before their first allocation.
"""
import hashlib

from tools.host_stream_kernel_cleanup_native import require
from tools.host_stream_kernel_constructor_failure import Editor

RAW = (189334, '6a2fec31182c7c4d247d85aaffba036de9c0b6a9911c3cc1249d00b423ea0ae8')
NORMAL = (197585, '5bf6c085dd50ea1e4ca945db88c7de44f0adc6ff9fd1bb85cf99332db16b6347')
RX_CORE = (46360, 'a99ff0e60a383fb607a2630ae5a642f2702c7a02ca4e94f5ca798496d50f571f')
DISPATCH = (2858, '7007a4e36e41f2a48be51e2f659be266f1bc02da446ab1060dbb9f2d5ef4908a')


def _pin(raw, expected):
    require(type(raw) is bytes and (len(raw), hashlib.sha256(raw).hexdigest()) == expected,
        'stream-skb-whole-source-preimage')


def _definitions(text, prefix):
    starts = [i for i in range(len(text)) if text.startswith(prefix, i)
        and (i == 0 or text[i-1] == '\n')]
    result = []
    for start in starts:
        end = text.find('\n}\n', start)
        require(end >= 0, 'stream-skb-definition-end')
        result.append(text[start:end+3])
    return result


def _wrap(old, address, kind, failure, positive, *, build=False):
    declaration, body = old.split('\n{\n', 1)
    # Fresh blocks preserve original declaration/label scope. The complete old
    # body (including existing CONFIG wrappers) survives, and Editor reverses
    # ALL wrappers against the pinned original normal TU, not selected snippets.
    guard = ('\tint stream_rx = lsf_factory_stream_rx_skb_kind(' + address +
        ', LSF_STREAM_SKB_' + kind + ');\n' +
        '\tif (stream_rx < 0' + (' || stream_rx == 2' if build else '') + ')\n' +
        '\t\treturn' + (' ' + failure if failure else '') + ';\n')
    return declaration + '\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + guard +         '\tif (stream_rx == 1) {\n' + positive + '\t}\n#endif\n\t{\n' + body[:-2] + '\t}\n}\n'


def compose(raw, normal):
    _pin(raw, RAW)
    _pin(normal, NORMAL)
    original = raw.decode()
    editor = Editor(normal.decode())
    editor.edit('#include <linux/module.h>\n',
        '#include <linux/module.h>\n#include <net/lsf_stream_ring_profile_private.h>\n')
    specs = [
        ('struct sk_buff *__build_skb(', 'data', 'HEAD', 'NULL', 'build', 1),
        ('static struct sk_buff *__napi_build_skb(', 'data', 'HEAD', 'NULL', 'build', 1),
        ('static void skb_free_head(', 'skb->head', 'HEAD', '',
            '\t\t(void)lsf_factory_stream_rx_data_return(skb->head);\n\t\treturn;\n', 1),
        ('static void kfree_skbmem(', 'skb', 'HEADER', '',
            '\t\t(void)lsf_factory_stream_rx_header_return(skb);\n\t\treturn;\n', 1),
        ('static void napi_skb_cache_put(', 'skb', 'HEADER', '',
            '\t\t(void)lsf_factory_stream_rx_header_return(skb);\n\t\treturn;\n', 1),
        ('static void kfree_skb_add_bulk(', 'skb', 'HEADER', '',
            '\t\tskb_release_all(skb, reason);\n'
            '\t\t(void)lsf_factory_stream_rx_header_return(skb);\n\t\treturn;\n', 1),
        ('void kfree_skb_partial(', 'skb', 'HEADER', '',
            '\t\tif (head_stolen) {\n\t\t\tskb_release_head_state(skb);\n'
            '\t\t\t(void)lsf_factory_stream_rx_header_return(skb);\n'
            '\t\t} else {\n\t\t\t__kfree_skb(skb);\n\t\t}\n\t\treturn;\n', 1),
        ('static void skb_release_data(', 'skb', 'HEADER', '', 'release', 1),
        ('struct sk_buff *skb_clone(', 'skb', 'HEADER', 'NULL', '\t\treturn NULL;\n', 1),
        ('int pskb_expand_head(', 'skb', 'HEADER', '-EOPNOTSUPP',
            '\t\treturn -EOPNOTSUPP;\n', 1),
        ('struct sk_buff *skb_copy(', 'skb', 'HEADER', 'NULL', '\t\treturn NULL;\n', 1),
        ('struct sk_buff *__pskb_copy_fclone(', 'skb', 'HEADER', 'NULL', '\t\treturn NULL;\n', 2),
        ('struct sk_buff *skb_copy_expand(', 'skb', 'HEADER', 'NULL', '\t\treturn NULL;\n', 2),
    ]
    for prefix, address, kind, failure, positive, count in specs:
        bodies = _definitions(editor.text, prefix)
        require(len(bodies) == count, 'stream-skb-exact-definition-count')
        if positive == 'build':
            positive = ('\t\tstruct sk_buff *skb;\n'
                '\t\tif (lsf_factory_stream_rx_header(data, frag_size, &skb) != 1)\n'
                '\t\t\treturn NULL;\n'
                '\t\tmemset(skb, 0, offsetof(struct sk_buff, tail));\n'
                '\t\t__build_skb_around(skb, data, frag_size);\n\t\treturn skb;\n')
        elif positive == 'release':
            selected = _definitions(original, prefix)
            require(len(selected) == 1, 'stream-skb-original-release-definition')
            release = selected[0].split('\n{\n', 1)[1][:-2]
            # C labels have function scope, even inside a fresh block. Rename
            # ONLY the two original labels and their exact goto operands in
            # this duplicated RX branch; the old normal function stays exact.
            for label, uses in (('exit', 1), ('free_head', 1)):
                require(release.count('goto ' + label + ';') == uses and
                    release.count('\n' + label + ':') == 1,
                    'stream-skb-release-label-preimage')
                release = release.replace('goto ' + label + ';',
                    'goto lsf_stream_rx_' + label + ';').replace('\n' + label + ':',
                    '\nlsf_stream_rx_' + label + ':')
            positive = ('\t\t{\n' + release + '\t\t}\n\t\treturn;\n')
        for old in bodies:
            editor.edit(old, _wrap(old, address, kind, failure, positive,
                build=prefix in ('struct sk_buff *__build_skb(',
                    'static struct sk_buff *__napi_build_skb(')))
    return editor.finish().encode()


def finish(outputs):
    """Attach the typed namespace hook AFTER old exact core projections.

    Do not change their raw RX source or whole-body preimages to insert it.
    The original RX state/Root validators remain in this same allocating TU.
    """
    from tools.host_stream_kernel_cleanup_native import OWNED
    require(type(outputs) is dict and 'net/factory.c' in outputs and
        'net/factory-stream-skb-dispatch.c' not in outputs,
        'stream-skb-fresh-hook-stage')
    _pin(outputs.get('net/factory-stream-rx-preallocate.c'), RX_CORE)
    source = (OWNED/'stream-skb-dispatch.c').read_bytes()
    _pin(source, DISPATCH)
    editor = Editor(outputs['net/factory.c'].decode())
    anchor = '#include "factory-stream-rx-preallocate.c"\n'
    editor.edit(anchor, anchor+'#include "factory-stream-skb-dispatch.c"\n')
    result = dict(outputs)
    result['net/factory.c'] = editor.finish().encode()
    result['net/factory-stream-skb-dispatch.c'] = source
    return result
