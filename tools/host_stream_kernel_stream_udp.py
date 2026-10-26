"""Unselected exact-source copied IPv4 UDP send packet ownership.

Original socket error/shutdown/wmem accounting and IP checksum/copy/error paths
remain authoritative. Unsupported page/zero-copy shapes refuse
before their unowned allocation. This is NOT full UDP/DNS/IPv6 qualification.
"""
import hashlib

from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require

SOCK = 'net/core/sock.c'
IP = 'net/ipv4/ip_output.c'
HEADER = 'include/net/lsf_stream_packet_private.h'
PREPAID = 'net/prepaid.h'
PINS = {
    'static void ip_cork_release(': (167,
        'f7ff0c6ca879b5c2204157d8d08cb980ec0998c435732d8ae3286c37d452983d'),
    'struct sk_buff *sock_alloc_send_pskb(': (947,
        'ea487f8abde943b2f8fe10f2696de1e6fd2f52b5092261c476ba0f0cd68c88e2'),
    'static int __ip_append_data(': (8913,
        'b1d17d83ac4b1ee0df2a8bacae3d38f767b934a65f98884cf052a03e8d7acb0a'),
    'static int ip_setup_cork(': (1137,
        '3f3f483f6f30ac0aa20bb5b87aaeb9a2c064672af0f93f5137c2c5f7221065d9'),
}


def _body(text, signature):
    raw = function(text, signature)
    size, sha = PINS[signature]
    require(len(raw.encode()) == size and hashlib.sha256(raw.encode()).hexdigest() == sha,
        'stream-udp-exact-maintained-body')
    return raw


def _send_private(original):
    e = Editor(original)
    e.edit('struct sk_buff *sock_alloc_send_pskb(',
        'struct sk_buff *lsf_prepaid_stream_udp_alloc_send_pskb(')
    e.edit('\ttimeo = sock_sndtimeo(sk, noblock);\n',
        '\terr = -EOPNOTSUPP;\n'
        '\tif (lsf_prepaid_stream_udp_sock(sk) != 1 || data_len || !noblock ||\n'
        '\t    max_page_order || header_len > UINT_MAX)\n\t\tgoto failure;\n'
        '\ttimeo = sock_sndtimeo(sk, noblock);\n')
    e.edit('\tskb = alloc_skb_with_frags(header_len, data_len, max_page_order,\n'
        '\t\t\t\t   errcode, sk->sk_allocation);\n',
        '\t/* Original data_len==0 branch also sets ENOBUFS before allocation.\n'
        '\t * Full header/head/shared-info are charged from SAME socket scope. */\n'
        '\t*errcode = -ENOBUFS;\n'
        '\tskb = lsf_prepaid_packet_alloc_sock(sk, (unsigned int)header_len);\n')
    return e.finish()


def _append(original):
    e = Editor(original)
    e.edit('\tu32 tskey = 0;\n', '\tu32 tskey = 0;\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tint stream_owned = lsf_prepaid_stream_udp_sock(sk);\n'
        '\tif (stream_owned < 0) return stream_owned;\n'
        '\tif (stream_owned && ((flags & ~(MSG_DONTWAIT | MSG_NOSIGNAL)) ||\n'
        '\t    getfrag != ip_generic_getfrag || cork->gso_size || cork->tx_flags ||\n'
        '\t    READ_ONCE(sk->sk_tsflags) || inet_test_bit(RECVERR, sk)))\n'
        '\t\treturn -EOPNOTSUPP;\n'
        '#endif\n')
    e.edit('\tskb = skb_peek_tail(queue);\n', '\tskb = skb_peek_tail(queue);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (stream_owned && skb && !lsf_prepaid_packet_for_sock(skb, sk))\n'
        '\t\treturn -EOPNOTSUPP;\n'
        '#endif\n')
    e.edit('\t\t\talloclen += alloc_extra;\n', '\t\t\talloclen += alloc_extra;\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\t\t/* Do not let an unexpected jumbo/GSO shape enter page allocation. */\n'
        '\t\t\tif (stream_owned && pagedlen) {\n'
        '\t\t\t\terr = -EOPNOTSUPP;\n\t\t\t\tgoto error;\n\t\t\t}\n'
        '#endif\n')
    e.edit('\t\t\t\t\tskb = alloc_skb(alloclen,\n'
        '\t\t\t\t\t\t\tsk->sk_allocation);\n',
        '\t\t\t\t\t{\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\t\t\t\t\tif (stream_owned)\n'
        '\t\t\t\t\t\t\tskb = lsf_prepaid_packet_alloc_sock(sk, alloclen);\n'
        '\t\t\t\t\t\telse\n#endif\n'
        '\t\t\t\t\t\t\tskb = alloc_skb(alloclen, sk->sk_allocation);\n'
        '\t\t\t\t\t}\n')
    e.edit('\t\tif (!(rt->dst.dev->features&NETIF_F_SG) &&\n',
        '\t\tif ((\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\t     stream_owned ||\n#endif\n'
        '\t\t     !(rt->dst.dev->features&NETIF_F_SG)) &&\n')
    e.edit('\n\t\t} else if (flags & MSG_SPLICE_PAGES) {\n',
        '\n\t\t}\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\telse if (stream_owned) {\n'
        '\t\t\terr = -EOPNOTSUPP;\n\t\t\tgoto error;\n\t\t}\n#endif\n'
        '\t\telse if (flags & MSG_SPLICE_PAGES) {\n')
    return e.finish()


