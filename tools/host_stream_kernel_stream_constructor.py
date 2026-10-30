"""Closed original-actor PCI bind and actual VP/device-core source route.

Unselected source draft. The original 381-file input and ordinary function
bodies are authenticated whole; no source match lends allocation authority.
"""
import hashlib
import json
import re
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require

INPUT_SHA = '0f3276228e4952a8ffed4ddd725022db50aa7e6c6f28086c12f81f46aed88637'
PREIMAGES = {'drivers/pci/pci-driver.c': (44968, 'ee4fde41eba28cadaf567b47526104d3a4ed7468a08a9e71014cf071e5085a88'), 'drivers/virtio/virtio_pci_common.c': (23391, '81792321309029fd3b9f92677ad528e61886a1b422c3f16a086492c4483976c0'), 'drivers/virtio/virtio.c': (16287, 'b3da335d7adb701a366af3e9e0097143499354f33ce4e17bd73ec5a219eebe7b'), 'drivers/net/virtio_net.c': (194869, '401fe3721ef145607f732c7ce09c2867e573075e44bb4aed029336bb8bb3aa7b'), 'net/factory-device-core.c': (13126, '49db917a58c1d9f661df666e1ebd81f6858ac3ca3a2f9475e8b69fb675f7f231'), 'net/factory-stream-rx-preallocate.c': (46360, 'a99ff0e60a383fb607a2630ae5a642f2702c7a02ca4e94f5ca798496d50f571f'), 'net/factory-stream-root-final-free.c': (12837, 'e0d9b9dea98be981dbc673e9b0fd416573e3b65713dce1751a07757a6fc259ec'), 'lib/kobject.c': (34036, 'ef095be483a79178cb6e94b305562bc490231814fb71ff2588aebe6161152d9b'), 'net/device-prepaid.h': (18564, 'ed2bfd8132b42078d35cffb113b8ed59f7df639c47d0b575a6aea605f8233d2d'), 'net/factory.c': (36966, '932f33884be6dbfaa1a4fcf482090e1b53c97eb93678cc75e2b3f21acc43e7a3'), 'lib/idr.c': (23401, 'd72e15d7308dcbb8ff61f0587e094cd74934a4f946b8e3286edaf17d326de916'), 'net/factory-device-registration.c': (12869, '3309a0145f10936a5afe28d4f7979e53c2d27837e0b0eee535ac22be6fd066a7'), 'net/factory-device-sysfs.c': (4709, 'b36c47dd0ec3a8c3a6e7e8f3aa4cbd582db8880f32a98b4e5a7d6cc6b884d304'), 'net/factory-stream-operations.c': (25328, '54bb347dfc97b9d6cca25ffa6e85fe0ef1ff344e69a864646533447ce46459f2'), 'lib/radix-tree.c': (60159, '314fe217812183eec82a83a7f1b8c0d4734b926813048fd8ea23449ace112039')}
PRIMARY = {'drivers/base/dd.c': (38838, 'd7321d96a19b4dbf2fdea8bae5ac3cbd1956a775668c70f34845c6594cab6689'), 'drivers/pci/bus.c': (11650, '98922d091750fa9a87d332769290a8e438b762df3f9200b66da4b94298bdbc3a'), 'drivers/pci/proc.c': (11040, '68ce303ece85a98f9279452092928d33b097dce2166987a022711556fae6f796'), 'drivers/pci/pci-sysfs.c': (42332, '09c42535f348dff82b90ae40c497d46e8b98a3a84a43c0d56ca9e7d3237e1460'), 'fs/proc/generic.c': (19809, 'aed7c375f9b5fa0caa326beaa420514dfcddc3ffc78de8402c346444343bca64'), 'fs/proc/inode.c': (17061, 'a25586d83a5c01dba5e11c0b2d59d7ea977e11cb3cd5fc83892f8dd7e94985e6'), 'fs/proc/internal.h': (11133, 'f3fc4d9e1a2ca2e0b6ef68b659915aacc225aeb230d895517fcc4ad6328f97ff')}
BODIES = {'drivers/pci/bus.c::void pci_bus_add_device(': (968, '776cef780deb8c0f7ab16b0ac97f4a4a28fdd506e863ee3640e2f2d4e746e301'), 'drivers/pci/pci-driver.c::static int pci_call_probe(': (1234, 'd02eb7afe9289d5c9d3e039d0c8eedc9e102339d86f223273120cd9b2cf2c111'), 'drivers/virtio/virtio_pci_common.c::static int virtio_pci_probe(': (1439, '15d8c29f1248741e5fc2df771053b20c3df3888b09231d627d90c2d5bd7a1f39'), 'drivers/virtio/virtio_pci_common.c::static void virtio_pci_release_dev(': (329, 'ca7adc7a4aa038dc0a673e1171fafa1542c3617b351ba617538ebb4b518ddd3e'), 'drivers/virtio/virtio.c::int register_virtio_device(': (1251, 'eee85910214e7e2ae4febe5e0cd7af5b0f4f202bfcd21e34ba5fd64b96860753'), 'drivers/base/dd.c::static int __device_attach_driver(': (1050, '2c581571b8bb3afe5ef35cd33c8c41f81a9a156baa6cbfbea9acc84733cbb507'), 'drivers/pci/proc.c::int pci_proc_attach_device(': (548, '1bb9bef28d9d1cd9efe84104c0a67b2a920291cc14be3736489488777a1e9290'), 'drivers/pci/pci-sysfs.c::static int pci_create_attr(': (1563, '3ed7bd2d43e0fdd41569bf03ec48bd05bb8c0450fcd0a19196819a91503fa8eb'), 'drivers/pci/pci-sysfs.c::static void pci_remove_resource_files(': (411, 'cf19a585e4b5415664a59d3e699da2f9de47b90f9f2e0f9e2bc419b51fc78f33'), 'fs/proc/generic.c::void pde_free(': (192, 'cba1de2b7e0a4e391cd01b1c7739a5e9d01617d5da0daf7a56efd17fe5c7a947'), 'fs/proc/generic.c::struct dentry *proc_lookup_de(': (516, '441fbea2ddfc333265339644d8d19cebe838b96a1d1ba9df95bee0fa8cf3663c'), 'fs/proc/generic.c::int proc_alloc_inum(': (220, '4e40db28f7c5a2986d197639f0843bf9421e25bde6f8bd92632df83e43caf0d0'), 'fs/proc/generic.c::static struct proc_dir_entry *__proc_create(': (1597, '1bf97da9d5ef692598beeacf341273d2488fc9bab4687fe49d1fc0f6fccc989e'), 'fs/proc/generic.c::struct proc_dir_entry *proc_create_reg(': (426, '251cfe3a79ffec61d7c44ab1208cebf1a6d2db013c809f0aeb5b0ff4cc39062e'), 'fs/proc/generic.c::struct proc_dir_entry *proc_register(': (583, '34ae941ef6408becec809ff8a9e785cdff7d761548d1318aed05d2fc1a8a8a05'), 'fs/proc/inode.c::void proc_entry_rundown(': (579, '5a573a4fba108b17afd46808ab571259b0b593a0f6a5ed43b3c15900c0976a59'), 'fs/proc/inode.c::struct inode *proc_get_inode(': (1174, '25ab0fef3f812ec24c038619558613fa6900fd2eb3448a28e518bae69bfa1697'), 'net/factory-device-core.c::int lsf_factory_device_core_owned(': (1164, 'c9d9da6d17a8b6e5e3a32d09441d12050c9fcb2579d31e49392473e93ddf7c50'), 'net/factory-device-core.c::void *lsf_factory_device_core_allocate(': (1813, 'edb55614645f932b9b981a6be326bf46e61bd84fab1f259f9556ec09dc841265'), 'net/factory-device-core.c::int lsf_factory_device_core_return(': (2531, '904781dd27e963840cbaff4b1dae66d066362729228da51445e21b0c94f351ec'), 'net/factory-device-core.c::int lsf_factory_device_core_tail_enter(': (1303, '70c409d1e499b39e1c7383d160545bbdc3f32c796d032b386d97a3861c179a7c'), 'net/factory-device-core.c::void lsf_factory_device_core_tail_finish(': (2066, '28529eb7fb8262c8834cae0c84763701ecad0189bb467b868f7973b0eab633ad'), 'net/factory-device-registration.c::static struct lsf_factory_device_firmware *\nlsf_factory_device_registration_parent_locked(': (829, '50c69e5ac9bafc9b8405b1cfdb9d8d184253c23f95f5f21a899638258fd14e54'), 'net/factory-device-registration.c::static struct lsf_prepaid_view *lsf_factory_device_registration_record_locked(': (1361, 'bcd87cc56f77cf401fd95ff7439cbf6234c2c8bca0d3b54556fb3638d9697497'), 'net/factory-device-registration.c::int lsf_factory_device_registration_kobject(': (964, '8b98214fa7038f32ced3f72d42c6f5320bcd5a20ac3c21300cd6a43d0f420b8e'), 'net/factory-device-registration.c::static int lsf_factory_device_registration_current_locked(': (881, '89a3029617bfd374ffb3c904289c9be038a336afbdf88bc46380a687e334751f'), 'net/factory-device-registration.c::void *lsf_factory_device_registration_allocate(': (1244, '2124f6164c0dcad6632769dda7cc1c616b3d6ed659428ca0af9585286eb29ded'), 'net/factory-device-sysfs.c::int lsf_factory_device_sysfs_release(': (1528, '3f15f42fd6c5b75204d7dff60774c6f5eeb9e0627a71d3deaabe7da16934d5a9'), 'net/factory-stream-operations.c::static int lsf_stream_create(': (2108, '643aef634e7929b222da204381918bd0ed287b1540f7b7f9dbec95e8f8696e01'), 'lib/radix-tree.c::void __rcu **lsf_prepaid_device_idr_get_free(': (2199, 'f9398e577413d029216092115cd9fb276731674ba0bee27db68d64003d7b903e'), 'lib/radix-tree.c::void __rcu **lsf_prepaid_stream_classdir_idr_get_free(': (2229, 'd3b624d2da8ddf00d4d592d22853732ab1dc1aa01d87986e3a79bb2004d825a8'), 'lib/radix-tree.c::void __rcu **lsf_prepaid_stream_netdev_directory_idr_get_free(': (2264, 'c47890ec156e58099c5b2d8c2a14434ca7f1beb435bd8ad49a26166e4349995f')}
OWNED_FILES = {
    'include/net/lsf_stream_constructor_private.h': 'stream-constructor-private.h',
    'net/factory-stream-constructor.c': 'factory-stream-constructor.c',
    'net/factory-stream-virtio-core.c': 'factory-stream-virtio-core.c',
    'lib/lsf-stream-constructor-ida.c': 'stream-constructor-ida.c',
    'net/factory-stream-proc.c': 'factory-stream-proc.c',
    'net/factory-stream-virtio-registration.c': 'factory-stream-virtio-registration.c',
    'net/factory-stream-pci-attrs.c': 'factory-stream-pci-attrs.c',
    'drivers/pci/lsf-stream-constructor-pci-attrs.c': 'stream-constructor-pci-attrs.c',
    'lib/lsf-stream-constructor-idr.c': 'stream-constructor-idr.c',
}


