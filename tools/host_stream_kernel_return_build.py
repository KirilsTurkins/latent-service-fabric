"""Fresh bounded kernel stage after native/C fail-fast checks; no old image reuse."""
import hashlib
import json
from pathlib import Path
from tools import qualify_host_stream_kernel_vm as historical
from tools import host_stream_kernel_return_source as source
from tools import host_stream_kernel_native_vm_inputs as historical_materials

programme, image = historical.programme, historical.image
baseline, objects, paths = historical.baseline, historical.objects, historical.paths
require, tool_identity = historical.require, historical.tool_identity
ROOT = historical.ROOT
late = historical.late
ADDITIONAL_MATERIALS = frozenset((
    'research/standard-outbound/linux-6.12-lineage/native-constructor-vm-init.c',
    'research/standard-outbound/linux-6.12-lineage/factory-retirement-observation.c',
))


def partition_materials(materials, source_before):
    """Retain the complete current set and authenticate the historical subset."""
    require(ADDITIONAL_MATERIALS <= materials.keys(), 'return-additional-materials-missing')
    additional = {name:materials[name] for name in sorted(ADDITIONAL_MATERIALS)}
    for name,bound in additional.items():
        require(source_before.get(name) == {'size':bound['bytes'],'digest':'sha256:'+bound['sha256']},
            'return-additional-material-not-source-bound')
    original = {name:bound for name,bound in materials.items() if name not in ADDITIONAL_MATERIALS}
    canonical = json.dumps(original,sort_keys=True,separators=(',',':')).encode()
    public = historical_materials.public_receipt()
    require(len(original) == 294 and hashlib.sha256(canonical).hexdigest() ==
        public['sourceBinding']['canonicalInventorySha256'],'return-original-294-materials')
    return original,additional