def _cork(original):
    e = Editor(original)
    e.edit('\trt = *rtp;\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tint stream_owned = lsf_prepaid_stream_udp_sock(sk);\n'
        '\tif (stream_owned < 0) return stream_owned;\n'
        '\tif (stream_owned && (ipc->gso_size || ipc->sockc.tsflags ||\n'
        '\t    inet_test_bit(RECVERR, sk) ||\n'
        '\t    (ipc->opt && ipc->opt->opt.optlen > 40)))\n'
        '\t\treturn -EOPNOTSUPP;\n'
        '#endif\n\trt = *rtp;\n')
    e.edit('\t\t\tcork->opt = kmalloc(sizeof(struct ip_options) + 40,\n'
        '\t\t\t\t\t    sk->sk_allocation);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\t\tif (stream_owned)\n'
        '\t\t\t\tcork->opt = lsf_prepaid_stream_udp_cork_allocate(sk);\n'
        '\t\t\telse\n#endif\n'
        '\t\t\tcork->opt = kmalloc(sizeof(struct ip_options) + 40,\n'
        '\t\t\t\t\t    sk->sk_allocation);\n')
    e.edit('\t\tmemcpy(cork->opt, &opt->opt, sizeof(struct ip_options) + opt->opt.optlen);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\tif (stream_owned && !lsf_prepaid_stream_udp_cork_current(sk, cork->opt))\n'
        '\t\t\treturn -EOPNOTSUPP;\n'
        '#endif\n'
        '\t\tmemcpy(cork->opt, &opt->opt, sizeof(struct ip_options) + opt->opt.optlen);\n')
    return e.finish()


def _cork_release(original):
    e = Editor(original)
    e.edit('\tkfree(cork->opt);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (!lsf_prepaid_stream_udp_cork_return(&cork->opt))\n'
        '#endif\n\t\tkfree(cork->opt);\n')
    return e.finish()


def _prepaid(original):
    e = Editor(original)
    e.edit('LSF_PREPAID_ROUTE, LSF_PREPAID_PACKET_SKB, LSF_PREPAID_PACKET_HEAD\n',
        'LSF_PREPAID_ROUTE, LSF_PREPAID_PACKET_SKB, LSF_PREPAID_PACKET_HEAD,\n'
        '    LSF_PREPAID_CORK_OPTIONS\n')
    for name in ('lsf_prepaid_child_allocate', 'lsf_prepaid_blob_find',
            'lsf_prepaid_blob_finish'):
        original_body = function(e.text, 'static inline int '+name+'(')
        body = Editor(original_body)
        body.edit('kind != LSF_PREPAID_PACKET_HEAD)',
            'kind != LSF_PREPAID_PACKET_HEAD && kind != LSF_PREPAID_CORK_OPTIONS)')
        e.edit(original_body, body.finish())
    # No queue/publish admission: copied cork options remain PRIVATE through
    # their original ip_cork_release, not ip_options_rcu's callback lifecycle.
    return e.finish()