def _bound(raw, pin):
    return type(raw) is bytes and (len(raw), hashlib.sha256(raw).hexdigest()) == pin


def _body(text, path, signature):
    require(text.count(signature) == 1, 'constructor-one-full-declaration')
    start = text.index(signature)
    require(start == 0 or text[start - 1] == '\n', 'constructor-line-full-declaration')
    raw = function(text, signature)
    require(_bound(raw.encode(), BODIES[path + '::' + signature]),
            'constructor-full-function-body')
    return raw


def _include(editor, anchor):
    editor.edit(anchor, anchor + '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
                '#include <net/lsf_stream_constructor_private.h>\n#endif\n')


def _wrap(original, branch):
    start = original.index('\n{\n')
    return original[:start] + '\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n' + branch + \
        '#endif\n' + original[start + 1:] + '}\n'


def _clone(original, name, replacements):
    name_start = original.index('(')
    prefix = original[:name_start]
    old_name = re.search(r'([A-Za-z_]\w*)$', prefix).group(1)
    result = original[:name_start-len(old_name)] + name + original[name_start:]
    for old, new in replacements:
        require(result.count(old) == 1, 'constructor-clone-one-edit')
        result = result.replace(old, new)
    inverse = result
    for old, new in reversed(replacements):
        require(inverse.count(new) == 1, 'constructor-clone-one-inverse')
        inverse = inverse.replace(new, old)
    inverse = inverse.replace(name + '(', old_name + '(', 1)
    require(inverse == original, 'constructor-complete-clone-inverse')
    return result


# Resource/PAT source increment. Kept separate from the immutable R1 transform:
# no old ordinary body, source tuple or qualification receipt is relabelled.
MAPPING_INPUT_SHA = 'f9820d0e9a9d9d0eedeb469c6fe03556ba25d09be91932da5b2b31ee255d5df9'
MAPPING_PRIMARY = {'kernel/resource.c': (54675, '4dc6ed5d3fca0fe8c1285a058859af4ca7490cc7654e8c01279fa16f759398bd'), 'arch/x86/mm/pat/memtype.c': (32298, '84a3e0deccb9685787d96662383a3deba07e5acb0e6930e6119e8764c8464a6a'), 'arch/x86/mm/pat/memtype.h': (1470, 'c0f6507e078711594fc793f767f62a22488bd634705770cbc0ab58e5894e2fa8'), 'arch/x86/mm/pat/memtype_interval.c': (5010, 'afa6d493197f5d3a42399da3f9c2599c7897ef38e1dac4961ace18e0c848483e')}
MAPPING_PREIMAGES = {'drivers/pci/pci.c': (187959, '665d92073a3695b1afbf3c3702dfb5f879ef78932610c2e9c7f5c9172194e02f'), 'net/factory.c': (37552, '6e46ec6a58d8824654262d0aff1557e7247229fe958c69a4f1e006cd99e83008'), 'net/device-prepaid.h': (18886, '3ce2d472e8597b2b9d5ca85daad583281387f6fdcb654c454d27e14b0747e7f3'), 'net/factory-stream-stop.c': (6081, '417daf92a236163e50d12e441eb212d17d85d6cfe6c19774789743a046f96f3a'), 'net/factory-stream-rx-preallocate.c': (46658, 'c51f72113ef932231a70330d2dada89e04bd93b99f4ec6dcd3a4553d48542639'), 'net/factory-stream-root-final-free.c': (13985, 'e50d51e2dbc101acad0054d82058aa7e6a8d21f2ca75b0d2e4a1a168e268f7a4')}
MAPPING_BODIES = {'kernel/resource.c::static void free_resource(': (375, '0132303345c9635011d0fd0b6cfb070ac7842faa613e17badf58acb442f414e8'), 'kernel/resource.c::void __release_region(': (770, '34ec6b28ced8a62486b5f198f09ff8a591677d394539c51cc469bcb32fe255c0'), 'kernel/resource.c::struct resource *__request_region(': (485, '2f54a5a9522cce18357f896e75c81b1e9d1eaaf408f32b3427b9ca457462c158'), 'drivers/pci/pci.c::static int __pci_request_region(': (891, 'feceb5be376714483c8ac622383fe2d10276e31afe6debd03d4f5716dea89592'), 'arch/x86/mm/pat/memtype.c::int memtype_reserve(': (2148, 'cae5bba51835a67c910794b141db42ff2ea27e6941dc31388c87bd0abeaf2971'), 'arch/x86/mm/pat/memtype.c::int memtype_free(': (843, '5f59a615ad8a1beac95f9e40f1818d39bae42a5e358c6f11679246fabae8266c'), 'arch/x86/mm/pat/memtype_interval.c::struct memtype *memtype_erase(': (906, '08cf30b732b1c8fac597b3e7daf8f5c6ddd64db472735c98b403f5e16ab570fb')}
MAPPING_FILES = {
    'include/net/lsf_stream_constructor_mapping_private.h': 'stream-constructor-mapping-private.h',
    'net/factory-stream-mapping.c': 'factory-stream-mapping.c',
    'kernel/lsf-stream-constructor-resource.c': 'stream-constructor-resource.c',
    'arch/x86/mm/pat/lsf-stream-constructor-pat.c': 'stream-constructor-pat.c',
    'arch/x86/mm/pat/lsf-stream-constructor-pat-interval.c': 'stream-constructor-pat-interval.c',
}


def _mapping_body(text, path, signature):
    require(text.count(signature) == 1, 'mapping-complete-function-prefix')
    start = text.index(signature)
    require(start == 0 or text[start-1] == '\n', 'mapping-full-declaration-line')
    body = function(text, signature)
    require(_bound(body.encode(), MAPPING_BODIES[path+'::'+signature]), 'mapping-full-body-preimage')
    return body


