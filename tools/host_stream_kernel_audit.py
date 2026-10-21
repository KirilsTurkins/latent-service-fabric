"""Maintain real AVC audit selection, formatter status and SKB queue transfer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from tools import host_stream_kernel_audit_skb as skb

maintained = skb.maintained
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_audit.json'
AUDIT = 'kernel/audit.c'
LSM = 'security/lsm_audit.c'
AVC = 'security/selinux/avc.c'
NAMES = frozenset(('audit_buffer_free', 'audit_log_start', 'audit_expand',
    'audit_log_vformat', 'audit_log_end', 'avc_audit_post_callback',
    'slow_avc_audit', 'avc_audit', 'avc_audit_pre_callback', 'avc_audit_required',
    'common_lsm_audit', 'dump_common_audit_data'))


def require(value, reason):
    if not value:
        raise ValueError('kernel-audit-' + reason)


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    require(value['upstreamCommit'] == maintained.COMMIT and
        value['archiveSha256'] == maintained.manifest()['archive']['sha256'], 'upstream')
    require(set(value['source']) == set(skb.fixture()['source']) | {AUDIT, LSM} and
        set(value['sections']) == NAMES, 'source-membership')
    require(all(value[key] is False for key in ('kernelBuilt', 'actualAuditExecuted',
        'actualLinuxRcuExecuted', 'completeAllocationClosure', 'productionInstallation')),
        'uninstalled-only')
    return value


def section(text, name):
    row = fixture()['sections'][name]
    starts = [i for i in range(len(text)) if text.startswith(row['prefix'], i) and
        (not i or text[i-1] == '\n')]
    require(len(starts) == 1, 'definition-occurrence')
    end = text.find('\n}\n', starts[0])
    require(end >= 0, 'definition-end')
    raw = text[starts[0]:end+3]
    require(len(raw.encode()) == row['bytes'] and
        hashlib.sha256(raw.encode()).hexdigest() == row['sha256'], 'definition-preimage')
    return raw


def replace(text, before, after, count=1):
    require(text.count(before) == count, 'replacement-preimage')
    return text.replace(before, after)


def observed(raw, name):
    require(section(raw, name) == raw, 'observed-preimage')
    if name == 'audit_buffer_free':
        return replace(raw, '{\n', '{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tif (lsf_prepaid_audit_buffer_free(ab))\n\t\treturn;\n#endif\n')
    if name == 'audit_expand':
        return replace(raw, '\tif (ret < 0) {\n', '\tif (ret < 0) {\n'
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t\tlsf_prepaid_audit_error(ab, ret);\n#endif\n')
    require(name == 'audit_log_vformat', 'observed-name')
    text = replace(raw, '\tlen = vsnprintf(skb_tail_pointer(skb), avail, fmt, args);\n',
        '\tlen = vsnprintf(skb_tail_pointer(skb), avail, fmt, args);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (len < 0)\n'
        '\t\tlsf_prepaid_audit_error(ab, len);\n#endif\n')
    return replace(text, '\t\tlen = vsnprintf(skb_tail_pointer(skb), avail, fmt, args2);\n',
        '\t\tlen = vsnprintf(skb_tail_pointer(skb), avail, fmt, args2);\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\t\tif (len < 0)\n'
        '\t\t\tlsf_prepaid_audit_error(ab, len);\n#endif\n')


def argument(raw, addition):
    declaration, body = raw.split('\n{\n', 1)
    require(declaration.endswith(')'), 'function-declaration')
    return declaration[:-1] + addition + ')\n{\n' + body


def private(raw, name):
    require(section(raw, name) == raw, 'private-preimage')
    if name == 'audit_log_start':
        text = replace(raw, '*audit_log_start(', '*lsf_prepaid_audit_log_start(')
        text = argument(text, ', const struct lsf_factory_blob *source, int *error')
        text = replace(text, '\tunsigned int serial;\n', '\tunsigned int serial;\n'
            '\tif (!error)\n\t\treturn NULL;\n'
            '\t*error = source ? 0 : -EOPNOTSUPP;\n\tif (!source)\n\t\treturn NULL;\n')
        text = replace(text, 'ab = audit_buffer_alloc(ctx, gfp_mask, type);',
            'ab = lsf_prepaid_audit_buffer_alloc(ctx, gfp_mask, type, source);')
        return replace(text, '\t\taudit_log_lost("out of memory in audit_log_start");\n',
            '\t\taudit_log_lost("out of memory in audit_log_start");\n\t\t*error = -ENOMEM;\n')
    if name == 'audit_log_end':
        text = replace(raw, 'void audit_log_end(', 'int lsf_prepaid_audit_log_end(')
        text = argument(text, ', int error')
        text = replace(text, '\tstruct nlmsghdr *nlh;\n', '\tstruct nlmsghdr *nlh;\n'
            '\tstruct lsf_factory_blob birth;\n\tint status;\n')
        text = replace(text, '\tif (!ab)\n\t\treturn;\n',
            '\tif (!ab || lsf_factory_blob_lookup(ab, LSF_PREPAID_AUDIT_BUFFER, &birth) != 1)\n'
            '\t\treturn -EOPNOTSUPP;\n'
            '\tstatus = ((struct lsf_prepaid_audit_envelope *)ab)->error;\n'
            '\tif (status)\n\t\terror = status;\n'
            '\tif (error) {\n\t\tlsf_prepaid_audit_buffer_free(ab);\n'
            '\t\treturn error < 0 ? error : -EIO;\n\t}\n')
        text = replace(text, '\t} else\n\t\taudit_log_lost("rate limit exceeded");',
            '\t} else {\n\t\taudit_log_lost("rate limit exceeded");\n'
            '\t\terror = -EAGAIN;\n\t}')
        return replace(text, '\taudit_buffer_free(ab);',
            '\tstatus = lsf_prepaid_audit_buffer_free(ab);\n'
            '\treturn status == 1 ? error : -EOPNOTSUPP;')
    if name == 'avc_audit_post_callback':
        text = replace(raw, 'static void avc_audit_post_callback(',
            'static int lsf_prepaid_avc_post(')
        text = argument(text, ', const struct lsf_factory_blob *source')
        text = replace(text, '\tint rc;\n', '\tint rc;\n\tint error = 0;\n')
        for function, flag, expected in (('security_sid_to_context', 0, 2),
                                        ('security_sid_to_context_inval', 1, 2)):
            pattern = re.compile(r'\b' + function + r'\((.*?)\)', re.S)
            require(len(pattern.findall(text)) == expected, 'context-call-count')
            text = pattern.sub(lambda m: 'lsf_prepaid_security_sid_to_context('+m[1]+f', {flag}, source)', text)
        pattern = re.compile(r'rc = lsf_prepaid_security_sid_to_context\(.*?\);', re.S)
        require(len(pattern.findall(text)) == 4, 'context-status-count')
        text = pattern.sub(lambda m: m[0]+'\n\tif (rc && rc != -EINVAL && !error)\n\t\terror = rc;', text)
        for pointer, count in (('scontext', 3), ('tcontext', 1)):
            text = replace(text, f'kfree({pointer});',
                f'if ({pointer} && lsf_prepaid_audit_string_return({pointer}) != 1 && !error)\n'
                '\t\terror = -EOPNOTSUPP;', count)
        return text[:-2]+'\treturn error;\n}\n'
    if name == 'slow_avc_audit':
        text = replace(raw, 'noinline int slow_avc_audit(',
            'static noinline int lsf_prepaid_slow_avc_audit(')
        text = argument(text, ', const struct lsf_factory_blob *source')
        return replace(text, '\tcommon_lsm_audit(a, avc_audit_pre_callback, avc_audit_post_callback);\n\treturn 0;',
            '\treturn lsf_prepaid_common_lsm_audit(a, avc_audit_pre_callback,\n'
            '\t\t\tlsf_prepaid_avc_post, source);')
    require(name == 'avc_audit', 'private-name')
    text = replace(raw, 'static inline int avc_audit(', 'int lsf_prepaid_avc_audit(')
    text = argument(text, ', const struct lsf_factory_blob *source')
    text = replace(text, '\tu32 audited, denied;\n', '\tu32 audited, denied;\n'
        '\tif (!source)\n\t\treturn -EOPNOTSUPP;\n')
    return replace(text, 'return slow_avc_audit(ssid, tsid, tclass, requested, audited, denied,\n'
        '\t\t\t      result, a);',
        'return lsf_prepaid_slow_avc_audit(ssid, tsid, tclass, requested, audited, denied,\n'
        '\t\t\t      result, a, source);')


def authenticate(inputs):
    value = fixture()
    maintained.authenticate_files(inputs, value['source'])
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)
    layout = value['auditBufferDefinition']
    require(hashlib.sha256(layout['text'].encode()).hexdigest() == layout['sha256'] and
        inputs[AUDIT].decode().count(layout['text']) == 1, 'audit-buffer-layout-preimage')


def derive(inputs):
    authenticate(inputs)
    outputs = skb.derive({name: inputs[name] for name in skb.fixture()['source']})
    original = {name:inputs[name].decode() for name in (AUDIT, LSM, AVC)}
    audit = original[AUDIT]
    for name in ('audit_buffer_free', 'audit_expand', 'audit_log_vformat'):
        raw = section(original[AUDIT], name)
        audit = replace(audit, raw, observed(raw, name))
    layout = fixture()['auditBufferDefinition']['text']
    audit = replace(audit, layout, layout+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "../net/audit-buffer-private.c"\n#endif\n')
    include = '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "../net/audit-private.h"\n#endif\n'
    # Retain the maintained translation unit's pr_fmt before any header can
    # supply printk.h's default. The whole authenticated file binds this site.
    audit = replace(audit, '#include "audit.h"\n', '#include "audit.h"\n'+include)
    audit += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
    audit += ''.join(private(section(original[AUDIT], name), name) for name in ('audit_log_start', 'audit_log_end'))
    outputs[AUDIT] = (audit+'#endif\n').encode()
    outputs[LSM] = (include+original[LSM]+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "../net/lsm-audit-private.c"\n#endif\n').encode()
    # Compose over the already derived AVC graph. Never discard its private
    # permission calls, ownership/RCU paths or the SID/Netlabel predecessors.
    avc = outputs[AVC].decode()
    avc += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "../../net/audit-private.h"\n'
    for name in ('avc_audit_post_callback', 'slow_avc_audit'):
        avc += private(section(original[AVC], name), name)
    avc += private(section(inputs['security/selinux/include/avc.h'].decode(), 'avc_audit'), 'avc_audit')
    outputs[AVC] = (avc+'#endif\n').encode()
    for name in ('audit-private.h', 'audit-buffer-private.c', 'lsm-audit-private.c'):
        outputs['net/'+name] = (maintained.ROOT/'research/standard-outbound/linux-6.12-lineage'/name).read_bytes()
    return outputs
