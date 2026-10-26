"""Separate normal typed TCP/UDP IPv4/IPv6 constructors; SOURCE ONLY.

Never changes historical TCP-only tools/fixtures or ordinary kernel methods.
No consumer selection, packet/Netlabel refusal removal, image/fit qualification.
"""
import hashlib
import json

from tools import host_stream_kernel_protocol as prior
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require

IPV6 = 'net/ipv6/af_inet6.c'
IPV6_BYTES = 32534
IPV6_SHA = 'f27d331aa781752457541f6f40e7f5b5d05268855135a56abb61a6e511a69f98'
ALLOCATOR_SHA = '3a0c4a06f2fa0eb991f5157d61d5f6fe58f5adef023174567720eb619ed90fbc'


def _type_guard():
    return ('((sock->type != SOCK_STREAM || (protocol != 0 && protocol != IPPROTO_TCP)) &&\n'
        '\t     (sock->type != SOCK_DGRAM || (protocol != 0 && protocol != IPPROTO_UDP)))')


def _original(name):
    raw = json.loads(prior.FIXTURE.read_bytes())['sections'][name]['text']
    return prior.section(raw, name)


def _inet4():
    old = prior.private(_original('inet_create'), 'inet_create')
    e = Editor(old)
    e.edit('sock->type != SOCK_STREAM || (protocol != 0 && protocol != IPPROTO_TCP)', _type_guard())
    e.edit('\tif (answer->prot != &tcp_prot || answer->ops != &inet_stream_ops) {\n',
        '\tif ((sock->type == SOCK_STREAM &&\n'
        '\t     (answer->prot != &tcp_prot || answer->ops != &inet_stream_ops)) ||\n'
        '\t    (sock->type == SOCK_DGRAM &&\n'
        '\t     (answer->prot != &udp_prot || answer->ops != &inet_dgram_ops))) {\n')
    return old, e.finish()


def _outer():
    old = prior.private(_original('__sock_create'), '__sock_create')
    e = Editor(old)
    e.edit('\tif (!context || !kern || family != PF_INET || type != SOCK_STREAM ||\n'
        '\t    (protocol != 0 && protocol != IPPROTO_TCP) || !lsf_prepaid_protocol_security_supported())\n'
        '\t\treturn -EOPNOTSUPP;\n',
        '\tif (!context || !kern || (family != PF_INET && family != PF_INET6) ||\n'
        '\t    ((type != SOCK_STREAM || (protocol != 0 && protocol != IPPROTO_TCP)) &&\n'
        '\t     (type != SOCK_DGRAM || (protocol != 0 && protocol != IPPROTO_UDP))) ||\n'
        '\t    !lsf_prepaid_protocol_security_supported())\n'
        '\t\treturn -EOPNOTSUPP;\n'
        '#if !IS_BUILTIN(CONFIG_IPV6)\n'
        '\tif (family == PF_INET6)\n'
        '\t\treturn -EOPNOTSUPP; /* No module autoload or unowned family fallback. */\n'
        '#endif\n')
    e.edit('\tif (!pf || !lsf_prepaid_protocol_family(pf))\n',
        '\tif (!pf || (family == PF_INET && !lsf_prepaid_protocol_family(pf))\n'
        '#if IS_BUILTIN(CONFIG_IPV6)\n'
        '\t    || (family == PF_INET6 && !lsf_prepaid_stream_protocol_family6(pf))\n'
        '#endif\n\t   )\n')
    e.edit('\terr = lsf_prepaid_inet_create(net, sock, protocol, kern, context, pf);\n',
        '#if IS_BUILTIN(CONFIG_IPV6)\n\tif (family == PF_INET6)\n'
        '\t\terr = lsf_prepaid_stream_inet6_create(net, sock, protocol, kern, context, pf);\n'
        '\telse\n#endif\n'
        '\t\terr = lsf_prepaid_inet_create(net, sock, protocol, kern, context, pf);\n')
    return old, e.finish()


def _inet6(raw):
    require(type(raw) is bytes and len(raw) == IPV6_BYTES and
        hashlib.sha256(raw).hexdigest() == IPV6_SHA, 'stream-protocol-pinned-inet6-whole')
    original = raw.decode()
    old = function(original, 'static int inet6_create(')
    e = Editor(old)
    e.edit('static int inet6_create(struct net *net, struct socket *sock, int protocol,\n'
        '\t\t\tint kern)',
        'int lsf_prepaid_stream_inet6_create(struct net *net, struct socket *sock, int protocol,\n'
        '\t\t\tint kern, struct lsf_factory_context *context, const struct net_proto_family *family)')
    e.edit('\tint try_loading_module = 0;\n',
        '\t/* Fixed private family: no module autoload or retry owner. */\n')
    e.edit('\tif (protocol < 0 || protocol >= IPPROTO_MAX)\n',
        '\tif (!context || !kern || family != &inet6_family_ops ||\n\t    '+_type_guard()+')\n'
        '\t\treturn -EOPNOTSUPP;\n\tif (protocol < 0 || protocol >= IPPROTO_MAX)\n')
    e.edit('lookup_protocol:\n',
        '\t/* Original registered built-in protocol lookup, once. */\n')
    begin = e.text.index('\tif (err) {')
    end = e.text.index('\n\terr = -EPERM;', begin)
    block = e.text[begin:end]
    require('try_loading_module' in block and 'request_module(' in block,
        'stream-protocol-exact-inet6-module-block')
    e.edit(block, '\tif (err)\n\t\tgoto out_rcu_unlock;\n')
    e.edit('\tsock->ops = answer->ops;\n',
        '\tif ((sock->type == SOCK_STREAM &&\n'
        '\t     (answer->prot != &tcpv6_prot || answer->ops != &inet6_stream_ops)) ||\n'
        '\t    (sock->type == SOCK_DGRAM &&\n'
        '\t     (answer->prot != &udpv6_prot || answer->ops != &inet6_dgram_ops))) {\n'
        '\t\terr = -EOPNOTSUPP;\n\t\tgoto out_rcu_unlock;\n\t}\n'
        '\tsock->ops = answer->ops;\n')
    e.edit('sk_alloc(net, PF_INET6, GFP_KERNEL, answer_prot, kern)',
        'lsf_prepaid_sk_alloc(net, PF_INET6, GFP_KERNEL, answer_prot, kern, context)')
    private = e.finish()
    # Original lookup/init/destructor/module/error cleanup stay original.
    whole = Editor(original)
    whole.edit(original, original+'\n#if defined(CONFIG_LSF_STREAM_FACTORY) && IS_BUILTIN(CONFIG_IPV6)\n'
        '#include <net/lsf_stream_protocol_private.h>\n'
        'bool lsf_prepaid_stream_protocol_family6(const struct net_proto_family *family)\n'
        '{\n\treturn family == &inet6_family_ops;\n}\n'+private+'#endif\n')
    return whole.finish().encode()