def build(commands, tools, archive, output, receipt):
    # Only called after real Rust controls, ELF validation and C controls pass.
    value = baseline.maintained.manifest()
    source_root = output/'source'
    source_root.mkdir()
    commands.root = source_root
    commands.command_seconds = 1800
    archive = objects.snapshot_archive(archive,output/'source.tar.xz',value['archive'])
    extras = {'net/Kconfig','net/Makefile'} | set(objects.packet_source.fixture()['source'])
    originals = baseline.maintained.authenticate_archive(archive,value,
        tuple(sorted(extras-set(value['source']))))
    receipt['archive'] = objects.identity(archive)
    local, recipe = programme.local_freeze(), historical.recipe_inputs()
    receipt['stage'] = 'extract'
    commands.run('extract-authenticated-source',tools['tar'],'--extract','--xz',
        '--file',str(archive),'--directory',str(source_root),'--no-same-owner','--no-same-permissions')
    tree = source_root/('linux-'+value['version'])
    commands.root = tree
    require(all((tree/name).read_bytes() == raw for name,raw in originals.items()),
        'constructor-vm-extracted-preimage')
    receipt['stage'] = 'baseline-source-and-config'
    base, frozen, old_originals = programme.baseline_source(tree,originals)
    receipt['baselineSourceFreeze'] = frozen
    # Preserve ALL historical producer materials as historical source evidence.
    # New observer inputs are separately bound by the new source/recipe inventory.
    materials = {}
    for group in (recipe,local,frozen):
        for name,bound in group.items():
            require(name not in materials or materials[name] == bound,'return-conflicting-old-material')
            materials[name] = bound
    original,additional = partition_materials(materials,receipt['sourceBefore'])
    receipt['historicalKernelProducerMaterials'] = original
    receipt['additionalKernelProducerMaterials'] = additional
    receipt['compiledKernelProducerMaterials'] = materials
    receipt['localSourceFreeze'],receipt['recipeInputs'] = local,recipe
    original_inputs = {**old_originals,**originals}
    # Fixed stage names read from this same fully authenticated private
    # extraction. Old archive-extra limits and validators remain unchanged.
    for name in sorted(programme.source_names() - {'selected.config'}):
        if name not in original_inputs:
            original_inputs[name] = paths.read(tree,name,baseline.maintained.MAX_FILE)
    require(sum(map(len,original_inputs.values())) <= baseline.maintained.MAX_SELECTED,
        'constructor-vm-selected-byte-bound')
    receipt['compiledKernelLogSource'] = late.authenticate_printk(
        original_inputs['kernel/printk/printk.c'])
    for name,suffix in (('net/Kconfig',objects.KCONFIG),('net/Makefile',objects.MAKEFILE)):
        raw = original_inputs[name]
        require(objects.SELECTED.encode() not in raw,'constructor-vm-private-config-present')
        (tree/name).write_bytes(raw+suffix.encode())
    build = output/'objects'
    common = [tools['make'],'O='+str(build),'ARCH=x86_64','CC='+str(tools['gcc'])]
    commands.run('compiler-identity',tools['gcc'],'--version')
    commands.run('original-defconfig',*common,'x86_64_defconfig')
    before_raw = (build/'.config').read_bytes()
    (output/'baseline.config').write_bytes(before_raw)
    before = objects.configuration(before_raw)
    require(before.get(objects.SELECTED) == 'n','constructor-vm-private-default-enabled')
    selected_raw = before_raw.replace(b'# CONFIG_LSF_STREAM_FACTORY is not set\n',b'CONFIG_LSF_STREAM_FACTORY=y\n')
    require(selected_raw != before_raw,'constructor-vm-missing-private-config')
    (build/'.config').write_bytes(selected_raw)
    commands.run('resolve-selected-config',*common,'olddefconfig')
    final = (build/'.config').read_bytes()
    baseline.configuration(before,objects.configuration(final))
    (output/'selected.config').write_bytes(final)
    receipt['bootConfiguration'] = image.check_boot_configuration(final, objects.configuration)
    # This generated exact selected config is also independently pinned in
    # the authenticated provider source fixture, never a copied local file.
    receipt['stage'] = 'complete-source-composition'
    canonical,compiler_probes = source.compiler_probe_projection(final)
    fixture_config,historical_projection = programme.source_fixture_configuration(canonical)
    receipt['sourceFixtureConfiguration'] = {'actual':objects.identity(output/'selected.config'),
        'sourceFixture':source.identity(fixture_config),'unselectedCompilerProbeProjection':compiler_probes,
        'historicalDataOnlyProjection':historical_projection,'actualConfigurationMutated':False,
        'rustKernelSelected':False,'allOtherConfigurationBytesExact':True}
    # Retain both real selected bytes and the explicit data-only fixture
    # projection. The actual Kbuild configuration is NEVER rewritten.
    (output/'source-fixture.config').write_bytes(fixture_config)
    normal = programme.compose(base,original_inputs,fixture_config)
    projected, receipt['candidateProjection'] = programme.qualification_projection(normal, final)
    derived, receipt['sourceComposition'] = source.compose(normal, projected)
    audited_originals = {name:paths.read(tree,name,baseline.maintained.MAX_FILE)
        for name in source.fixture()['originals']}
    compiled = {name:derived.get(name,raw) for name,raw in audited_originals.items()}
    receipt['outsideBankLifetimeSource'] = source.authenticate(audited_originals,compiled,final)
    receipt['selectedOriginalInputs'] = {name:objects.identity(tree/name)
        for name in programme.source_names() if name != 'selected.config'}
    receipt['normalDerived'], receipt['derived'] = {}, {}
    for name,raw in derived.items():
        target = tree/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
        if name in normal:
            receipt['normalDerived'][name] = dict(bytes=len(normal[name]),
                sha256=hashlib.sha256(normal[name]).hexdigest())
        receipt['derived'][name] = objects.identity(target)
    paths.write_new(output/'selection.json',(json.dumps(receipt,indent=2)+'\n').encode())
    receipt['stage'] = 'complete-real-kernel-link'
    commands.run('link-complete-candidate-kernel', *common, '-j2', 'bzImage')
    receipt['kernelLinked'] = True
    baseline.generated_configuration((build/'include/generated/autoconf.h').read_bytes())
    require(b'#define CONFIG_RUST ' not in (build/'include/generated/autoconf.h').read_bytes(),
            'constructor-vm-rust-kernel-must-remain-unselected')
    require((build/'.config').read_bytes() == final, 'constructor-vm-build-config-drift')
    built_kernel = build/'arch/x86/boot/bzImage'
    kernel_raw = paths.read(built_kernel.parent,built_kernel.name,image.MAX_KERNEL)
    receipt['kernelImage'] = image.kernel_image(kernel_raw)
    receipt['linkedVmlinux'] = tool_identity(build/'vmlinux',512*1024**2)
    kernel = output/'constructor-bzImage'
    paths.write_new(kernel,kernel_raw)
    # Full bzImage already builds this exact upstream host tool.
    generator = build/'usr/gen_init_cpio'
    require(generator.is_file(), 'constructor-vm-upstream-initramfs-generator-missing')
    receipt['initramfsGenerator'] = tool_identity(generator)
    receipt['generatedAutoconf'] = objects.identity(build/'include/generated/autoconf.h')
    return kernel,generator,tree,derived,final