def mapping_transform(outputs, primary):
    constructor_sources()
    require(type(outputs) is dict and len(outputs) == 398 and
        all(type(n) is str and type(b) is bytes for n,b in outputs.items()), 'mapping-input-shape')
    canonical=(json.dumps({n:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
        for n,b in outputs.items()},sort_keys=True,separators=(',',':'))+'\n').encode()
    require(hashlib.sha256(canonical).hexdigest() == MAPPING_INPUT_SHA, 'mapping-whole-R1-input')
    require(type(primary) is dict and set(primary) == set(MAPPING_PRIMARY), 'mapping-closed-primaries')
    for n,pin in MAPPING_PRIMARY.items():require(_bound(primary[n],pin), 'mapping-primary-preimage')
    for n,pin in MAPPING_PREIMAGES.items():require(_bound(outputs[n],pin), 'mapping-derived-preimage')
    source={**outputs,**primary}
    for key in MAPPING_BODIES:
        path,signature=key.split('::',1);_mapping_body(source[path].decode(),path,signature)
    result=dict(outputs)
    path='kernel/resource.c'
    resource=Editor(source[path].decode())
    _include_mapping(resource,'#include <linux/ioport.h>\n')
    original=_mapping_body(resource.text,path,'static void free_resource(')
    resource.edit(original,_wrap(original,'''\tint owned = lsf_factory_stream_mapping_classify(res, LSF_STREAM_MAPPING_RESOURCE);
\tif (owned) {
\t\tif (owned > 0) (void)lsf_factory_stream_mapping_return(res, LSF_STREAM_MAPPING_RESOURCE);
\t\telse lsf_factory_stream_constructor_retain_unknown();
\t\treturn;
\t}
'''))
    original=_mapping_body(resource.text,path,'void __release_region(')
    anchor='\t\t\t*p = res->sibling;\n\t\t\twrite_unlock(&resource_lock);'
    replacement='''#ifdef CONFIG_LSF_STREAM_FACTORY
\t\t\t/* Real native tree owns the typed node through this locked search.
\t\t\t * An owned target still needs its exact original cleanup scope. */
\t\t\tint owned = lsf_factory_stream_mapping_classify(res, LSF_STREAM_MAPPING_RESOURCE);
\t\t\tif (owned && (owned < 0 ||
\t\t\t    lsf_factory_stream_mapping_can_unlink(res, LSF_STREAM_MAPPING_RESOURCE) != 1)) {
\t\t\t\tif (owned < 0) lsf_factory_stream_constructor_retain_unknown();
\t\t\t\twrite_unlock(&resource_lock);
\t\t\t\treturn; /* Refused BEFORE actual unlink/free. */
\t\t\t}
#endif
\t\t\t*p = res->sibling;
#ifdef CONFIG_LSF_STREAM_FACTORY
\t\t\tif (owned && lsf_factory_stream_mapping_unlinked(res, LSF_STREAM_MAPPING_RESOURCE) != 1) {
\t\t\t\twrite_unlock(&resource_lock);
\t\t\t\treturn; /* Actual unlink happened; unknown physical record retained. */
\t\t\t}
#endif
\t\t\twrite_unlock(&resource_lock);'''
    require(original.count(anchor)==1,'mapping-actual-resource-unlink')
    resource.edit(original,original.replace(anchor,replacement))
    resource.edit(resource.text,resource.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-stream-constructor-resource.c"\n#endif\n')
    result[path]=resource.finish().encode()
    pci=Editor(outputs['drivers/pci/pci.c'].decode())
    _include_mapping(pci,'#include <linux/pci.h>\n')
    original=_mapping_body(pci.text,'drivers/pci/pci.c','static int __pci_request_region(')
    # Closed actual BAR request: the original managed-device path remains
    # ordinary-only; the modern constructor uses the original unmanaged API.
    # Exact native IO/MEM call spellings are frozen with this source stage
    # before review; no token or API guess is accepted by the editor.
    private=_mapping_pci_request_clone(original)
    pci.edit(original,'#ifdef CONFIG_LSF_STREAM_FACTORY\n'+private+'#endif\n'+_wrap(original,
        '\tint owned = lsf_factory_stream_probe_current(pdev);\n'
        '\tif (owned) return owned < 0 ? owned : lsf_stream_constructor_pci_request_region(pdev, bar, res_name, exclusive);\n'))
    result['drivers/pci/pci.c']=pci.finish().encode()
    pat=Editor(primary['arch/x86/mm/pat/memtype.c'].decode())
    _include_mapping(pat,'#include "memtype.h"\n')
    pat.edit(pat.text,pat.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-stream-constructor-pat.c"\n#endif\n')
    result['arch/x86/mm/pat/memtype.c']=pat.finish().encode()
    interval=Editor(primary['arch/x86/mm/pat/memtype_interval.c'].decode())
    _include_mapping(interval,'#include "memtype.h"\n')
    original=_mapping_body(interval.text,'arch/x86/mm/pat/memtype_interval.c','struct memtype *memtype_erase(')
    anchor='\tif (entry_old->start == start) {'
    require(original.count(anchor)==1,'mapping-before-native-PAT-erase-or-shrink')
    interval.edit(original,original.replace(anchor,'''#ifdef CONFIG_LSF_STREAM_FACTORY
\t/* A generic range-based free must not erase/shrink another mapping's
\t * exact paid interval. The private caller retains its actual node pointer. */
\t{
\t\tint owned = lsf_factory_stream_mapping_classify(entry_old, LSF_STREAM_MAPPING_PAT);
\t\tif (owned) {
\t\t\tif (owned < 0) lsf_factory_stream_constructor_retain_unknown();
\t\t\treturn ERR_PTR(-EOPNOTSUPP);
\t\t}
\t}
#endif
'''+anchor))
    interval.edit(interval.text,interval.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-stream-constructor-pat-interval.c"\n#endif\n')
    result['arch/x86/mm/pat/memtype_interval.c']=interval.finish().encode()
    result['arch/x86/mm/pat/memtype.h']=primary['arch/x86/mm/pat/memtype.h']
    _mapping_factory(result,outputs)
    for destination,name in MAPPING_FILES.items():
        require(destination not in outputs,'mapping-new-source-file')
        raw=_constructor_source(name)
        require(raw and len(raw)<32768 and b'\r' not in raw,'mapping-owned-source-bound')
        result[destination]=raw
    return result


def _include_mapping(editor,anchor):
    editor.edit(anchor,anchor+'#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_constructor_mapping_private.h>\n#endif\n')


def _mapping_pci_request_clone(original):
    return _clone(original,'lsf_stream_constructor_pci_request_region',[
        ('\tif (pci_is_managed(pdev)) {\n'
         '\t\tif (exclusive == IORESOURCE_EXCLUSIVE)\n'
         '\t\t\treturn pcim_request_region_exclusive(pdev, bar, res_name);\n\n'
         '\t\treturn pcim_request_region(pdev, bar, res_name);\n\t}',
         '\tif (pci_is_managed(pdev) || bar >= PCI_STD_NUM_BARS)\n'
         '\t\treturn -EOPNOTSUPP;'),
        ('\t\tif (!request_region(pci_resource_start(pdev, bar),\n'
         '\t\t\t    pci_resource_len(pdev, bar), res_name))',
         '\t\tif (!lsf_prepaid_stream_request_region(pdev, &ioport_resource,\n'
         '\t\t\t    pci_resource_start(pdev, bar), pci_resource_len(pdev, bar), res_name, 0))'),
        ('\t\tif (!__request_mem_region(pci_resource_start(pdev, bar),\n'
         '\t\t\t\t\tpci_resource_len(pdev, bar), res_name,\n'
         '\t\t\t\t\texclusive))',
         '\t\tif (!lsf_prepaid_stream_request_region(pdev, &iomem_resource,\n'
         '\t\t\t    pci_resource_start(pdev, bar), pci_resource_len(pdev, bar), res_name, exclusive))'),
    ])


def _mapping_factory(result,outputs):
    state=Editor(outputs['net/factory-stream-rx-preallocate.c'].decode())
    state.edit('    struct task_struct *bind_task, *vp_tail_task;\n',
        '    struct task_struct *bind_task, *vp_tail_task;\n'
        '    struct task_struct *mapping_stop_task; /* Exact original synchronous stop borrow. */\n')
    result['net/factory-stream-rx-preallocate.c']=state.finish().encode()
    kinds=Editor(outputs['net/device-prepaid.h'].decode())
    kinds.edit('#define LSF_DEVICE_STREAM_PCI_ATTR 0x178u\n',
        '#define LSF_DEVICE_STREAM_PCI_ATTR 0x178u\n'
        '#define LSF_DEVICE_STREAM_RESOURCE 0x179u\n#define LSF_DEVICE_STREAM_PAT 0x17au\n')
    kinds.edit('        kind == LSF_DEVICE_STREAM_PROC || kind == LSF_DEVICE_STREAM_PCI_ATTR ||',
        '        kind == LSF_DEVICE_STREAM_RESOURCE || kind == LSF_DEVICE_STREAM_PAT ||\n'
        '        kind == LSF_DEVICE_STREAM_PROC || kind == LSF_DEVICE_STREAM_PCI_ATTR ||')
    result['net/device-prepaid.h']=kinds.finish().encode()
    factory=Editor(outputs['net/factory.c'].decode())
    _include_mapping(factory,'#include <linux/module.h>\n')
    factory.edit('#include "factory-stream-pci-attrs.c"\n',
        '#include "factory-stream-pci-attrs.c"\n#include "factory-stream-mapping.c"\n')
    result['net/factory.c']=factory.finish().encode()
    stop=Editor(outputs['net/factory-stream-stop.c'].decode())
    stop.edit('        pci_stop_and_remove_bus_device_locked(pci);',
        '        if (lsf_factory_stream_mapping_stop_enter(state, pci) != 1) {\n'
        '            result = -EOPNOTSUPP;\n'
        '            lsf_factory_stream_constructor_retain_unknown();\n'
        '        } else {\n            pci_stop_and_remove_bus_device_locked(pci);\n'
        '            if (lsf_factory_stream_mapping_stop_leave(state, pci) != 1) result = -EOPNOTSUPP;\n'
        '        }')
    stop.edit('        rcu_barrier();\n        result = lsf_stream_classdir_drain_after_remove(state);\n'
        '        if (!result) result = lsf_stream_netdev_drain_after_remove(state);',
        '        if (!result) {\n            rcu_barrier();\n'
        '            result = lsf_stream_classdir_drain_after_remove(state);\n'
        '            if (!result) result = lsf_stream_netdev_drain_after_remove(state);\n        }')
    result['net/factory-stream-stop.c']=stop.finish().encode()
    root=Editor(outputs['net/factory-stream-root-final-free.c'].decode())
    root.edit('        state->vp_tail_object) return 0;',
        '        state->vp_tail_object || state->mapping_stop_task) return 0;')
    result['net/factory-stream-root-final-free.c']=root.finish().encode()


def _pci_driver(editor):
    path = 'drivers/pci/pci-driver.c'
    signature = 'static int pci_call_probe('
    original = _body(editor.text, path, signature)
    clone = _clone(original, 'lsf_prepaid_stream_pci_call_probe', [
        ('\tnode = dev_to_node(&dev->dev);',
         '\tif (!lsf_prepaid_stream_pci_driver_known(drv)) return -EOPNOTSUPP;\n'
         '\tnode = dev_to_node(&dev->dev);'),
        ('\tif (cpu < nr_cpu_ids)\n\t\terror = work_on_cpu(cpu, local_pci_probe, &ddi);',
         '\tif (cpu < nr_cpu_ids)\n\t\terror = -EOPNOTSUPP; /* No worker/actor substitution. */'),
    ])
    wrapped = _wrap(original, '\tint selected = lsf_factory_stream_probe_current(dev);\n'
        '\tif (selected) return selected < 0 ? selected :\n'
        '\t\tlsf_prepaid_stream_pci_call_probe(drv, dev, id);\n')
    editor.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' + clone +
                '#endif\n' + wrapped)
    editor.edit(editor.text, editor.text+'''
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_stream_pci_bus_known(const struct bus_type *bus)
{
    return bus == &pci_bus_type; /* Actual source-pinned CONST native bus. */
}
#endif
''')


def _pci_bus(editor):
    path = 'drivers/pci/bus.c'
    original = _body(editor.text, path, 'void pci_bus_add_device(')
    clone = _clone(original, 'lsf_prepaid_stream_pci_bus_add_device', [])
    # The clone is private to this TU. Every original administrative operation,
    # order, error and match_driver assignment remains present in its body.
    clone = 'static ' + clone
    wrapped = _wrap(original, '''\tint selected = lsf_factory_stream_bind_selected(dev);
\tif (selected) {
\t\tstruct lsf_stream_bind_reference reference;
\t\tint error;
\t\tif (selected < 0) return;
\t\terror = lsf_factory_stream_bind_begin(dev, &reference);
\t\tif (error != 1) return;
\t\tlsf_prepaid_stream_pci_bus_add_device(dev);
\t\tlsf_factory_stream_bind_end(&reference, dev->driver ? 1 : -ENODEV);
\t\treturn;
\t}
''')
    editor.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' + clone +
                '#endif\n' + wrapped)


def _vp(editor):
    path = 'drivers/virtio/virtio_pci_common.c'
    original = _body(editor.text, path, 'static int virtio_pci_probe(')
    clone = _clone(original, 'lsf_prepaid_stream_virtio_pci_probe', [
        ('\tvp_dev = kzalloc(sizeof(struct virtio_pci_device), GFP_KERNEL);',
         '\tif (force_legacy) return -EOPNOTSUPP;\n'
         '\tvp_dev = lsf_factory_stream_vp_allocate(pci_dev, sizeof(*vp_dev));'),
        ('\t\tif (rc == -ENODEV)\n\t\t\trc = virtio_pci_legacy_probe(vp_dev);',
         '\t\tif (rc == -ENODEV)\n\t\t\trc = -EOPNOTSUPP; /* No unported legacy fallback. */'),
        ('\telse\n\t\tkfree(vp_dev);',
         '\telse\n\t\t(void)lsf_factory_stream_vp_return_uninitialized(vp_dev);'),
    ])
    wrapped = _wrap(original, '\tint selected = lsf_factory_stream_probe_current(pci_dev);\n'
        '\tif (selected) return selected < 0 ? selected :\n'
        '\t\tlsf_prepaid_stream_virtio_pci_probe(pci_dev, id);\n')
    editor.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' + clone +
                '#endif\n' + wrapped)
    release = _body(editor.text, path, 'static void virtio_pci_release_dev(')
    editor.edit(release, _wrap(release,
        '\tint selected = lsf_factory_stream_vp_release_seen(to_vp_device(dev_to_virtio(_d)));\n'
        '\tif (selected) return; /* Unknown retains the original physical owner. */\n'))
    editor.edit(editor.text, editor.text + '''
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_stream_pci_driver_known(const struct pci_driver *driver)
{
    if (driver != &virtio_pci_driver || !IS_BUILTIN(CONFIG_VIRTIO_PCI)) return 0;
    return driver->probe == virtio_pci_probe && driver->remove == virtio_pci_remove &&
        driver->id_table == virtio_pci_id_table &&
        driver->sriov_configure == virtio_pci_sriov_configure &&
#ifdef CONFIG_PM_SLEEP
        driver->driver.pm == &virtio_pci_pm_ops &&
#else
        !driver->driver.pm &&
#endif
        driver->driver.owner == THIS_MODULE;
}
int lsf_prepaid_stream_pci_device_driver_known(const struct device_driver *driver)
{
    return driver == &virtio_pci_driver.driver &&
        lsf_prepaid_stream_pci_driver_known(&virtio_pci_driver);
}
int lsf_prepaid_stream_vp_geometry(unsigned long *bytes, unsigned long *alignment)
{
    static_assert(offsetof(struct virtio_pci_device, vdev) == 0);
    *bytes = sizeof(struct virtio_pci_device);
    *alignment = __alignof__(struct virtio_pci_device);
    return 0;
}
int lsf_prepaid_stream_vp_device_known(const struct virtio_device *vdev,
    const struct pci_dev *pci)
{
    const struct virtio_pci_device *vp = container_of(vdev, struct virtio_pci_device, vdev);
    /* Caller has already authenticated the actual VP birth/whole extent. */
    return vp->pci_dev == pci && !vp->is_legacy &&
        vdev->dev.parent == &pci->dev && vdev->dev.release == virtio_pci_release_dev &&
        !vdev->dev.class && !vdev->dev.type && !vdev->dev.init_name &&
        !vdev->dev.platform_data && !vdev->dev.of_node && !vdev->dev.fwnode;
}
#endif
''')