def transform(outputs, inet6):
    require(type(outputs) is dict and IPV6 not in outputs,
        'stream-protocol-fresh-inet6-stage')
    result = dict(outputs)
    for path, derive in (('net/socket.c', _outer), ('net/ipv4/af_inet.c', _inet4)):
        require(type(outputs.get(path)) is bytes, 'stream-protocol-actual-prior-source-required')
        old, new = derive()
        editor = Editor(outputs[path].decode())
        editor.edit(old, new)
        result[path] = editor.finish().encode()
    path = 'net/core/lsf_protocol_private.c'
    require(type(outputs.get(path)) is bytes, 'stream-protocol-original-allocator-required')
    editor = Editor(outputs[path].decode())
    old = function(editor.text, 'struct sock *lsf_prepaid_protocol_allocate(')
    require(hashlib.sha256(old.encode()).hexdigest() == ALLOCATOR_SHA,
        'stream-protocol-whole-original-allocator')
    new = (OWNED/'stream-protocol-allocation.c').read_bytes()
    require(0 < len(new) <= 8*1024 and b'\r' not in new, 'stream-protocol-owned-allocator-bound')
    # Original clear/final-return and ordinary slab/LSM/packet stay untouched.
    editor.edit(old, new.decode())
    editor.edit('#include <linux/in.h>\n', '#include <linux/in.h>\n'
        '#include <linux/ipv6.h>\n#include <net/udp.h>\n#include <net/transp_v6.h>\n')
    result[path] = editor.finish().encode()
    path = 'include/net/lsf_stream_protocol_private.h'
    editor = Editor(outputs[path].decode())
    editor.edit('bool lsf_prepaid_protocol_family(const struct net_proto_family *);\n',
        'bool lsf_prepaid_protocol_family(const struct net_proto_family *);\n'
        '#if IS_BUILTIN(CONFIG_IPV6)\n'
        'bool lsf_prepaid_stream_protocol_family6(const struct net_proto_family *);\n'
        'int lsf_prepaid_stream_inet6_create(struct net *, struct socket *, int, int,\n'
        '    struct lsf_factory_context *, const struct net_proto_family *);\n#endif\n')
    result[path] = editor.finish().encode()
    # The existing IPv4 rtable/XFRM producer already allocates from this
    # exact socket parent before publication. Add only the actual UDP proto;
    # IPv6 routes and all XFRM/default-block/LSM/ref-tracker guards stay closed.
    path = 'net/ipv4/lsf_route_private.c'
    require(type(outputs.get(path)) is bytes, 'stream-protocol-actual-route-source-required')
    editor = Editor(outputs[path].decode())
    old = function(editor.text, 'static int lsf_prepaid_route_source(')
    original = function((OWNED/'route-private.c').read_text(),
        'static int lsf_prepaid_route_source(')
    require(hashlib.sha256(original.encode()).hexdigest() ==
        '742dc69e54eeefb2af69539cc2762929bd61a0e28dcf5c44ada68ea13fbf5a37' and
        original.count('lsf_factory_poison(source->context);') == 1,
        'stream-protocol-original-tcp-route-source')
    # Preserve the exact already-selected original device-security carrier
    # conversion; never restore the older context-only poison at this join.
    carrier = original.replace('lsf_factory_poison(source->context);',
        'lsf_factory_blob_poison(*source);')
    require(old == carrier and hashlib.sha256(old.encode()).hexdigest() ==
        'e25eab21264e24420eaddb22114ca50f2dbdc2f5d3b3e0da76fd9b5c354687e4',
        'stream-protocol-whole-typed-tcp-route-source')
    body = Editor(old)
    body.edit('                      sk->sk_protocol != IPPROTO_TCP || sk->sk_prot != &tcp_prot)',
        '                      !((sk->sk_protocol == IPPROTO_TCP && sk->sk_prot == &tcp_prot) ||\n'
        '                        (sk->sk_protocol == IPPROTO_UDP && sk->sk_prot == &udp_prot)))')
    editor.edit(old, body.finish())
    editor.edit('static_assert(offsetof(struct rtable, dst) == 0);\n',
        '#include <net/udp.h>\nstatic_assert(offsetof(struct rtable, dst) == 0);\n')
    result[path] = editor.finish().encode()
    result[IPV6] = _inet6(inet6)
    return result
