"""Authenticated SID-cache/context-string ownership derivation; uninstalled."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools import host_stream_kernel_netport as netport
from tools import host_stream_kernel_protocol as protocol
from tools import host_stream_kernel_maintained as maintained

FIXTURE = Path(__file__).parent / 'tests/fixtures/host_stream_kernel_sidcache.json'
SIDTAB = 'security/selinux/ss/sidtab.c'
SERVICES = 'security/selinux/ss/services.c'
NAMES = frozenset(('sidtab_destroy_entry', 'sidtab_sid2str_put', 'sidtab_sid2str_get',
    'context_struct_to_string', 'sidtab_entry_to_string', 'security_sid_to_context_core'))


def require(value, reason):
    if not value:
        raise ValueError('kernel-sidcache-' + reason)


def fixture():
    value = json.loads(FIXTURE.read_bytes())
    require(value['upstreamCommit'] == maintained.COMMIT and set(value['sections']) == NAMES,
            'definition-membership')
    require(value['archiveSha256'] == maintained.manifest()['archive']['sha256'], 'archive-identity')
    require(set(value['source']) == set(netport.fixture()['source']) | {SIDTAB, SERVICES}, 'source-membership')
    require(all(value[field] is False for field in ('kernelBuilt', 'actualLsmExecuted',
        'completeAllocationClosure', 'productionInstallation')), 'uninstalled-only')
    return value


def replace(text, before, after, count=1):
    require(text.count(before) == count, 'replacement-preimage')
    return text.replace(before, after)


def section(text, name):
    rows = fixture()['sections']
    require(name in rows, 'section-name')
    prefix = rows[name]['prefix']
    starts = [i for i in range(len(text)) if text.startswith(prefix, i) and (not i or text[i-1] == '\n')]
    require(len(starts) == 1, 'section-occurrence')
    end = text.find('\n}\n', starts[0])
    require(end >= 0, 'section-end')
    raw = text[starts[0]:end+3]
    require(hashlib.sha256(raw.encode()).hexdigest() == rows[name]['sha256'], 'section-preimage')
    return raw


def observed(raw, name):
    require(section(raw, name) == raw, 'observed-preimage')
    if name == 'sidtab_destroy_entry':
        return replace(raw, '\tkfree(rcu_dereference_raw(entry->cache));',
            '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tif (!lsf_prepaid_sidcache_destroy(rcu_dereference_raw(entry->cache)))\n#endif\n'
            '\t\tkfree(rcu_dereference_raw(entry->cache));')
    require(name == 'sidtab_sid2str_put', 'observed-name')
    text = replace(raw, '\tunsigned long flags;\n', '\tunsigned long flags;\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tint owned_victim = 0;\n#endif\n')
    text = replace(text, '\t\tlist_del(&victim->lru_member);',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t\towned_victim = lsf_factory_sidcache_queue(victim);\n#endif\n'
        '\t\tlist_del(&victim->lru_member);')
    return replace(text, '\tkfree_rcu(victim, rcu_member);',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tlsf_prepaid_sidcache_retire(victim, owned_victim);\n#else\n'
        '\tkfree_rcu(victim, rcu_member);\n#endif')


def private(raw, name):
    require(section(raw, name) == raw, 'private-preimage')
    if name == 'sidtab_sid2str_put':
        text = replace(raw, 'void sidtab_sid2str_put(', 'int lsf_prepaid_sid2str_put(')
        text = replace(text, 'const char *str, u32 str_len)',
            'const char *str, u32 str_len, const struct lsf_factory_blob *source)')
        text = replace(text, '\tunsigned long flags;\n',
            '\tunsigned long flags;\n\tint result = 0, owned_victim = 0;\n'
            '\tif (!source || !str || !str_len || str_len > LSF_TCP_BYTES)\n'
            '\t\treturn -EOPNOTSUPP;\n')
        text = replace(text, '\t\treturn;\n', '\t\treturn 0;\n')
        text = replace(text, '\tcache = kmalloc(struct_size(cache, str, str_len), GFP_ATOMIC);\n'
            '\tif (!cache)\n\t\tgoto out_unlock;',
            '\tcache = lsf_factory_child_allocate(*source, struct_size(cache, str, str_len),\n'
            '\t\tLSF_PREPAID_SIDCACHE);\n'
            '\tif (!cache) {\n\t\tresult = -ENOMEM;\n\t\tgoto out_unlock;\n\t}\n'
            '\tcache->parent = entry;\n\tcache->len = str_len;\n'
            '\tmemcpy(cache->str, str, str_len);\n'
            '\tif (lsf_factory_sidcache_publish(cache, (lsf_u64)(unsigned long)s) != 1) {\n'
            '\t\tresult = -EOPNOTSUPP;\n\t\tgoto out_unlock;\n\t}')
        text = replace(text, '\t\tlist_del(&victim->lru_member);',
            '\t\towned_victim = lsf_factory_sidcache_queue(victim);\n'
            '\t\tif (owned_victim < 0) {\n\t\t\tvictim = NULL;\n'
            '\t\t\tresult = -EOPNOTSUPP;\n\t\t\tgoto out_unlock;\n\t\t}\n'
            '\t\tlist_del(&victim->lru_member);')
        text = replace(text, '\tcache->parent = entry;\n\tcache->len = str_len;\n'
            '\tmemcpy(cache->str, str, str_len);\n\tlist_add(', '\tlist_add(')
        return replace(text, '\tkfree_rcu(victim, rcu_member);',
            '\tlsf_prepaid_sidcache_retire(victim, owned_victim);\n\treturn result;')
    if name == 'sidtab_sid2str_get':
        text = replace(raw, 'int sidtab_sid2str_get(', 'int lsf_prepaid_sid2str_get(')
        text = replace(text, 'u32 *out_len)', 'u32 *out_len, const struct lsf_factory_blob *source)')
        text = replace(text, '\tint rc = 0;\n', '\tint rc = 0;\n'
            '\tif (!source || !out_len)\n\t\treturn -EOPNOTSUPP;\n')
        text = replace(text, 'kmemdup(cache->str, cache->len, GFP_ATOMIC)',
            'lsf_prepaid_audit_dup(source, cache->str, cache->len)')
        return replace(text, '\tif (!rc && out)\n\t\tsidtab_sid2str_put(s, entry, *out, *out_len);',
            '\tif (!rc && out) {\n'
            '\t\trc = lsf_prepaid_sid2str_put(s, entry, *out, *out_len, source);\n'
            '\t\tif (rc) {\n\t\t\tlsf_prepaid_audit_string_return(*out);\n'
            '\t\t\t*out = NULL;\n\t\t}\n\t}')
    if name == 'context_struct_to_string':
        text = replace(raw, 'context_struct_to_string(', 'lsf_prepaid_context_to_string(')
        text = replace(text, 'u32 *scontext_len)',
            'u32 *scontext_len, const struct lsf_factory_blob *source)')
        text = replace(text, '\tchar *scontextp;\n', '\tchar *scontextp;\n'
            '\tif (!source || !scontext_len)\n\t\treturn -EOPNOTSUPP;\n')
        text = replace(text, 'kstrdup(context->str, GFP_ATOMIC)',
            'lsf_prepaid_audit_dup(source, context->str, strlen(context->str) + 1)')
        return replace(text, 'kmalloc(*scontext_len, GFP_ATOMIC)',
            'lsf_factory_child_allocate(*source, *scontext_len, LSF_PREPAID_AUDIT_STRING)')
    if name == 'sidtab_entry_to_string':
        text = replace(raw, 'sidtab_entry_to_string(', 'lsf_prepaid_entry_to_string(')
        text = replace(text, 'u32 *scontext_len)',
            'u32 *scontext_len, const struct lsf_factory_blob *source)')
        text = replace(text, 'sidtab_sid2str_get(sidtab, entry, scontext, scontext_len)',
            'lsf_prepaid_sid2str_get(sidtab, entry, scontext, scontext_len, source)')
        text = replace(text, 'context_struct_to_string(p, &entry->context, scontext,\n'
            '\t\t\t\t      scontext_len)',
            'lsf_prepaid_context_to_string(p, &entry->context, scontext,\n'
            '\t\t\t\t      scontext_len, source)')
        return replace(text, '\tif (!rc && scontext)\n'
            '\t\tsidtab_sid2str_put(sidtab, entry, *scontext, *scontext_len);',
            '\tif (!rc && scontext) {\n'
            '\t\trc = lsf_prepaid_sid2str_put(sidtab, entry, *scontext, *scontext_len, source);\n'
            '\t\tif (rc) {\n\t\t\tlsf_prepaid_audit_string_return(*scontext);\n'
            '\t\t\t*scontext = NULL;\n\t\t}\n\t}')
    require(name == 'security_sid_to_context_core', 'private-name')
    text = replace(raw, 'static int security_sid_to_context_core(',
        'static int lsf_prepaid_sid_to_context_core(')
    text = replace(text, 'int only_invalid)',
        'int only_invalid, const struct lsf_factory_blob *source)')
    text = replace(text, '\tint rc = 0;\n', '\tint rc = 0;\n'
        '\tif (!source || !scontext_len)\n\t\treturn -EOPNOTSUPP;\n')
    text = replace(text, 'kmemdup(s, *scontext_len, GFP_ATOMIC)',
        'lsf_prepaid_audit_dup(source, s, *scontext_len)')
    return replace(text, 'sidtab_entry_to_string(policydb, sidtab, entry, scontext,\n'
        '\t\t\t\t    scontext_len)',
        'lsf_prepaid_entry_to_string(policydb, sidtab, entry, scontext,\n'
        '\t\t\t\t    scontext_len, source)')


def authenticate(inputs):
    value = fixture()
    require(set(inputs) == set(value['source']), 'whole-source-membership')
    for name, row in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == row['bytes'] <= maintained.MAX_FILE and
            hashlib.sha256(raw).hexdigest() == row['sha256'] and
            hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == row['gitBlob'],
            'whole-source-preimage')
    require(sum(map(len, inputs.values())) <= maintained.MAX_SELECTED, 'source-envelope')
    for name, row in value['sections'].items():
        section(inputs[row['source']].decode(), name)


def derive(inputs):
    authenticate(inputs)
    outputs = netport.derive({name: inputs[name] for name in netport.fixture()['source']})
    original = {name: inputs[name].decode() for name in (SIDTAB, SERVICES)}
    # Earlier selected NetLabel services additions remain byte-bound. This
    # stage adds context-string ownership to that derived TU, not a fresh
    # copy of the original which would discard those real producers.
    texts = {name: outputs.get(name, inputs[name]).decode() for name in (SIDTAB, SERVICES)}
    for name in ('sidtab_destroy_entry', 'sidtab_sid2str_put'):
        raw = section(original[SIDTAB], name)
        texts[SIDTAB] = replace(texts[SIDTAB], raw, observed(raw, name))
    include = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "../../../net/factory-private.h"\n'
        '#include <net/lsf_stream_sidcache_private.h>\n#endif\n')
    for source in (SIDTAB, SERVICES):
        texts[source] = replace(texts[source], '#include "services.h"\n', '#include "services.h"\n' + include)
    texts[SIDTAB] = replace(texts[SIDTAB], 'static void sidtab_destroy_entry(',
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf_sidcache_private.c"\n#endif\n\n'
        'static void sidtab_destroy_entry(')
    texts[SIDTAB] += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#if CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE > 0\n'
    for name in ('sidtab_sid2str_put', 'sidtab_sid2str_get'):
        texts[SIDTAB] += private(section(original[SIDTAB], name), name)
    texts[SIDTAB] += '#else\n'
    for name, arguments in (
        ('put', 'const char *str, u32 str_len'), ('get', 'char **out, u32 *out_len')):
        unused = '(void)str; (void)str_len;' if name == 'put' else '(void)out; (void)out_len;'
        texts[SIDTAB] += ('int lsf_prepaid_sid2str_' + name + '(struct sidtab *s, struct sidtab_entry *entry, '
            + arguments + ', const struct lsf_factory_blob *source)\n{\n'
            '\t(void)s; (void)entry; (void)source; ' + unused + '\n\treturn -EOPNOTSUPP;\n}\n')
    texts[SIDTAB] += '#endif\n#endif\n'
    texts[SERVICES] += '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf_audit_string_private.c"\n'
    for name in ('context_struct_to_string', 'sidtab_entry_to_string', 'security_sid_to_context_core'):
        texts[SERVICES] += private(section(original[SERVICES], name), name)
    texts[SERVICES] += ('int lsf_prepaid_security_sid_to_context(u32 sid, char **out, u32 *length,\n'
        '    int only_invalid, const struct lsf_factory_blob *source)\n{\n'
        '\tif (only_invalid != 0 && only_invalid != 1)\n\t\treturn -EOPNOTSUPP;\n'
        '\treturn lsf_prepaid_sid_to_context_core(sid, out, length, only_invalid, only_invalid, source);\n}\n'
        '#endif\n')
    outputs.update({name: text.encode() for name, text in texts.items()})
    for output, owned in (
        ('include/net/lsf_stream_sidcache_private.h', 'sidcache-private.h'),
        ('security/selinux/ss/lsf_sidcache_private.c', 'sidcache-private.c'),
        ('security/selinux/ss/lsf_audit_string_private.c', 'audit-string-private.c')):
        outputs[output] = (protocol.OWNED/owned).read_bytes()
    return outputs


def reference_body():
    value = fixture()
    factory = (protocol.OWNED/'factory.c').read_text()
    body = ''
    for name in ('lsf_factory_sidcache_publish', 'lsf_factory_sidcache_queue',
                 'lsf_factory_sidcache_destroy', 'lsf_factory_sidcache_candidate',
                 'lsf_factory_sidcache_current'):
        prefix = 'int ' + name + '('
        require(factory.count(prefix) == 1, 'reference-factory-definition')
        begin = factory.index(prefix)
        body += factory[begin:factory.index('\n}\n', begin)+3]
    helper = (protocol.OWNED/'audit-string-private.c').read_text()
    body += helper[:helper.index('void lsf_prepaid_sidcache_drain(')]
    body += (protocol.OWNED/'sidcache-private.c').read_text()
    for name in ('sidtab_destroy_entry', 'sidtab_sid2str_put'):
        raw = value['sections'][name]['text']
        body += observed(raw, name)
    for name in ('sidtab_sid2str_put', 'sidtab_sid2str_get'):
        body += private(value['sections'][name]['text'], name)
    return body.encode()
