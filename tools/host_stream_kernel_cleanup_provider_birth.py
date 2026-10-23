"""Closed provider pool-IDR source: existing cells only, no node allocation.

These definitions do not construct a Task or select the executor consumer.
"""
import hashlib
import json
from pathlib import Path
from tools import host_stream_kernel_cleanup_provider_executor as prior

OWNED = prior.OWNED
require = prior.require
replace = prior.replace
FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_cleanup_provider_birth.json'
FIXTURE_SHA = '1a4563111a9dd305b7baa80ee77cc20bb58086c6db236598f2267409389e2272'


def preimages():
    raw = FIXTURE.read_bytes()
    require(len(raw) <= 40 * 1024 and hashlib.sha256(raw).hexdigest() == FIXTURE_SHA,
        'cleanup-provider-birth-fixed-source')
    value = json.loads(raw)
    require(value['schemaVersion'] == 'lsf.kernel-cleanup-provider-birth-source.v1' and
        value['upstreamCommit'] == prior.preimages()['upstreamCommit'] and
        len(value['source']) == 4 and len(value['sections']) == 5 and len(value['parentDerived']) == 5 and
        all(value[key] is False for key in ('taskCreated', 'poolCreated', 'poolIdrAllocationExecuted',
            'actualRcuExecution', 'fullConstructorClosure', 'productionInstallation')),
        'cleanup-provider-birth-source-origin')
    return value


def authenticate(inputs):
    value = preimages()
    require(set(inputs) == set(value['source']), 'cleanup-provider-birth-whole-membership')
    for name, expected in value['source'].items():
        raw = inputs[name]
        require(type(raw) is bytes and len(raw) == expected['bytes'] and
            hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == expected['gitBlob'],
            'cleanup-provider-birth-whole-source')
    for expected in value['sections'].values():
        raw = expected['text'].encode()
        require(len(raw) == expected['bytes'] and hashlib.sha256(raw).hexdigest() == expected['sha256'] and
            inputs[expected['source']].decode().count(expected['text']) == 1,
            'cleanup-provider-birth-definition-preimage')


def definition(name):
    return preimages()['sections'][name]['text']


def private_radix():
    # Retain the maintained complete search/extend algorithm. Its only node
    # allocation leaf is closed, rather than a GFP flag which still allocates.
    text = '''static struct radix_tree_node *
lsf_provider_no_radix_node(gfp_t gfp, struct radix_tree_node *parent,
    struct radix_tree_root *root, unsigned int shift, unsigned int offset,
    unsigned int count, unsigned int nr_values)
{
    (void)gfp; (void)parent; (void)root; (void)shift; (void)offset;
    (void)count; (void)nr_values;
    return NULL;
}
'''
    extend = replace(definition('radix_tree_extend'),
        'static int radix_tree_extend(', 'static int lsf_provider_radix_extend(')
    extend = replace(extend, 'radix_tree_node_alloc(gfp, NULL,',
        'lsf_provider_no_radix_node(gfp, NULL,')
    free = replace(definition('idr_get_free'), 'void __rcu **idr_get_free(struct radix_tree_root *root,',
        'void __rcu **lsf_prepaid_cleanup_provider_pool_idr_get_free(\n'
        '    struct lsf_cleanup_task_source source, const void *pool, struct radix_tree_root *root,')
    free = replace(free, '\n grow:\n',
        '\n\tif (!lsf_prepaid_cleanup_provider_pool_idr_current(source, root, pool))\n'
        '\t\treturn ERR_PTR(-EOPNOTSUPP);\n\n grow:\n')
    free = replace(free, 'radix_tree_extend(root, gfp, start, shift)',
        'lsf_provider_radix_extend(root, gfp, start, shift)')
    free = replace(free, 'radix_tree_node_alloc(gfp, node, root, shift,',
        'lsf_provider_no_radix_node(gfp, node, root, shift,')
    return text+'\n'+extend+'\n'+free