def transform(outputs):
    require(type(outputs) is dict and 'net/core/lsf_stream_udp_private.c' not in outputs
        and 'net/ipv4/lsf_stream_udp_cork_private.c' not in outputs
        and all(type(outputs.get(n)) is bytes for n in (SOCK, IP, HEADER, PREPAID, 'net/factory.c')),
        'stream-udp-actual-source-members')
    result = dict(outputs)
    factory = Editor(outputs['net/factory.c'].decode())
    require('lsf_factory_stream_cork_allocate(' not in factory.text,
        'stream-udp-fresh-cork-factory-stage')
    owned = (OWNED/'factory-stream-udp-cork.c').read_bytes()
    require(0 < len(owned) <= 8*1024 and b'\r' not in owned,
        'stream-udp-cork-factory-source-bound')
    original = factory.text
    factory.edit(original, original+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include \"factory-stream-udp-cork.c\"\n#endif\n')
    result['net/factory.c'] = factory.finish().encode()
    result['net/factory-stream-udp-cork.c'] = owned
    core = Editor(outputs[SOCK].decode())
    original = _body(core.text, 'struct sk_buff *sock_alloc_send_pskb(')
    wrapper = Editor(original)
    wrapper.edit('\ttimeo = sock_sndtimeo(sk, noblock);\n',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tif (sk->sk_lsf_factory || sk->sk_lsf_view_slot || sk->sk_lsf_view_generation)\n'
        '\t\treturn lsf_prepaid_stream_udp_alloc_send_pskb(sk, header_len,\n'
        '\t\t\tdata_len, noblock, errcode, max_page_order);\n'
        '#endif\n\ttimeo = sock_sndtimeo(sk, noblock);\n')
    core.edit(original, wrapper.finish())
    core.edit('#include <net/tcp.h>\n', '#include <net/tcp.h>\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_packet_private.h>\n#endif\n')
    raw = (OWNED/'stream-udp-private.c').read_bytes()
    require(0 < len(raw) <= 8*1024 and b'\r' not in raw, 'stream-udp-owned-source-bound')
    prior = core.text
    core.edit(prior, prior+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf_stream_udp_private.c"\n'+_send_private(original)+'#endif\n')
    result[SOCK] = core.finish().encode()
    result['net/core/lsf_stream_udp_private.c'] = raw
    ip = Editor(outputs[IP].decode())
    for signature, derive in (('static int __ip_append_data(', _append),
            ('static int ip_setup_cork(', _cork),
            ('static void ip_cork_release(', _cork_release)):
        original = _body(ip.text, signature)
        ip.edit(original, derive(original))
    ip.edit('#include <net/sock.h>\n', '#include <net/sock.h>\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_packet_private.h>\n#endif\n')
    cork = (OWNED/'stream-udp-cork-private.c').read_bytes()
    require(0 < len(cork) <= 8*1024 and b'\r' not in cork,
        'stream-udp-cork-owned-source-bound')
    prior = ip.text
    ip.edit(prior, prior+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include \"lsf_stream_udp_cork_private.c\"\n#endif\n')
    result[IP] = ip.finish().encode()
    result['net/ipv4/lsf_stream_udp_cork_private.c'] = cork
    result[PREPAID] = _prepaid(outputs[PREPAID].decode()).encode()
    header = Editor(outputs[HEADER].decode())
    header.edit('#endif\n',
        'struct ip_options;\n'
        'struct ip_options *lsf_factory_stream_cork_allocate(struct lsf_factory_blob);\n'
        'int lsf_factory_stream_cork_current(const struct ip_options *, struct lsf_factory_blob);\n'
        'int lsf_factory_stream_cork_finish(struct lsf_factory_blob);\n'
        'struct ip_options *lsf_prepaid_stream_udp_cork_allocate(struct sock *);\n'
        'int lsf_prepaid_stream_udp_cork_current(struct sock *, const struct ip_options *);\n'
        'int lsf_prepaid_stream_udp_cork_return(struct ip_options **);\n'
        'int lsf_prepaid_stream_udp_sock(struct sock *);\n'
        'struct sk_buff *lsf_prepaid_stream_udp_alloc_send_pskb(struct sock *, unsigned long,\n'
        '    unsigned long, int, int *, int);\n#endif\n')
    result[HEADER] = header.finish().encode()
    return result