def _registration(editor):
    path = 'drivers/virtio/virtio.c'
    original = _body(editor.text, path, 'int register_virtio_device(')
    clone = _clone(original, 'lsf_prepaid_stream_register_virtio_device', [
        ('\tdevice_initialize(&dev->dev);',
         '\terr = lsf_factory_stream_virtio_core_begin(dev);\n'
         '\tif (err) return err;\n\tdevice_initialize(&dev->dev);'),
        ('\terr = ida_alloc(&virtio_index_ida, GFP_KERNEL);',
         '\terr = lsf_prepaid_stream_ida_alloc_existing(&virtio_index_ida, 0, INT_MAX);'),
        ('\terr = dev_set_name(&dev->dev, "virtio%u", dev->index);',
         '\terr = lsf_factory_stream_virtio_core_name(dev);'),
    ])
    clone = 'static ' + clone
    wrapped = _wrap(original,
        '\tint selected = lsf_factory_stream_virtio_core_classify(&dev->dev, 0);\n'
        '\tif (selected) return selected < 0 ? selected :\n'
        '\t\tlsf_prepaid_stream_register_virtio_device(dev);\n')
    editor.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' + clone +
                '#endif\n' + wrapped)
    editor.edit(editor.text, editor.text+'''
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_stream_virtio_bus_known(const struct bus_type *bus)
{
    return bus == &virtio_bus; /* Actual source-pinned CONST native bus. */
}
#endif
''')


def _attach(editor):
    original = _body(editor.text, 'drivers/base/dd.c', 'static int __device_attach_driver(')
    matcher = '\tret = driver_match_device(drv, dev);\n'
    require(original.count(matcher) == 1, 'constructor-before-real-bus-matcher')
    projected = original.replace(matcher, '#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\tret = lsf_factory_stream_attach_bus_current(dev);\n'
        '\tif (ret < 0) return ret;\n#endif\n'+matcher)
    old = '\tasync_allowed = driver_allows_async_probing(drv);\n'
    new = '''#ifdef CONFIG_LSF_STREAM_FACTORY
\t/* Original bus match has returned a positive match. Authenticate the real
\t * builtin probe instance before its callback or any async scheduling. */
\tret = lsf_factory_stream_attach_current(dev, drv);
\tif (ret < 0) return ret;
\tif (ret && driver_allows_async_probing(drv)) return -EOPNOTSUPP;
#endif
'''+old
    require(projected.count(old) == 1, 'constructor-real-async-decision')
    editor.edit(original, projected.replace(old, new))


def _device_core(editor):
    # Existing PCI/NETDEV source stays byte-exact after inverse projection.
    routes = (
        ('int lsf_factory_device_core_owned(', 'device', 'owned', 'device'),
        ('void *lsf_factory_device_core_allocate(', 'device', 'allocate', 'device, bytes'),
        ('int lsf_factory_device_core_return(', 'device', 'return', 'device, address'),
        ('int lsf_factory_device_core_tail_enter(', 'kobject', 'tail_enter', 'kobject'),
    )
    for signature, address, name, args in routes:
        original = _body(editor.text, 'net/factory-device-core.c', signature)
        original_start = original.index('\n{\n') + 3
        # Return types remain actual, including NULL on a refused allocator.
        negative = 'NULL' if name == 'allocate' else 'virtio_kind'
        branch = ('\n    int virtio_kind = lsf_factory_stream_virtio_core_classify(' + address +
                  ', ' + ('1' if name == 'tail_enter' else '0') + ');\n'
                  '    if (virtio_kind) return virtio_kind < 0 ? ' + negative +
                  ' : lsf_factory_stream_virtio_core_' + name + '(' + args + ');\n')
        editor.edit(original, original[:original_start] + branch + original[original_start:])
    original = _body(editor.text, 'net/factory-device-core.c',
                     'void lsf_factory_device_core_tail_finish(')
    at = original.index('\n{\n') + 3
    editor.edit(original, original[:at] +
        '\n    if (lsf_factory_stream_virtio_core_tail_finish(kobject)) return;\n' + original[at:])


def _state_and_lifetime(result, outputs):
    state = Editor(outputs['net/factory-stream-rx-preallocate.c'].decode())
    anchor = '    const struct pci_dev *pci;\n'
    state.edit(anchor, '''    struct task_struct *bind_task, *vp_tail_task;
    const void *vp_tail_object, *vp_returned_address;
    struct lsf_prepaid_ticket vp_returned;
    unsigned long vp_extent;
    unsigned int bind_attempted, bind_active, bind_complete, bind_error, vp_attempted;
'''+anchor)
    # sizeof(state) at the original pre-PCI allocation automatically includes
    # these fields. Actual cursor/alignment/record checks precede allocation.
    state.edit('        state->virtio == vdev && state->device_borrows)',
               '        lsf_factory_stream_vp_device_matches_locked(state, vdev) && state->device_borrows)')
    result['net/factory-stream-rx-preallocate.c'] = state.finish().encode()
    root = Editor(outputs['net/factory-stream-root-final-free.c'].decode())
    root.edit('    if (state->netdev_tail_task || state->netdev_tail_object) return 0;',
              '    if (state->netdev_tail_task || state->netdev_tail_object ||\n'
              '        state->bind_task || state->bind_active || state->vp_tail_task ||\n'
              '        state->vp_tail_object) return 0;')
    # The existing collector may have late child returns after stop. A counted
    # original bank loan plus collecting excludes another Root collector while
    # the native RCU barrier and corresponding positive-parent put run unlocked.
    anchor = '    lockdep_assert_held(&factory_lock);\n    *release = (struct lsf_cleanup_root_release){0};\n'
    root.edit(anchor, anchor+'''    spin_lock_irqsave(&pool_lock, flags);
    state = lsf_stream_rx_current_locked();
    if (state && state->closing && state->hardware_stopped && !state->collecting &&
        !state->finalizing && !state->vp_tail_task && !state->vp_tail_object &&
        state->device_borrows != UINT_MAX) {
        state->collecting = 1;
        ++state->device_borrows;
        spin_unlock_irqrestore(&pool_lock, flags);
        mutex_unlock(&factory_lock);
        rcu_barrier();
        (void)lsf_stream_vp_drain_completed(state);
        mutex_lock(&factory_lock);
        spin_lock_irqsave(&pool_lock, flags);
        if (lsf_stream_rx_current_locked() != state || !state->collecting ||
            !state->device_borrows) {
            factory.pool.poisoned = 1; WRITE_ONCE(factory.uncertain, 1);
            spin_unlock_irqrestore(&pool_lock, flags);
            return 0; /* Exact unknown bank loan is not refunded. */
        }
        --state->device_borrows;
        state->collecting = 0;
    }
    spin_unlock_irqrestore(&pool_lock, flags);
''')
    result['net/factory-stream-root-final-free.c'] = root.finish().encode()
    kobject = Editor(outputs['lib/kobject.c'].decode())
    _include(kobject, '#include <linux/kobject.h>\n')
    kobject.edit('\t\tif (!lsf_factory_stream_netdev_classdir_name_return(kobj, name) &&',
                 '\t\tif (!lsf_factory_stream_virtio_core_name_return(kobj, name) &&\n'
                 '\t\t    !lsf_factory_stream_netdev_classdir_name_return(kobj, name) &&')
    result['lib/kobject.c'] = kobject.finish().encode()
    kinds = Editor(outputs['net/device-prepaid.h'].decode())
    kinds.edit('static inline int lsf_device_kind(unsigned int kind)\n{\n',
               '#define LSF_DEVICE_VIRTIO_CORE 0x175u\n'
               '#define LSF_DEVICE_VIRTIO_CORE_NAME 0x176u\n'
               '#define LSF_DEVICE_STREAM_PROC 0x177u\n'
               '#define LSF_DEVICE_STREAM_PCI_ATTR 0x178u\n'
               'static inline int lsf_device_kind(unsigned int kind)\n{\n')
    kinds.edit('    return kind == LSF_DEVICE_STREAM_NETDEV_DIRECTORY_NODE',
               '    return kind == LSF_DEVICE_VIRTIO_CORE || kind == LSF_DEVICE_VIRTIO_CORE_NAME ||\n'
               '        kind == LSF_DEVICE_STREAM_PROC || kind == LSF_DEVICE_STREAM_PCI_ATTR ||\n'
               '        kind == LSF_DEVICE_STREAM_NETDEV_DIRECTORY_NODE')
    result['net/device-prepaid.h'] = kinds.finish().encode()
    factory = Editor(outputs['net/factory.c'].decode())
    # The header precedes actual device-kind users and exports only private
    # source interfaces. No static allocation, registration or initcall added.
    _include(factory, '#include <linux/module.h>\n')
    factory.edit('static int lsf_stream_root_pending_locked(void);\n',
        'static int lsf_stream_vp_drain_completed(struct lsf_stream_rx_state *);\n'
        'static int lsf_stream_root_pending_locked(void);\n')
    factory.edit('#include "factory-stream-netdev-core.c"\n',
        '#include "factory-stream-netdev-core.c"\n'
        '#include "factory-stream-constructor.c"\n#include "factory-stream-virtio-core.c"\n'
        '#include "factory-stream-proc.c"\n#include "factory-stream-virtio-registration.c"\n')
    factory.edit('#include "factory-stream-virtio-registration.c"\n',
        '#include "factory-stream-virtio-registration.c"\n#include "factory-stream-pci-attrs.c"\n')
    factory.edit('#include "factory-device-registration.c"\n',
        'static struct lsf_factory_device_firmware *lsf_stream_virtio_registration_parent_locked(\n'
        '    struct lsf_device_registration_source);\n'
        'static int lsf_stream_virtio_registration_bind_locked(struct lsf_device_registration_source);\n'
        '#include "factory-device-registration.c"\n')
    result['net/factory.c'] = factory.finish().encode()
    ida = Editor(outputs['lib/idr.c'].decode())
    _include(ida, '#include <linux/idr.h>\n')
    ida.edit(ida.text, ida.text + '\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-stream-constructor-ida.c"\n#endif\n')
    result['lib/idr.c'] = ida.finish().encode()
    operations = Editor(outputs['net/factory-stream-operations.c'].decode())
    original = _body(operations.text, 'net/factory-stream-operations.c', 'static int lsf_stream_create(')
    anchor = '    error = lsf_prepaid_context_create(&factory.pool, scope,\n'
    require(original.count(anchor) == 1, 'constructor-before-normal-context-birth')
    operations.edit(original, original.replace(anchor,
        '    if (!lsf_factory_stream_bind_ready_locked()) {\n'
        '        spin_unlock_irqrestore(&pool_lock, flags);\n'
        '        return -EOPNOTSUPP;\n    }\n'+anchor))
    result['net/factory-stream-operations.c'] = operations.finish().encode()