def private_idr():
    text = replace(definition('idr_alloc_u32'),
        'int idr_alloc_u32(struct idr *idr, void *ptr, u32 *nextid,',
        'static int lsf_provider_pool_idr_alloc_u32(struct lsf_cleanup_task_source source,\n'
        '    struct idr *idr, void *ptr, u32 *nextid,')
    text = replace(text, '\tunsigned int base = idr->idr_base;\n\tunsigned int id = *nextid;\n',
        '\tunsigned int base, id;\n\n'
        '\tif (!lsf_prepaid_cleanup_provider_pool_idr_current(source, &idr->idr_rt, ptr))\n'
        '\t\treturn -EOPNOTSUPP;\n'
        '\tbase = idr->idr_base;\n\tid = *nextid;\n')
    text = replace(text, 'idr_get_free(&idr->idr_rt, &iter, gfp, max - base)',
        'lsf_prepaid_cleanup_provider_pool_idr_get_free(source, ptr, &idr->idr_rt, &iter, gfp, max - base)')
    alloc = replace(definition('idr_alloc'),
        'int idr_alloc(struct idr *idr, void *ptr, int start, int end, gfp_t gfp)',
        'int lsf_prepaid_cleanup_provider_pool_idr_alloc(struct lsf_cleanup_task_source source,\n'
        '    struct idr *idr, void *ptr, int start, int end, gfp_t gfp)')
    alloc = replace(alloc, '\tif (WARN_ON_ONCE(start < 0))\n',
        '\tif (!lsf_prepaid_cleanup_provider_pool_idr_current(source, &idr->idr_rt, ptr))\n'
        '\t\treturn -EOPNOTSUPP;\n\n\tif (WARN_ON_ONCE(start < 0))\n')
    alloc = replace(alloc, 'idr_alloc_u32(idr, ptr, &id, end > 0 ? end - 1 : INT_MAX, gfp)',
        'lsf_provider_pool_idr_alloc_u32(source, idr, ptr, &id, end > 0 ? end - 1 : INT_MAX, gfp)')
    return text+'\n'+alloc


def transform(outputs, inputs):
    authenticate(inputs)
    for name, expected in preimages()['parentDerived'].items():
        require(name in outputs and len(outputs[name]) == expected['bytes'] and
            hashlib.sha256(outputs[name]).hexdigest() == expected['sha256'],
            'cleanup-provider-birth-parent-preimage')
    outputs = dict(outputs)
    name = 'include/net/lsf_stream_cleanup_provider_executor.h'
    outputs[name] = replace(outputs[name].decode(), '#endif\n',
        'struct idr;\nstruct radix_tree_root;\nstruct radix_tree_iter;\n'
        'int lsf_factory_cleanup_provider_birth_current(struct lsf_cleanup_task_source, const void *);\n'
        'int lsf_prepaid_cleanup_provider_pool_idr_current(struct lsf_cleanup_task_source,\n'
        '    const void *, const void *);\n'
        'int lsf_prepaid_cleanup_provider_pool_idr_alloc(struct lsf_cleanup_task_source,\n'
        '    struct idr *, void *, int, int, gfp_t);\n'
        'void __rcu **lsf_prepaid_cleanup_provider_pool_idr_get_free(struct lsf_cleanup_task_source,\n'
        '    const void *, struct radix_tree_root *, struct radix_tree_iter *, gfp_t, unsigned long);\n'
        '#endif\n').encode()
    name = 'net/factory.c'
    outputs[name] = replace(outputs[name].decode(), '#include "factory-cleanup-provider-executor.c"\n',
        '#include "factory-cleanup-provider-executor.c"\n#include "factory-cleanup-provider-birth.c"\n').encode()
    for name, fragment in [('lib/radix-tree.c', 'lsf-cleanup-provider-pool-radix.c'),
                           ('lib/idr.c', 'lsf-cleanup-provider-pool-idr.c')]:
        outputs[name] = (outputs[name].decode()+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '#include <net/lsf_stream_cleanup_provider_executor.h>\n#include "'+fragment+'"\n#endif\n').encode()
    name = 'kernel/lsf-cleanup-provider-executor.c'
    outputs[name] = (outputs[name]+b'\n'+(OWNED/'workqueue-cleanup-provider-birth.c').read_bytes())
    outputs['net/factory-cleanup-provider-birth.c'] = (OWNED/'factory-cleanup-provider-birth.c').read_bytes()
    outputs['lib/lsf-cleanup-provider-pool-radix.c'] = private_radix().encode()
    outputs['lib/lsf-cleanup-provider-pool-idr.c'] = private_idr().encode()
    return outputs
