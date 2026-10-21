"""WIP: maintained linear copied-TCP packet source; no installed selection."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_route_cache as prior

OWNED = prior.OWNED
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_packet.json'
TCP = 'net/ipv4/tcp.c'
CLONES = ('tcp_stream_alloc_skb', 'tcp_sendmsg_locked')
COPIES = ('__pskb_copy_fclone', 'skb_copy_expand')
EXTRAS = {TCP, 'include/net/tcp.h', 'net/ipv4/tcp_output.c', 'net/ipv4/tcp_input.c'}
replace = prior.replace
require = prior.require


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    parent = prior.fixture()
    require(value['upstreamCommit'] == parent['upstreamCommit'] and
        value['archiveSha256'] == parent['archiveSha256'], 'packet-maintained-identity')
    require(set(value['source']) == set(parent['source']) | EXTRAS and
        all(value['source'][name] == row for name, row in parent['source'].items()),
        'packet-whole-membership')
    require(all(value[key] is False for key in ('kernelBuilt', 'actualPacketExchangeExecuted',
        'actualLinuxRcuExecuted', 'completeAllocationClosure', 'finalFreeCertified',
        'productionInstallation')), 'packet-uninstalled')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i - 1] == '\n')]
    require(len(starts) == 1, 'packet-definition-occurrence')
    end = text.find('\n}\n', starts[0])
    require(end >= 0, 'packet-definition-end')
    raw = text[starts[0]:end + 3]
    require(raw == row['text'] and len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'],
        'packet-definition-preimage')
    return raw


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'packet-whole-membership')
    maintained = prior.route.bind.avc.maintained
    maintained.authenticate_files(inputs, value['source'])
    prior.authenticate({name: inputs[name] for name in prior.fixture()['source']})
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def private(raw, name):
    require(name in CLONES and section(raw, name) == raw, 'packet-private-preimage')
    declaration, body = raw.split('\n{\n', 1)
    declaration = replace(declaration, name + '(', 'lsf_prepaid_' + name + '(')
    if name == 'tcp_stream_alloc_skb':
        body = replace(body, '\tstruct sk_buff *skb;\n',
            '\tstruct sk_buff *skb;\n\tstruct lsf_factory_blob parent;\n'
            '\tstruct lsf_prepaid_ticket ticket = {\n'
            '\t\t.slot = sk->sk_lsf_view_slot,\n'
            '\t\t.generation = sk->sk_lsf_view_generation,\n\t};\n')
        body = replace(body, '\tskb = alloc_skb_fclone(MAX_TCP_HEADER, gfp);\n',
            '\t(void)gfp;\n'
            '\tif (!lsf_factory_protocol_parent(sk, sk->sk_lsf_factory, ticket, &parent))\n'
            '\t\treturn NULL;\n'
            '\tskb = lsf_prepaid_packet_skb_new(parent, MAX_TCP_HEADER + LSF_PACKET_LINEAR_BYTES);\n')
    else:
        # All ordinary Linux wait/connect/copy-error/sequence/push logic remains.
        # Reject unsupported allocating alternatives before any original call.
        body = replace(body, '\tflags = msg->msg_flags;\n',
            '\tflags = msg->msg_flags;\n'
            '\tif (!sk->sk_lsf_factory || msg->msg_controllen || msg->msg_ubuf ||\n'
            '\t    (flags & ~(MSG_DONTWAIT | MSG_NOSIGNAL | MSG_MORE | MSG_EOR)) ||\n'
            '\t    inet_test_bit(DEFER_CONNECT, sk) || tp->repair || tcp_passive_fastopen(sk))\n'
            '\t\treturn -EOPNOTSUPP;\n')
        # There are two indentation levels; each resumed route/MSS gets checked.
        for indent in ('\t', '\t\t'):
            old = indent + 'mss_now = tcp_send_mss(sk, &size_goal, flags);\n'
            new = old + indent + 'if (mss_now <= 0 || size_goal != mss_now ||\n'
            new += indent + '    mss_now > (int)LSF_PACKET_LINEAR_BYTES) {\n'
            new += indent + '\terr = -EOPNOTSUPP;\n' + indent + '\tgoto do_error;\n' + indent + '}\n'
            # Prefix match only at a line start avoids selecting the nested site twice.
            before = '\n' + old
            body = replace(body, before, '\n' + new)
        start = body.index('\t\tif (zc == 0) {\n')
        stop = body.index('\t\t} else if (zc == MSG_ZEROCOPY)', start)
        original = body[start:stop]
        require('skb_copy_to_page_nocache(' in original and 'sk_page_frag_refill(' in original
            and 'page_ref_inc(' in original, 'packet-original-page-copy-shape')
        selected = ('\t\tif (zc == 0) {\n'
            '\t\t\tstruct lsf_factory_blob birth;\n'
            '\t\t\tint owned = lsf_factory_packet_birth(skb, LSF_PREPAID_PACKET_SKB, &birth);\n'
            '\t\t\tif (owned != 1 || !lsf_prepaid_packet_linear(skb, birth) ||\n'
            '\t\t\t    skb_tailroom(skb) < copy) {\n'
            '\t\t\t\terr = -EOPNOTSUPP;\n\t\t\t\tgoto do_error;\n\t\t\t}\n'
            '\t\t\t/* The complete linear head was charged by tcp_skb_entail.\n'
            '\t\t\t * Do not double-charge copied bytes as new page fragments. */\n'
            '\t\t\terr = skb_add_data_nocache(sk, skb, &msg->msg_iter, copy);\n'
            '\t\t\tif (err)\n\t\t\t\tgoto do_error;\n')
        body = body[:start] + selected + body[stop:]
        body = replace(body, 'skb = tcp_stream_alloc_skb(', 'skb = lsf_prepaid_tcp_stream_alloc_skb(')
    return declaration + '\n{\n' + body


def packet_routing(raw, name):
    """Extend only the existing private dispatcher; normal bodies stay exact."""
    if name in ('skb_kfree_head', 'kfree_skbmem', 'napi_skb_cache_put', 'kfree_skb_add_bulk'):
        address = 'head' if name == 'skb_kfree_head' else 'skb'
        kind = 'HEAD' if name == 'skb_kfree_head' else 'SKB'
        old = f'\tif (lsf_prepaid_audit_return({address}, LSF_PREPAID_AUDIT_{kind}))\n'
        new = f'\tif (lsf_prepaid_packet_return({address}, LSF_PREPAID_PACKET_{kind}))\n\t\treturn;\n' + old
        return replace(raw, old, new)
    if name == 'kfree_skb_partial':
        return replace(raw,
            '\t\tif (!lsf_prepaid_audit_return(skb, LSF_PREPAID_AUDIT_SKB))\n',
            '\t\tif (!lsf_prepaid_packet_return(skb, LSF_PREPAID_PACKET_SKB) &&\n'
            '\t\t    !lsf_prepaid_audit_return(skb, LSF_PREPAID_AUDIT_SKB))\n')
    old = ('\tstruct lsf_factory_blob birth;\n'
        '\tint owned = lsf_factory_blob_lookup(skb, LSF_PREPAID_AUDIT_SKB, &birth);\n')
    new = ('\tstruct lsf_factory_blob birth, packet_birth;\n'
        '\tint owned, packet_owned = lsf_factory_packet_birth(skb, LSF_PREPAID_PACKET_SKB, &packet_birth);\n')
    if name in ('skb_clone', 'pskb_expand_head'):
        action = 'lsf_prepaid_packet_clone(skb, packet_birth)' if name == 'skb_clone' else \
            'lsf_prepaid_packet_expand(skb, nhead, ntail, packet_birth)'
        refusal = 'NULL' if name == 'skb_clone' else '-EOPNOTSUPP'
        new += ('\tif (packet_owned)\n'
            f'\t\treturn packet_owned < 0 ? {refusal} : {action};\n'
            '\towned = lsf_factory_blob_lookup(skb, LSF_PREPAID_AUDIT_SKB, &birth);\n')
        return replace(raw, old, new)
    require(name == 'skb_copy', 'packet-dispatch-name')
    new += ('\tif (packet_owned < 0 || (packet_owned && !lsf_prepaid_packet_linear(skb, packet_birth)))\n'
        '\t\treturn NULL;\n'
        '\towned = packet_owned ? 0 : lsf_factory_blob_lookup(skb, LSF_PREPAID_AUDIT_SKB, &birth);\n')
    text = replace(raw, old, new)
    return replace(text,
        '\tif (owned)\n\t\tn = lsf_prepaid_audit_skb_new(birth, size);\n',
        '\tif (packet_owned)\n\t\tn = lsf_prepaid_packet_skb_new(packet_birth, size);\n'
        '\telse if (owned)\n\t\tn = lsf_prepaid_audit_skb_new(birth, size);\n')



CONTROL_ALLOCATORS = ('tcp_send_fin', 'tcp_send_active_reset', '__tcp_send_ack',
    'tcp_xmit_probe_skb', 'tcp_collapse')


def control(raw, name):
    """Keep real TCP control/queue logic; select only its protected producer."""
    import re
    require(name in CONTROL_ALLOCATORS and section(raw, name) == raw,
        'packet-control-preimage')
    pattern = r'(?m)^([\t ]+)([a-z_]+) = (alloc_skb(?:_fclone)?)\('
    matches = list(re.finditer(pattern, raw))
    require(len(matches) == 1, 'packet-control-constructor-occurrence')
    match = matches[0]
    start = match.end() - 1
    depth, stop = 0, None
    for i in range(start, len(raw)):
        if raw[i] == '(':
            depth += 1
        elif raw[i] == ')':
            depth -= 1
            if depth == 0:
                stop = i + 1
                break
    require(stop is not None and raw[stop:stop + 2] == ';\n',
        'packet-control-constructor-end')
    arguments = raw[start + 1:stop - 1]
    size = arguments.split(',', 1)[0]
    require(size in ('MAX_TCP_HEADER', 'copy'), 'packet-control-constructor-size')
    indent, variable = match.group(1), match.group(2)
    original = raw[match.start():stop + 2]
    selected = ('#ifdef LSF_STREAM_PACKET_SOURCE\n' + indent + 'if (sk->sk_lsf_factory)\n' +
        indent + '\t' + variable + ' = lsf_prepaid_packet_alloc_sock(sk, ' + size + ');\n' +
        indent + 'else\n#endif\n' + original)
    text = raw[:match.start()] + selected + raw[stop + 2:]
    if name == 'tcp_collapse':
        # RX remains incomplete: never silently inherit an unowned/foreign
        # queue packet merely because its consumer is a protected socket.
        text = replace(text,'\t\tn = tcp_skb_next(skb, list);\n',
            '#ifdef LSF_STREAM_PACKET_SOURCE\n'
            '\t\tif (sk->sk_lsf_factory && !lsf_prepaid_packet_for_sock(skb, sk))\n'
            '\t\t\treturn;\n#endif\n'
            '\t\tn = tcp_skb_next(skb, list);\n'
            '#ifdef LSF_STREAM_PACKET_SOURCE\n'
            '\t\tif (sk->sk_lsf_factory && n && n != tail &&\n'
            '\t\t    !lsf_prepaid_packet_for_sock(n, sk))\n'
            '\t\t\treturn;\n#endif\n')
        for indent, action in (('\t\t\t','return'), ('\t\t\t\t','goto end')):
            old = indent+'skb = tcp_collapse_one(sk, skb, list, root);\n'
            guard = ('#ifdef LSF_STREAM_PACKET_SOURCE\n'+indent+
                'if (sk->sk_lsf_factory && skb && skb != tail &&\n'+indent+
                '    !lsf_prepaid_packet_for_sock(skb, sk))\n'+indent+'\t'+action+
                ';\n#endif\n')
            text = replace(text,'\n'+old,'\n'+old+guard)
    return text


def copy_private(raw, name):
    """Use the real maintained copy tail after proving an owned linear source."""
    require(name in COPIES and section(raw, name) == raw, 'packet-copy-preimage')
    declaration, body = raw.split('\n{\n',1)
    declaration = 'static ' + replace(declaration, name+'(', 'lsf_prepaid_'+name+'(')
    declaration = replace(declaration, ')', ', struct lsf_factory_blob birth)',1)
    if name == '__pskb_copy_fclone':
        old = ('\tunsigned int size = skb_headlen(skb) + headroom;\n'
            '\tint flags = skb_alloc_rx_flag(skb) | (fclone ? SKB_ALLOC_FCLONE : 0);\n'
            '\tstruct sk_buff *n = __alloc_skb(size, gfp_mask, flags, NUMA_NO_NODE);\n')
        new = ('\tunsigned long requested;\n\tstruct sk_buff *n;\n'
            '\t(void)gfp_mask;\n\t(void)fclone;\n'
            '\tif (headroom < 0 || !lsf_prepaid_packet_linear(skb, birth))\n'
            '\t\treturn NULL;\n'
            '\trequested = (unsigned long)skb_headlen(skb) + (unsigned int)headroom;\n'
            '\tif (requested > LSF_TCP_BYTES)\n\t\treturn NULL;\n'
            '\tn = lsf_prepaid_packet_skb_new(birth, (unsigned int)requested);\n')
        body = replace(body,old,new)
    else:
        old = '\tint oldheadroom;\n'
        body = replace(body,old,old+'\tunsigned long requested;\n'
            '\t(void)gfp_mask;\n'
            '\tif (newheadroom < 0 || newtailroom < 0 ||\n'
            '\t    !lsf_prepaid_packet_linear(skb, birth))\n\t\treturn NULL;\n'
            '\trequested = (unsigned long)(unsigned int)newheadroom + skb->len +\n'
            '\t\t(unsigned int)newtailroom;\n'
            '\tif (requested > LSF_TCP_BYTES)\n\t\treturn NULL;\n')
        body = replace(body,'\tn = __alloc_skb(newheadroom + skb->len + newtailroom,\n'
            '\t\t\tgfp_mask, skb_alloc_rx_flag(skb),\n\t\t\tNUMA_NO_NODE);\n',
            '\tn = lsf_prepaid_packet_skb_new(birth, (unsigned int)requested);\n')
    return declaration+'\n{\n'+body


def copy_helpers(text):
    """Define private copies only after their retained static dependency."""
    raw = section(text, 'skb_zerocopy_clone')
    return replace(text, raw, raw + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "../packet-copy-private.c"\n#endif\n')


def copy_routing(raw, name):
    require(name in COPIES and section(raw,name)==raw,'packet-copy-dispatch-preimage')
    declaration, body = raw.split('\n{\n',1)
    arguments = 'skb, headroom, gfp_mask, fclone, birth' if name=='__pskb_copy_fclone' else \
        'skb, newheadroom, newtailroom, gfp_mask, birth'
    selected = (declaration+'\n{\n\tstruct lsf_factory_blob birth;\n'
        '\tint owned = lsf_factory_packet_birth(skb, LSF_PREPAID_PACKET_SKB, &birth);\n'
        '\tif (owned)\n\t\treturn owned < 0 ? NULL : lsf_prepaid_'+name+'('+arguments+');\n'
        '\t{\n'+body+'}\n')
    return '#ifdef LSF_STREAM_PACKET_SOURCE\n'+selected+'#else\n'+raw+'#endif\n'


def unsupported_entry(raw, name):
    require(section(raw, name) == raw, 'packet-unsupported-preimage')
    if name == 'inet_listen':
        guard, refused = 'sock->sk && sock->sk->sk_lsf_factory', '-EOPNOTSUPP'
    elif name == 'tcp_make_synack':
        guard, refused = 'sk->sk_lsf_factory', 'NULL'
    elif name in ('tcp_send_syn_data', 'tcp_send_rcvq'):
        guard, refused = 'sk->sk_lsf_factory', '-EOPNOTSUPP'
    else:
        require(name == 'tcp_connect', 'packet-unsupported-name')
        guard = ('sk->sk_lsf_factory && (tcp_sk(sk)->fastopen_req ||\n'
            '\t    inet_test_bit(DEFER_CONNECT, sk) || tcp_sk(sk)->repair)')
        refused = '-EOPNOTSUPP'
    declaration, body = raw.split('\n{\n', 1)
    # A fresh inner block preserves original declaration and label scope without
    # introducing declaration-after-statement warnings in real Kbuild.
    selected = declaration + '\n{\n\tif (' + guard + ')\n\t\treturn ' + refused + ';\n\t{\n' + body + '}\n'
    return '#ifdef LSF_STREAM_PACKET_SOURCE\n' + selected + '#else\n' + raw + '#endif\n'

def derive(inputs):
    authenticate(inputs)
    from tools import host_stream_kernel_audit_skb as audit
    outputs = prior.derive({name: inputs[name] for name in prior.fixture()['source']})
    for name in set(inputs) - set(prior.fixture()['source']):
        outputs[name] = inputs[name]
    text = outputs['net/prepaid.h'].decode()
    text = replace(text, '    LSF_PREPAID_ROUTE\n',
        '    LSF_PREPAID_ROUTE, LSF_PREPAID_PACKET_SKB, LSF_PREPAID_PACKET_HEAD\n')
    text = replace(text, 'kind != LSF_PREPAID_ROUTE)',
        'kind != LSF_PREPAID_ROUTE && kind != LSF_PREPAID_PACKET_SKB &&\n'
        '         kind != LSF_PREPAID_PACKET_HEAD)', 3)
    outputs['net/prepaid.h'] = text.encode()
    text = outputs['net/factory-private.h'].decode()
    text = replace(text, '#include "prepaid.h"\n',
        '#include "prepaid.h"\n#include <net/lsf_stream_packet_private.h>\n')
    outputs['net/factory-private.h'] = text.encode()
    outputs['net/factory.c'] += b'\n#include "packet-factory.c"\n'
    outputs['include/net/lsf_stream_packet_private.h'] = (OWNED/'packet-private.h').read_bytes()
    for source, target in (('packet-factory.c','net/packet-factory.c'),
        ('packet-skb-private.c','net/packet-skb-private.c')):
        outputs[target] = (OWNED/source).read_bytes()
    text = outputs[audit.SKBUFF].decode()
    for name in sorted(audit.NAMES - {'__skb_clone'}):
        original = audit.section(inputs[audit.SKBUFF].decode(), name)
        previous = audit.routed(original, name)
        text = replace(text, previous, packet_routing(previous, name))
    text = replace(text, 'static int lsf_prepaid_audit_return(const void *, unsigned int);\n',
        'static int lsf_prepaid_audit_return(const void *, unsigned int);\n'
        'static int lsf_prepaid_packet_return(const void *, unsigned int);\n')
    text = replace(text, '#include "../audit-skb-private.c"\n',
        '#include "../audit-skb-private.c"\n#include "../packet-skb-private.c"\n')
    copies = ''
    for name in COPIES:
        raw = section(inputs[audit.SKBUFF].decode(),name)
        copies += copy_private(raw,name)+'\n'
        text = replace(text,raw,copy_routing(raw,name))
    outputs['net/packet-copy-private.c'] = copies.encode()
    outputs[audit.SKBUFF] = copy_helpers(text).encode()
    original = inputs[TCP].decode()
    text = original
    declarations = ''
    clones = ''
    for name in CLONES:
        raw = section(original, name)
        selected = private(raw, name)
        declarations += selected.split('\n{\n', 1)[0] + ';\n'
        clones += selected + '\n'
        declaration, body = raw.split('\n{\n',1)
        guarded = declaration+'\n{\n\tif (sk->sk_lsf_factory)\n'
        guarded += f'\t\treturn lsf_prepaid_{name}('
        guarded += 'sk, gfp, force_schedule' if name == 'tcp_stream_alloc_skb' else 'sk, msg, size'
        guarded += ');\n\t{\n'+body+'}\n'
        # Keep the entire original definition as the unselected branch.
        text = replace(text, raw, '#ifdef LSF_STREAM_PACKET_SOURCE\n' + guarded +
            '#else\n' + raw + '#endif\n')
    text = replace(text, '#include "../core/devmem.h"\n',
        '#include "../core/devmem.h"\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "../factory-private.h"\n' + declarations + '#endif\n')
    text += '\n#ifdef LSF_STREAM_PACKET_SOURCE\n' + clones + '#endif\n'
    outputs[TCP] = text.encode()
    controls = {name:fixture()['sections'][name]['source'] for name in CONTROL_ALLOCATORS}
    entries = {name:fixture()['sections'][name]['source'] for name in
        ('inet_listen','tcp_make_synack','tcp_send_syn_data','tcp_send_rcvq','tcp_connect')}
    for name, path in controls.items():
        raw = section(inputs[path].decode(), name)
        outputs[path] = replace(outputs[path].decode(), raw, control(raw, name)).encode()
    for name, path in entries.items():
        raw = section(inputs[path].decode(), name)
        outputs[path] = replace(outputs[path].decode(), raw, unsupported_entry(raw, name)).encode()
    for path, anchor in (('net/ipv4/tcp_output.c','#include <trace/events/tcp.h>\n'),
        ('net/ipv4/tcp_input.c','#include <net/mptcp.h>\n'),
        ('net/ipv4/af_inet.c','#include <net/tcp.h>\n')):
        outputs[path] = replace(outputs[path].decode(), anchor,
            anchor + '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '#include <net/lsf_stream_packet_private.h>\n#endif\n').encode()
    return outputs