def _registration_route(result, outputs):
    path = 'net/factory-device-registration.c'
    registration = Editor(outputs[path].decode())
    signature = 'static struct lsf_factory_device_firmware *\nlsf_factory_device_registration_parent_locked('
    original = _body(registration.text, path, signature)
    anchor = '    record = lsf_device_record(&factory.pool, factory.device->key, pci, LSF_DEVICE_PCI);'
    branch = '''    /* The SAME source container field can name only these two actual
     * closed kinds. VIRTIO is not relabelled/adopted as a PCI record. */
    if (pci.slot && pci.slot < LSF_ALLOCATION_SLOTS &&
        factory.pool.records[pci.slot].kind == LSF_DEVICE_VIRTIO)
        return lsf_stream_virtio_registration_parent_locked(source);
'''
    require(original.count(anchor) == 1, 'constructor-registration-parent-branch')
    registration.edit(original, original.replace(anchor, branch+anchor))
    signature = 'static struct lsf_prepaid_view *lsf_factory_device_registration_record_locked('
    original = _body(registration.text, path, signature)
    local = Editor(original)
    local.edit('(source.kind != LSF_DEVICE_PCI && !lsf_device_registration_kind(source.kind))',
        '(source.kind != LSF_DEVICE_PCI && source.kind != LSF_DEVICE_VIRTIO &&\n'
        '         !lsf_device_registration_kind(source.kind))')
    local.edit('    if ((source.kind == LSF_DEVICE_PCI && record->bytes < sizeof(struct pci_dev)) ||',
        '    if ((source.kind == LSF_DEVICE_VIRTIO && record->bytes < sizeof(struct virtio_device)) ||\n'
        '        (source.kind == LSF_DEVICE_PCI && record->bytes < sizeof(struct pci_dev)) ||')
    local.edit('    if (source.kind == LSF_DEVICE_PCI) {',
        '    if (source.kind == LSF_DEVICE_PCI || source.kind == LSF_DEVICE_VIRTIO) {')
    registration.edit(original, local.finish())
    signature = 'int lsf_factory_device_registration_kobject('
    original = _body(registration.text, path, signature)
    at = original.index('\n{\n')+3
    registration.edit(original, original[:at]+
        '\n    int virtio = lsf_factory_stream_virtio_registration_kobject(kobject, copy);\n'
        '    if (virtio) return virtio;\n'+original[at:])
    signature = 'static int lsf_factory_device_registration_current_locked('
    original = _body(registration.text, path, signature)
    local = Editor(original)
    local.edit('(source.kind == LSF_DEVICE_PCI || source.kind == LSF_DEVICE_KERNFS_NODE)',
        '(source.kind == LSF_DEVICE_PCI || source.kind == LSF_DEVICE_VIRTIO ||\n'
        '        source.kind == LSF_DEVICE_KERNFS_NODE)')
    local.edit('        (owned = lsf_factory_device_registration_parent_locked(source)) &&',
        '        (owned = lsf_factory_device_registration_parent_locked(source)) &&\n'
        '        lsf_stream_virtio_registration_bind_locked(source) &&')
    registration.edit(original, local.finish())
    signature = 'void *lsf_factory_device_registration_allocate('
    original = _body(registration.text, path, signature)
    old = '(source.kind != LSF_DEVICE_PCI && source.kind != LSF_DEVICE_KERNFS_NODE)'
    require(original.count(old) == 1, 'constructor-registration-closed-allocation-parent')
    registration.edit(original, original.replace(old,
        '(source.kind != LSF_DEVICE_PCI && source.kind != LSF_DEVICE_VIRTIO &&\n'
        '         source.kind != LSF_DEVICE_KERNFS_NODE)'))
    result[path] = registration.finish().encode()
    sysfs = Editor(outputs['net/factory-device-sysfs.c'].decode())
    original = _body(sysfs.text, 'net/factory-device-sysfs.c', 'int lsf_factory_device_sysfs_release(')
    require(original.count(old) == 1, 'constructor-registration-closed-return-parent')
    sysfs.edit(original, original.replace(old,
        '(source.kind != LSF_DEVICE_PCI && source.kind != LSF_DEVICE_VIRTIO &&\n'
        '         source.kind != LSF_DEVICE_KERNFS_NODE)'))
    result['net/factory-device-sysfs.c'] = sysfs.finish().encode()


def _proc(result, source):
    path = 'drivers/pci/proc.c'
    pci = Editor(source[path].decode())
    _include(pci, '#include <linux/pci.h>\n')
    original = _body(pci.text, path, 'int pci_proc_attach_device(')
    clone = _clone(original, 'lsf_stream_constructor_pci_proc_attach_device', [
        ('\tret = __pci_proc_attach_bus(bus);\n\tif (ret)\n\t\treturn ret;',
         '\t/* Existing global bus directory only; no shared proc_mkdir birth. */\n'
         '\tret = bus->procdir ? 0 : -EOPNOTSUPP;\n\tif (ret)\n\t\treturn ret;'),
        ('\tentry = proc_create_data(name, S_IFREG | S_IRUGO | S_IWUSR,\n'
         '\t\t\t\t bus->procdir, &proc_bus_pci_ops, dev);',
         '\tentry = lsf_prepaid_stream_proc_create(dev, name, bus->procdir, &proc_bus_pci_ops);'),
    ])
    clone = 'static ' + clone
    pci.edit(original, '#ifdef CONFIG_LSF_STREAM_FACTORY\n' + clone + '#endif\n' +
        _wrap(original, '\tint selected = lsf_factory_stream_probe_current(dev);\n'
            '\tif (selected) return selected < 0 ? selected :\n'
            '\t\tlsf_stream_constructor_pci_proc_attach_device(dev);\n'))
    pci.edit(pci.text, pci.text+'''
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_stream_pci_proc_ops_known(const struct proc_ops *ops)
{
    return ops == &proc_bus_pci_ops;
}
int lsf_prepaid_stream_pci_proc_current(struct pci_dev *pci,
    const struct proc_dir_entry *parent, const struct proc_ops *ops)
{
    lockdep_assert_held(&pci_proc_lock);
    if (lsf_factory_stream_probe_current(pci) != 1) return 0;
    /* The original PCI bus reference and pci_proc_lock protect this existing
     * native directory; no Root adopts or returns global parent storage. */
    return pci->bus && pci->bus->procdir && pci->bus->procdir == parent &&
        !pci->procent && ops == &proc_bus_pci_ops;
}
#endif
''')
    result[path] = pci.finish().encode()
    generic = Editor(source['fs/proc/generic.c'].decode())
    _include(generic, '#include <linux/idr.h>\n')
    # Actual PCI type/macros are visible in this allocating TU, never copied.
    generic.edit('#include <linux/idr.h>\n', '#include <linux/idr.h>\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <linux/pci.h>\n#endif\n')
    original = _body(generic.text, 'fs/proc/generic.c', 'void pde_free(')
    generic.edit(original, _wrap(original,
        '\tint selected = lsf_prepaid_stream_proc_free(pde);\n'
        '\tif (selected) return; /* Actual owned lastref or retained unknown. */\n'))
    lookup = _body(generic.text, 'fs/proc/generic.c', 'struct dentry *proc_lookup_de(')
    anchor = '\tif (de) {\n\t\tpde_get(de);'
    replacement = '''\tif (de) {
#ifdef CONFIG_LSF_STREAM_FACTORY
\t\t/* Actor-independent owned-PDE classification precedes pde_get and
\t\t * inode/opener allocation. Expected private-profile denial is NOT
\t\t * Root poison and has the actual dentry/error return contract. */
\t\tif (lsf_factory_stream_proc_classify(de)) {
\t\t\tread_unlock(&proc_subdir_lock);
\t\t\treturn ERR_PTR(-EOPNOTSUPP);
\t\t}
#endif
\t\tpde_get(de);'''
    require(lookup.count(anchor) == 1, 'constructor-proc-lookup-before-reference')
    generic.edit(lookup, lookup.replace(anchor, replacement))
    clones = []
    original = _body(source['fs/proc/generic.c'].decode(), 'fs/proc/generic.c', 'int proc_alloc_inum(')
    clones.append('static '+_clone(original, 'lsf_stream_constructor_proc_alloc_inum', [
        ('\ti = ida_alloc_max(&proc_inum_ida, UINT_MAX - PROC_DYNAMIC_FIRST,\n\t\t\t  GFP_KERNEL);',
         '\ti = lsf_prepaid_stream_ida_alloc_existing(&proc_inum_ida, 0, UINT_MAX - PROC_DYNAMIC_FIRST);'),
    ]))
    original = _body(source['fs/proc/generic.c'].decode(), 'fs/proc/generic.c', 'static struct proc_dir_entry *__proc_create(')
    clones.append(_clone(original, 'lsf_stream_constructor_proc_create', [
        ('(struct proc_dir_entry **parent,', '(struct pci_dev *pci, struct proc_dir_entry **parent,'),
        ('\tent = kmem_cache_zalloc(proc_dir_entry_cache, GFP_KERNEL);',
         '\tif (qstr.len + 1u > SIZEOF_PDE_INLINE_NAME) goto out;\n'
         '\tent = lsf_factory_stream_proc_allocate(pci, SIZEOF_PDE, __alignof__(struct proc_dir_entry));'),
    ]))
    original = _body(source['fs/proc/generic.c'].decode(), 'fs/proc/generic.c', 'struct proc_dir_entry *proc_create_reg(')
    clones.append('static '+_clone(original, 'lsf_stream_constructor_proc_create_reg', [
        ('(const char *name,', '(struct pci_dev *pci, const char *name,'),
        ('\tp = __proc_create(parent, name, mode, 1);',
         '\tp = lsf_stream_constructor_proc_create(pci, parent, name, mode, 1);'),
    ]))
    original = _body(source['fs/proc/generic.c'].decode(), 'fs/proc/generic.c', 'struct proc_dir_entry *proc_register(')
    clones.append('static '+_clone(original, 'lsf_stream_constructor_proc_register', [
        ('\tif (proc_alloc_inum(&dp->low_ino))',
         '\tif (lsf_factory_stream_proc_current(dp) != 1 ||\n'
         '\t    lsf_stream_constructor_proc_alloc_inum(&dp->low_ino))'),
        ('\treturn dp;', '\tif (lsf_factory_stream_proc_registered(dp) != 1) {\n'
         '\t\tproc_remove(dp); /* Real unlink/rundown; unknown bank stays retained. */\n'
         '\t\treturn NULL;\n\t}\n\treturn dp;'),
    ]))
    raw = _constructor_source('stream-constructor-proc.c')
    marker = '/* Source-generated full native clones are inserted HERE before this entry. */'
    require(raw.count(marker.encode()) == 1 and b'\r' not in raw, 'constructor-proc-source-template')
    result['fs/proc/lsf-stream-constructor-proc.c'] = raw.replace(marker.encode(),
        ('\n'.join(clones)).encode())
    generic.edit(generic.text, generic.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-stream-constructor-proc.c"\n#endif\n')
    result['fs/proc/generic.c'] = generic.finish().encode()
    inode = Editor(source['fs/proc/inode.c'].decode())
    _include(inode, '#include "internal.h"\n')
    rundown = _body(inode.text, 'fs/proc/inode.c', 'void proc_entry_rundown(')
    close = rundown.rfind('\n}')
    inode.edit(rundown, rundown[:close]+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t(void)lsf_factory_stream_proc_rundown(de);\n#endif'+rundown[close:])
    # Defense for any direct native caller outside the supported lookup edge:
    # preserve proc_get_inode's original NULL allocation-failure contract. It
    # is NOT relabelled EOPNOTSUPP; supported lookup returns that error above.
    original = _body(inode.text, 'fs/proc/inode.c', 'struct inode *proc_get_inode(')
    inode.edit(original, _wrap(original,
        '\tif (lsf_factory_stream_proc_classify(de)) {\n'
        '\t\tpde_put(de); /* Original incoming native PDE ref, as on new_inode failure. */\n'
        '\t\treturn NULL;\n\t}\n'))
    result['fs/proc/inode.c'] = inode.finish().encode()
    result['fs/proc/internal.h'] = source['fs/proc/internal.h']


def _pci_attrs(result, source):
    path = 'drivers/pci/pci-sysfs.c'
    editor = Editor(source[path].decode())
    _include(editor, '#include <linux/pci.h>\n')
    original = _body(editor.text, path, 'static int pci_create_attr(')
    editor.edit(original, _wrap(original,
        '\tint selected = lsf_factory_stream_bind_selected(pdev);\n'
        '\tif (selected) return selected < 0 ? selected :\n'
        '\t\tlsf_prepaid_stream_pci_create_attr(pdev, num, write_combine);\n'))
    original = _body(editor.text, path, 'static void pci_remove_resource_files(')
    editor.edit(original, _wrap(original,
        '\tint selected = lsf_factory_stream_bind_selected(pdev);\n'
        '\tif (selected) {\n'
        '\t\tif (selected > 0) lsf_prepaid_stream_pci_remove_resource_files(pdev);\n'
        '\t\treturn; /* Unknown never frees or dereferences an unproved attr. */\n\t}\n'))
    editor.edit(editor.text, editor.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-stream-constructor-pci-attrs.c"\n#endif\n')
    result[path] = editor.finish().encode()


def _no_growth_idr(result, outputs):
    path = 'lib/radix-tree.c'
    editor = Editor(outputs[path].decode())
    _include(editor, '#include <linux/radix-tree.h>\n')
    for signature, kind, current in (
        ('void __rcu **lsf_prepaid_device_idr_get_free(',
         'LSF_REGISTRATION_KIND_NODE', 'lsf_factory_device_registration_current'),
        ('void __rcu **lsf_prepaid_stream_classdir_idr_get_free(',
         'LSF_STREAM_CLASSDIR_NODE', 'lsf_factory_stream_classdir_current'),
        ('void __rcu **lsf_prepaid_stream_netdev_directory_idr_get_free(',
         'LSF_STREAM_NETDEV_DIRECTORY_NODE', 'lsf_factory_stream_netdev_directory_current'),
    ):
        original = _body(editor.text, path, signature)
        branch = ('\tif (lsf_factory_stream_constructor_mode()) {\n'
            '\t\tif (source.kind != '+kind+' || '+current+'(source) != 1)\n'
            '\t\t\treturn ERR_PTR(-EOPNOTSUPP);\n'
            '\t\treturn lsf_prepaid_stream_idr_get_free_existing(root, iter, max);\n\t}\n')
        editor.edit(original, _wrap(original, branch))
    editor.edit(editor.text, editor.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-stream-constructor-idr.c"\n#endif\n')
    result[path] = editor.finish().encode()


def transform(outputs, primary):
    constructor_sources()
    require(type(outputs) is dict and len(outputs) == 381 and
            all(type(n) is str and type(b) is bytes for n, b in outputs.items()),
            'constructor-frozen-input-map')
    canonical = (json.dumps({n: {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
        for n, b in outputs.items()}, sort_keys=True, separators=(',', ':')) + '\n').encode()
    require(hashlib.sha256(canonical).hexdigest() == INPUT_SHA, 'constructor-whole-381-input')
    require(type(primary) is dict and set(primary) == set(PRIMARY), 'constructor-closed-primaries')
    for name, pin in PREIMAGES.items():
        require(_bound(outputs[name], pin), 'constructor-whole-selected-source')
    for name, pin in PRIMARY.items():
        require(_bound(primary[name], pin), 'constructor-whole-primary-source')
    source = {**outputs, **primary}
    for key in BODIES:
        name, signature = key.split('::', 1)
        _body(source[name].decode(), name, signature)
    result = dict(outputs)
    for name, operation, anchor in (
        ('drivers/pci/bus.c', _pci_bus, '#include <linux/pci.h>\n'),
        ('drivers/pci/pci-driver.c', _pci_driver, '#include <linux/pci.h>\n'),
        ('drivers/virtio/virtio_pci_common.c', _vp, '#include "virtio_pci_common.h"\n'),
        ('drivers/virtio/virtio.c', _registration, '#include <linux/virtio.h>\n'),
        ('drivers/base/dd.c', _attach, '#include "base.h"\n'),
    ):
        editor = Editor(source[name].decode())
        _include(editor, anchor)
        operation(editor)
        result[name] = editor.finish().encode()
    core = Editor(outputs['net/factory-device-core.c'].decode())
    _device_core(core)
    result['net/factory-device-core.c'] = core.finish().encode()
    _state_and_lifetime(result, outputs)
    _proc(result, source)
    _registration_route(result, outputs)
    _pci_attrs(result, source)
    _no_growth_idr(result, outputs)
    virtio_net = Editor(outputs['drivers/net/virtio_net.c'].decode())
    _include(virtio_net, '#include <linux/netdevice.h>\n')
    virtio_net.edit(virtio_net.text, virtio_net.text + '''
#ifdef CONFIG_LSF_STREAM_FACTORY
int lsf_prepaid_stream_virtio_driver_known(const struct device_driver *driver)
{
    if (driver != &virtio_net_driver.driver || !IS_BUILTIN(CONFIG_VIRTIO_NET)) return 0;
    return virtio_net_driver.probe == virtnet_probe &&
        virtio_net_driver.remove == virtnet_remove &&
        virtio_net_driver.validate == virtnet_validate &&
        virtio_net_driver.config_changed == virtnet_config_changed &&
        virtio_net_driver.id_table == id_table &&
        virtio_net_driver.feature_table == features &&
        virtio_net_driver.feature_table_size == ARRAY_SIZE(features) &&
        virtio_net_driver.feature_table_legacy == features_legacy &&
        virtio_net_driver.feature_table_size_legacy == ARRAY_SIZE(features_legacy)
#ifdef CONFIG_PM_SLEEP
        && virtio_net_driver.freeze == virtnet_freeze && virtio_net_driver.restore == virtnet_restore
#endif
        ;
}
#endif
''')
    result['drivers/net/virtio_net.c'] = virtio_net.finish().encode()
    for destination, name in OWNED_FILES.items():
        require(destination not in outputs, 'constructor-new-owned-destination')
        raw = _constructor_source(name)
        require(raw and len(raw) < 32768 and b'\r' not in raw, 'constructor-new-owned-source')
        result[destination] = raw
    # This source draft is not selected by an owner. VIRTIO registration/kernfs,
    # actual proc last-reference and constructor rollback are reviewed together
    # before a complete source packet can be frozen.
    return result


# Physical packaging only. Every logical source below is the exact separately
# reviewed C/H payload; no historical input file or native body is rewritten.
CONSTRUCTOR_BUNDLE = 'research/standard-outbound/linux-6.12-lineage/stream-constructor-sources.json'
CONSTRUCTOR_BUNDLE_PIN = (182209, 'ccfd474c1aee18d19230b7e508e4181b156270e617b7618a9d7d22e6de3a467b')
CONSTRUCTOR_BUNDLE_ROWS = (('research/standard-outbound/linux-6.12-lineage/factory-stream-constructor.c', 'c', 25464, 'dd8823018cf0393d61f1cc27fe5acdc6d1b9a5dc54edefe07c84e88be0905f57'), ('research/standard-outbound/linux-6.12-lineage/factory-stream-mapping.c', 'c', 13001, 'c6df579b6778092207e785540c7d21f08ddc961778b96470ad8fefa7b6f8f97d'), ('research/standard-outbound/linux-6.12-lineage/factory-stream-mmio.c', 'c', 20797, 'e8c0148e3fe47a5824b923b5721ab01b14d03575538660587e1e7fb36cde1fab'), ('research/standard-outbound/linux-6.12-lineage/factory-stream-pci-attrs.c', 'c', 7188, '9fc4e85faaec3f8baca9f1bf4222efe3c7ead3ffb49a66b53a6e145c033e5dd1'), ('research/standard-outbound/linux-6.12-lineage/factory-stream-proc.c', 'c', 9785, '4fc7bb5f0743ee68b1a6fecac8e431d68e90e1adbafa7457bfaf074154f396a9'), ('research/standard-outbound/linux-6.12-lineage/factory-stream-pte.c', 'c', 8302, '761d716b7b8f43ee382af238c54c922265d8ae2899db1ae49920bef65d47d73a'), ('research/standard-outbound/linux-6.12-lineage/factory-stream-virtio-core.c', 'c', 16801, '60168b066c6e6cb7725a159aa45fba683bbb25ac37007f63bb45d5cf7c4ead23'), ('research/standard-outbound/linux-6.12-lineage/factory-stream-virtio-registration.c', 'c', 4997, '32e283bb525a8251d242690c505077a4988731b1b38f54439613bf7caf1edbca'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-ida.c', 'c', 3512, '43a3889aeafbfcb2658121eedeef4d74ad02406b166b22c9b5aeacde32654d51'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-idr.c', 'c', 2861, '7ac49feb6280e68f8d018deeca4947546eb0da44a1ebecb71325393fd6271d97'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-ioremap.c', 'c', 6939, '617485774e4558f534c77745b13e441fd2f0f01742d14f33bd0c2feda46209c5'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-mapping-private.h', 'h', 1871, '0a515054501176035f188e2dbfcab1ae81291788fbdb67739113e3985649776e'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-mmio-modern.c', 'c', 5872, 'a24ae119fbd37110fd9b2e42acbc02701578f220fb1633d5c589cba4e52c13bc'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-mmio-private.h', 'h', 2517, '9ffc59c1fb56791f61565fdf5361fc7eab4b903a3e8d7b5593481b3327a623da'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-pat-interval.c', 'c', 1377, 'b18467871a14f6dbd86241c174ac863190222776a4c2d503f6a11673abcc9db7'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-pat.c', 'c', 3787, '3eac9b1b0e3c6706e8303b346b9c845d106787e8725c74026df39b47328d7f94'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-pci-attrs.c', 'c', 5662, '78b832892210da4052940f115e228ac03ee428b44a0764012a14502d7053bed7'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-private.h', 'h', 5090, 'dbba838eb9d502ff758268f07fd72680192d992281087833f09f892c45236d72'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-proc.c', 'c', 2262, '74c1b447abcdebc31814f557954bac6ad979fc642cd6bfcce483e8b8350e9977'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-pte-private.h', 'h', 734, 'd5b708beabfda360850530e57e65249761d4a23ac54e0fd07e274f9c0f014c4f'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-resource.c', 'c', 2253, '32554154e79c2447c29a0f0a8a16151b7da9eae7ab183ab52b91ae550d8c9d66'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-vwindow-ancestors.c', 'c', 5488, 'f9132f09f291d3d815346e8f3809a909ec3024b1b4b3718d6a984de1728c0c07'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-vwindow-mmio.c', 'c', 7758, '1ab463f412ccf89f5ce92ea87421afc5d527bb9af03bfe786e1e1c2be8466ce4'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-vwindow-private.h', 'h', 364, '7a44cd17c13f90a612b99baeeeeddd1ec9ebf750a776bf7d739692d217758a58'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-vwindow-pte.c', 'c', 4756, 'cecbafb1e54f5cb626bfc84739f5272d094138fcae458c4c19f0e00b98aef58d'), ('research/standard-outbound/linux-6.12-lineage/stream-constructor-vwindow.c', 'c', 3106, '0ef4911f9c2359a680d162d76c708df590598198f455e29350949aabae36df75'))
CONSTRUCTOR_EXISTING_INPUTS = {'research/standard-outbound/linux-6.12-lineage/device-prepaid.h': (12881, '74ca3148bcf376f2aa8dccef2a776a80e8c1c41fbbeccf0666f5c7cef0dfa043'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-classdir-registration.c': (23017, 'ba0ef3d1e561c0fd6f6bb1a2794ae317692b726b25687a3bdab8d9945e0bb77a'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-find-vqs.c': (6162, '52db6f6db5a4603124ea8ed90677cedd0c543ef1b7306178ebe32aa0254c50b2'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-material-arena.c': (3263, '8a78a41d72dd8771020108b6527ff4031292be21253d5b91f04907f6c22bed06'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-material-plan.c': (15157, '0c07408ef6251454fb2bece1c91602abc0ce1ffcaba2c07268a371ab2188a1df'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-address.c': (8477, 'fcf6eb3e568526364cd6a84d0f44a9317843c05b56bbcd7c111e4e5eda118400'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-classdir.c': (18406, 'e7416ddc0453d1d837f096e5cdfdc6843075bf198192b8a1cfa9b6c8b8ff292b'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-core.c': (18545, '418bca3f30763011adc9a05619922674bb92dda6608177d08be7ce36700a04d8'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-cpu.c': (4485, '838d4b160c61e9db278ff764c56539e50ea0149024e1ec325a0912c73cf783e3'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-directory.c': (27541, '5283326bc30a5be56069de0fb37eb13b85231ef8f973dbcebf0591f9dace0ee9'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-fixed.c': (15763, '0595ac6452778ad6222f157265f4222c6c4b46964c3b7e0db885e2d5232b1637'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-name.c': (6207, '33bacd944a2c9104af813baf228fc2032bb84211a330cdb50af07e39b31bdc9e'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-notify.c': (4160, 'de1a386a3ffbe8631ee8cc095edda154797aea4a3a10470ac065660b139964fa'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-post-init.c': (2333, '851a19b929c500403ac04a38f05ba18f2a8e6c86ac763c302487914eae80cba6'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-operations.c': (25328, '54bb347dfc97b9d6cca25ffa6e85fe0ef1ff344e69a864646533447ce46459f2'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-retirement.c': (5812, '63c40d61187219fc6d5c3235d35e6b9088f9348c3df245fc5365304d5c759473'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-root-final-free.c': (12765, '2aa32c9afd9b1b750e5251d54b60d81a550b679e8887a9457afb73f6c61d4e8a'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-rss.c': (6520, 'a272bd5a0a4f6ce93a779d6af52bc30c44eeb08dcccf17e5bb4262dcb46f99b8'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-rx-preallocate.c': (46154, '8e9f72047e57e21aca6eefe5b071760924723b4bfc48fa666c95dc10ba65883f'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-stop.c': (5778, '0792867d3207d55cfd126c3d5ce78658f1660b90144eeb8b9606f2629bece2ac'), 'research/standard-outbound/linux-6.12-lineage/factory-stream-udp-cork.c': (4594, '105ee5984eb64b29385708fced8ca549a3a344cf9f4f27eef65e98f070bfe868'), 'research/standard-outbound/linux-6.12-lineage/stream-classdir-registration-private.h': (2563, '5452764a0e25ef3143a5d399bf18c8e2f9e6cf6c897e20921d7718a96517982a'), 'research/standard-outbound/linux-6.12-lineage/stream-material-geometry-private.h': (1607, '272a9e2f310d87aee62b1b8046730604660deb04afe07237e8b81d7011336710'), 'research/standard-outbound/linux-6.12-lineage/stream-net-geometry.c': (3339, '5c6dc56be1aaf09884c626b0683570c3415f0e1811f4518f2536abf6736b2a4e'), 'research/standard-outbound/linux-6.12-lineage/stream-net-material-geometry.c': (2007, 'daaf16fb5a052f48b992aaa3ef135b0f8bbbb4723bc63a18760b875e6b985010'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-classdir-private.h': (1207, '26ec30fc7b6e7b4d7c12685ee18fdd93a716a7fb735f8b258cbbf95888838162'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-core-private.h': (984, 'ac87c17ee8bc74ffb8d4403e26b2d2ccd595275cfc162a80aa55d1c3bf29a3ee'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-cpu-private.h': (1017, '0df763bc0df5095b30a486882bde42d999853481c24e7a41bba6142635d5c2b5'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-cpu.c': (4181, '4593851c0b4b06be4bf8f4b9ea0b5525fdc8b258c83e494157a7121661d7d723'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-directory-private.h': (2714, '845e44ced2aeb21e6594ddc00560717be38a179526ff20366a98169c2aeb5ba9'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-fixed-geometry-private.h': (719, 'c0f6b7a6f14dd517413aa38df8a311e6182716a07bc206ae34d204e655c670fe'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-fixed-geometry.c': (1705, '69076854e8150be58f4be3b77b4dced5092712447c906b0e524305cba3859452'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-fixed-private.h': (1073, '5f5494f65d89970f754cd9c27306b9619f579ea8c178bffa0eaead4fdaedc3bb'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-name-private.h': (507, '8189b45f311a8b7c4e59e1d8a8dd995a28c1c359542d8dc61d3245ca73e86db3'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-notify-private.h': (1356, 'aec949a49be91717099a67b26dbee4aad0fd7a09d880ac8ec5fde7d408e90518'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-post-init-private.h': (1216, '4a5ebe566862e72851f8a4c52cfe0ea2406bfe4c56557dacffcb2ac5b70cf3d3'), 'research/standard-outbound/linux-6.12-lineage/stream-netdev-private.h': (704, '04bf5b72b6f8501dce73ea797407cdb730bf30d712b681e12be9f0a2796c09c3'), 'research/standard-outbound/linux-6.12-lineage/stream-operation-private.h': (1921, '00d7ef28ac43fdeb170bea8c11cfef4c8e47facb365e05576705e21ad7a197f3'), 'research/standard-outbound/linux-6.12-lineage/stream-owned-ring.c': (5870, '53d295a4b0ff26b3242ac4b4971c1e4f1b6bb36df2bfd2794cb770ae4db12de3'), 'research/standard-outbound/linux-6.12-lineage/stream-pci-material-geometry.c': (1995, '6e1b2777a456bcd315863cbbf5a2931eecff1bbb24b393084ae398544c2ff39e'), 'research/standard-outbound/linux-6.12-lineage/stream-protocol-allocation.c': (2171, '389449637b5400a78550d9a9884eb4288ba6800cc1c38cb62b628ab56e40a840'), 'research/standard-outbound/linux-6.12-lineage/stream-ring-geometry.c': (1610, '5fcf4504dfaba27b3be6ac72407b32b06e18ec628f7fb3710e53b199aa3da107'), 'research/standard-outbound/linux-6.12-lineage/stream-ring-profile-private.h': (4137, 'add54b6326de79e80dc4c8ba16f47193955c2c70baaf9edfdffa83b93d0d9a8b'), 'research/standard-outbound/linux-6.12-lineage/stream-skb-dispatch.c': (2858, '7007a4e36e41f2a48be51e2f659be266f1bc02da446ab1060dbb9f2d5ef4908a'), 'research/standard-outbound/linux-6.12-lineage/stream-udp-cork-private.c': (2104, 'da95be8e9805ab710636750440faec414b201ba9627473e7dfeabcd6f26e0600'), 'research/standard-outbound/linux-6.12-lineage/stream-udp-private.c': (1020, '8d82189773d0de5259a538e8b0fe3b7e5e4a10de6495da2027b6fe526929c1ed'), 'tools/host_stream_kernel_stream_classdir.py': (32823, '80746dc34eaf4c6aaebeb595c0c10b8dd016638ec46ab9067262f324081107c7'), 'tools/host_stream_kernel_stream_core.py': (9665, '533d7e480d29a71d694b1ca289cd5871b34ddbbcbf7154b2ad7ef51988cf139e'), 'tools/host_stream_kernel_stream_cpu.py': (8517, 'ede9797ee9f07391ef3d6155045aad3129eaee6827f851667da208b6ede737a8'), 'tools/host_stream_kernel_stream_fixed_netdev.py': (12283, 'b18a152ea75ccdc9036e303a01e33246a32cc9fe2121aa45bdd7d4dd768406a4'), 'tools/host_stream_kernel_stream_layout.py': (27719, '21fa6de11a8bd0f1288e885230ef349b3568ae0567238899147e11ba0c9c5da1'), 'tools/host_stream_kernel_stream_name.py': (5485, 'b71ebb68dfb08f1320d2245989ca1fe7dd0fd4d2b687579de81df55a23c16e6d'), 'tools/host_stream_kernel_stream_netdev.py': (6378, '53cef49ed39481d0c8f1c3866bd7ed59f60e3255744e1028971d7bb89afea9e2'), 'tools/host_stream_kernel_stream_netdev_directory.py': (18727, 'd3842295fc76cac2d4df12935d7c99a354766318dfba3717ccf11c8b7a750c63'), 'tools/host_stream_kernel_stream_netdev_notify.py': (17547, '027a8439ee86297aaafb2acd3247accae91783be8e7d5a6b0c1678a4a6e44e41'), 'tools/host_stream_kernel_stream_operations.py': (3185, 'f7aafa20f00c07a9e8a3ebee93a1c31cec0a2e58af58f0bb66c2e85435893523'), 'tools/host_stream_kernel_stream_post_init.py': (15621, 'e5f0512c85a60257736d773c0d7ea57aea99c2bd102037e007d249bc0e1e0e89'), 'tools/host_stream_kernel_stream_protocol.py': (9580, '8f23fbc26362894f93026855f7de5303a39b9ff8bfbabbb6b9272392514244e4'), 'tools/host_stream_kernel_stream_rss_failure.py': (2771, '91d57a5fdce6427ef23fc0d974680f99e5e525840a751574670affdab61ad5a3'), 'tools/host_stream_kernel_stream_rx.py': (22587, '0003ffb37b166194f35c8bf0d2689d6f3700649866d918f8e9a0d87b3021f697'), 'tools/host_stream_kernel_stream_skb.py': (6935, 'af0d43d86dba54b6cb0ecdd29e84d55868c0859500ed9d3cf9ffe7e8fa9b83c4'), 'tools/host_stream_kernel_stream_udp.py': (10833, '03bc18a026b0c23619aa7fb7978f7e37dc755e2b80757ba2b62d37e54cb3ea00')}
CONSTRUCTOR_PROJECTORS = ('tools/host_stream_kernel_stream_constructor.py', 'tools/host_stream_kernel_stream_vwindow.py')


def _constructor_read(path, length):
    require(type(length) is int and 0 < length <= 262144 and
        path.is_file() and not path.is_symlink(), 'constructor-source-physical-file')
    with path.open('rb') as stream:
        raw=stream.read(length+1)
    require(len(raw)==length, 'constructor-source-physical-length')
    return raw


def _constructor_object(pairs):
    result={}
    for key,value in pairs:
        require(type(key) is str and key not in result, 'constructor-bundle-duplicate-key')
        result[key]=value
    return result


def _constructor_decode(raw):
    require(_bound(raw,CONSTRUCTOR_BUNDLE_PIN), 'constructor-bundle-whole-identity')
    require(raw.endswith(b'\n') and b'\r' not in raw and b'\0' not in raw,
            'constructor-bundle-encoding')
    value=json.loads(raw.decode('utf8',errors='strict'), object_pairs_hook=_constructor_object,
                     parse_constant=lambda value: require(False,'constructor-bundle-json-constant'))
    require(type(value) is dict and list(value)==['schema','sources'] and
        value['schema']=='lsf.stream-constructor-sources.v1' and type(value['sources']) is list and
        len(value['sources'])==26, 'constructor-bundle-schema')
    result={}
    for row,pin in zip(value['sources'],CONSTRUCTOR_BUNDLE_ROWS):
        name,kind,length,sha=pin
        require(type(row) is dict and list(row)==['name','type','bytes','sha256','text'] and
            type(row['name']) is str and row['name']==name and name not in result and
            type(row['type']) is str and row['type']==kind and
            type(row['bytes']) is int and row['bytes']==length and
            type(row['sha256']) is str and row['sha256']==sha and
            type(row['text']) is str, 'constructor-bundle-ordered-source-row')
        payload=row['text'].encode('utf8',errors='strict')
        require(0<len(payload)<32768 and _bound(payload,(length,sha)) and
            b'\r' not in payload and b'\0' not in payload and payload.endswith(b'\n'),
            'constructor-bundle-logical-identity')
        result[name]=payload
    return result


def constructor_sources():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    return _constructor_decode(_constructor_read(root/CONSTRUCTOR_BUNDLE,CONSTRUCTOR_BUNDLE_PIN[0]))


def _constructor_source(name):
    require(type(name) is str and '/' not in name and '\\' not in name and
        name not in ('.','..'), 'constructor-bundle-logical-name')
    key='research/standard-outbound/linux-6.12-lineage/'+name
    sources=constructor_sources()
    require(key in sources, 'constructor-bundle-unknown-source')
    return sources[key]


def constructor_input_materials():
    """Fixed actual physical rows plus separately labelled logical sources.

    A logical C/H name is not claimed to be a raw Git path: its origin is the
    actual pinned container and ordinal. The two current projector identities
    are computed from their actual bytes, never from a recursive self-pin.
    """
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    sources=constructor_sources()
    physical={}; logical={}; origins={}
    for name,(length,sha) in CONSTRUCTOR_EXISTING_INPUTS.items():
        raw=_constructor_read(root/name,length)
        require(_bound(raw,(length,sha)), 'constructor-existing-physical-identity')
        row={'bytes':length,'sha256':sha}
        physical[name]=row;logical[name]=dict(row)
        origins[name]={'kind':'physical-file','path':name}
    for name in CONSTRUCTOR_PROJECTORS:
        path=root/name
        require(path.is_file() and not path.is_symlink(), 'constructor-projector-physical-file')
        with path.open('rb') as stream: raw=stream.read(131073)
        require(0<len(raw)<=131072 and b'\r' not in raw and raw.endswith(b'\n'),
                'constructor-projector-physical-bound')
        row={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        physical[name]=row;logical[name]=dict(row)
        origins[name]={'kind':'physical-file','path':name}
    # The second read is also whole-pinned. Mutations cannot switch authority
    # between the decoded logical payloads and the actual physical identity.
    container=_constructor_read(root/CONSTRUCTOR_BUNDLE,CONSTRUCTOR_BUNDLE_PIN[0])
    require(_bound(container,CONSTRUCTOR_BUNDLE_PIN), 'constructor-container-recheck')
    physical[CONSTRUCTOR_BUNDLE]={'bytes':len(container),'sha256':CONSTRUCTOR_BUNDLE_PIN[1]}
    for ordinal,(name,kind,length,sha) in enumerate(CONSTRUCTOR_BUNDLE_ROWS):
        require(_bound(sources[name],(length,sha)), 'constructor-logical-material-recheck')
        logical[name]={'bytes':length,'sha256':sha}
        origins[name]={'kind':'utf8-source-bundle','path':CONSTRUCTOR_BUNDLE,
                       'ordinal':ordinal,'sourceType':kind}
    require(len(physical)==65 and len(logical)==90 and len(origins)==90,
            'constructor-material-cardinality')
    return {'physicalInputs':physical,'logicalIdentities':logical,'logicalOrigins':origins,
            'projectionOutputCount':427,'runtimeOrFundingQualified':False}
