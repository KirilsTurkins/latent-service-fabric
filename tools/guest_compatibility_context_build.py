"""Bind owner-emitted runtime/patch receipts after existing immutable-input checks."""
from __future__ import annotations

from pathlib import Path

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_context as context
from tools import guest_emitted_code, guest_runtime_receipts
from tools.dev_workflow.common import decode, digest, encode, integer, members, require, sha
from tools.rust_capsule_project import inventory, read_file, write_json

# Rust's shared Commands/package_inputs module is imported by every owner, so
# its runtime receipt dependency belongs in their common captured closure too.
RECIPE = ('tools/guest_compatibility_context.py', 'tools/guest_compatibility_context_build.py',
          'tools/guest_runtime_receipts.py', 'tools/guest_emitted_code.py',
          'tools/guest_compiler_edges.py', 'tools/guest_compiler_capture.py', 'tools/guest_api_analysis.py')


JAVA_COMPILER_PATCH = 'java-teavm-coroutine-compiler'
JAVA_COMPILER_PATCH_NAMES = frozenset((JAVA_COMPILER_PATCH, 'java-teavm-coroutine-source',
    'java-teavm-array-root-source', 'java-teavm-monitor-source'))


def java_compiler_materials(bindings, profile, recipe):
    """Project the bound compiler owner's receipt, never certify an API."""
    require(isinstance(bindings, dict), 'compatibility-context-java-bindings')
    if 'coroutineCompiler' not in bindings:
        return []  # Historical/base builds have no selected coroutine patch.
    patch = bindings['coroutineCompiler']
    require(isinstance(patch, dict)
            and patch.get('schemaVersion') == 'latent.java.coroutine-compiler-patch.v1',
            'compatibility-context-java-compiler-receipt')
    classes = patch.get('replacedClasses')
    require(isinstance(classes, dict) and 0 < len(classes) <= 32,
            'compatibility-context-java-compiler-classes')
    expected = {}
    for name, row in classes.items():
        require(isinstance(row, dict) and all(isinstance(row.get(key), str)
                for key in ('originalSha256', 'replacementSha256')),
                'compatibility-context-java-compiler-class')
        sha('sha256:' + row['originalSha256'])
        sha('sha256:' + row['replacementSha256'])
        expected[name] = row['replacementSha256']
    loaded = patch.get('loadedCompiler')
    require(isinstance(loaded, dict) and loaded.get('selectedOwnedReplacement') is True and loaded == {
        'schemaVersion': 'latent.java.coroutine-compiler-load.v1',
        'selectedOwnedReplacement': True,
        'replacementJarSha256': patch['replacementJarSha256'],
        'loadedJarSha256': patch['replacementJarSha256'],
        'codeSourceKind': loaded.get('codeSourceKind'), 'loadedClasses': expected}
        and loaded['codeSourceKind'] in {'owned-replacement', 'byte-identical-copy'},
        'compatibility-context-java-compiler-load')
    # Hash the complete already-bound owner receipt, including loaded classes.
    # Only fixed names and digests enter the public context/presentation.
    transformation = digest(encode({'recipeDigest': recipe, 'receipt': patch}))
    pairs = ((JAVA_COMPILER_PATCH, 'originalJarSha256', 'replacementJarSha256'),
        ('java-teavm-coroutine-source', 'upstreamSourceSha256', 'correctedSourceSha256'),
        ('java-teavm-array-root-source', 'upstreamTypeSourceSha256', 'correctedTypeSourceSha256'),
        ('java-teavm-monitor-source', 'upstreamAsyncFinderSourceSha256', 'correctedAsyncFinderSourceSha256'))
    require(all(isinstance(patch.get(key), str) for _, original, selected in pairs
                for key in (original, selected)), 'compatibility-context-java-compiler-identities')
    return [context.material('patch', name, 'sha256:' + patch[selected], profile=profile,
        original='sha256:' + patch[original], transformation=transformation)
        for name, original, selected in pairs]


def dependency_materials(files, source_inputs, language):
    graph = guest_runtime_receipts.captured_graph(files)
    if graph is None:
        return [], 0
    require(inventory(files) == source_inputs, 'compatibility-context-detached-dependency-inventory')
    require(graph.get('language') in (None, language) and isinstance(graph.get('artifacts'), list)
            and len(graph['artifacts']) <= 1024, 'compatibility-context-dependency-graph')
    retained, omitted = [], 0
    for row in graph['artifacts']:
        # This is the already captured graph, never a resolver/catalogue query.
        # Retain only closed public attribution fields, not source locations,
        # arbitrary ecosystem metadata or registry configuration.
        try:
            require(isinstance(row['metadata'], dict), 'compatibility-context-dependency-metadata')
            # A native replacement records the actual selected source version
            # separately. A local replacement has no version; do not borrow
            # the superseded module's requested version for those bytes.
            version = row['metadata'].get('effectiveVersion', row['metadata'].get('version'))
            if version is not None:
                try:
                    context.version_token(version)
                except ValueError:
                    version = None
            retained.append(context.material('dependency', row['id'], row['treeDigest'],
                original=row['original']['digest'], version=version))
        except (KeyError, TypeError, ValueError):
            omitted += 1
    return retained, omitted


def typescript_buffer_materials(receipt: bytes, recipe: bytes, source_inputs: bytes):
    """Identify a selected owned module, never its execution or authority.

    Read only already-bound inventories. No package lookup, current SDK search,
    initializer or compiler is needed by either the build or outcome reader.
    """
    from tools.typescript_guest import buffer_profile
    require(buffer_profile.PROFILE == context.BUFFER_PROFILE, 'compatibility-context-buffer-owner-profile')
    recipe_inputs = decode(recipe, 8 * 1024 * 1024)
    captured = decode(source_inputs, 8 * 1024 * 1024)

    def entry(document, name):
        require(isinstance(document, dict) and name in document, 'compatibility-context-buffer-input-missing')
        row = document[name]
        members(row, {'digest', 'size'})
        sha(row['digest']); integer(row['size'], 1, 4 * 1024 * 1024)
        return row

    backend = entry(recipe_inputs, buffer_profile.BACKEND)
    declaration = entry(recipe_inputs, buffer_profile.DECLARATION)
    require(declaration == entry(captured, 'vendor/lsf/' + buffer_profile.DECLARATION),
            'compatibility-context-buffer-declaration-drift')
    value = decode(receipt, 65536)
    globals_selected = isinstance(value, dict) and value.get('schemaVersion') == 'latent.typescript.standard-buffer-selection.v2'
    global_entries = {part: entry(recipe_inputs, name) for part, name in buffer_profile.GLOBAL_RECIPE.items()} if globals_selected else {}
    if globals_selected:
        name = buffer_profile.GLOBAL_RECIPE['declaration']
        require(global_entries['declaration'] == entry(captured, 'vendor/lsf/' + name),
                'compatibility-context-buffer-global-declaration-drift')
    buffer_profile.validate_selection(value, backend['digest'],
        {part: row['digest'] for part, row in global_entries.items()} if globals_selected else None)
    identities = (digest(receipt), backend['digest'], declaration['digest'])
    rows = [context.material('runtime', name, identity, profile=context.BUFFER_PROFILE)
            for name, identity in zip(context.BUFFER_MATERIALS, identities)]
    if globals_selected:
        rows.extend(context.material('runtime', name, global_entries[part]['digest'], profile=context.BUFFER_GLOBAL_PROFILE)
                    for part, name in zip(buffer_profile.GLOBAL_RECIPE, context.BUFFER_GLOBAL_MATERIALS))
    return rows


def typescript_buffer_owner(owner, receipt_digest, recipe_digest):
    """Rebind module/recipe to the validated original owner's input list."""
    require(isinstance(owner, dict) and owner.get('schemaVersion') == guest_runtime_receipts.SCHEMA
            and owner.get('language') == 'typescript', 'compatibility-context-buffer-owner-required')
    inputs = {row['name']: row['digest'] for row in owner['toolAndCompilerInputs']}
    require(inputs.get(context.BUFFER_MATERIALS[0]) == receipt_digest
            and inputs.get('build-recipe') == recipe_digest, 'compatibility-context-buffer-owner-input-drift')


def typescript_net_materials(receipt, recipe, source_inputs):
    """Bind each Socket implementation input to the original captured recipe."""
    from tools.typescript_guest import net_profile
    require(net_profile.PROFILE == context.NET_PROFILE, 'compatibility-context-net-owner-profile')
    recipe_inputs = decode(recipe, 8 * 1024 * 1024)
    captured = decode(source_inputs, 8 * 1024 * 1024)

    def entry(document, name):
        require(isinstance(document, dict) and name in document, 'compatibility-context-net-input-missing')
        row = document[name]
        members(row, {'digest', 'size'})
        sha(row['digest']); integer(row['size'], 1, 4 * 1024 * 1024)
        return row

    paths = (net_profile.BACKEND, net_profile.TRANSPORT, net_profile.BINDINGS,
             net_profile.RESOLVER, net_profile.DECLARATION, net_profile.WIT)
    identities = {}
    for part, path in zip(context.NET_PARTS, paths):
        row = entry(recipe_inputs, path)
        if part in {'declaration', 'interface'}:
            require(row == entry(captured, 'vendor/lsf/' + path),
                    'compatibility-context-net-captured-input-drift')
        identities[part] = row['digest']
    # The selector itself must be part of the same immutable recipe.
    entry(recipe_inputs, 'tools/typescript_guest/net_profile.py')
    selected = net_profile.selected({'standardNetModules': ['node:net'],
        'standardNetProfile': context.NET_PROFILE, 'standardNetIdentities': identities}, identities)
    require(encode(decode(receipt, 65536)) == encode(selected),
            'compatibility-context-net-selection-drift')
    return [context.material('runtime', name, identity, profile=context.NET_PROFILE)
            for name, identity in zip(context.NET_MATERIALS, (digest(receipt), *identities.values()))]


def typescript_net_owner(owner, receipt_digest, recipe_digest):
    require(isinstance(owner, dict) and owner.get('schemaVersion') == guest_runtime_receipts.SCHEMA
            and owner.get('language') == 'typescript' and owner.get('ownerIssue') == 745,
            'compatibility-context-net-owner-required')
    inputs = {row['name']: row['digest'] for row in owner['toolAndCompilerInputs']}
    require(inputs.get(context.NET_MATERIALS[0]) == receipt_digest
            and inputs.get('build-recipe') == recipe_digest, 'compatibility-context-net-owner-input-drift')


def finish(output: Path, files: dict[str, bytes], source_inputs: bytes,
           component: bytes, materials: list[dict]) -> dict:
    report_raw = read_file(output / 'compatibility-report.json', compatibility.MAX_BYTES)
    report = compatibility.read(report_raw)
    require(report['sourceDigest'] == digest(source_inputs) and report['componentDigest'] == digest(component),
            'compatibility-context-stale-build')
    sdk = decode(files['sdk-lock.json'], 8 * 1024 * 1024)
    selected = {'state': 'absent'}
    retained = [context.material('sdk', 'sdk-lock', digest(encode(sdk)))]
    captured = {}
    require(isinstance(materials, list) and len(materials) <= 64, 'compatibility-context-build-material-limit')
    for row in materials:
        require(isinstance(row, dict) and isinstance(row.get('name'), str) and row['name'] not in captured,
                'compatibility-context-duplicate-build-material')
        captured[row['name']] = row
        if report['language'] == 'typescript' and row['name'] in {context.BUFFER_MATERIALS[0], context.NET_MATERIALS[0]}:
            continue  # Project its bound module/source identities below.
        if row['name'] not in {'source-snapshot', 'package-inputs'}:
            kind = 'generated' if row['name'] in {'c-generator-inputs', 'go-generator-inputs',
                'java-generator-inputs', 'typescript-generator-inputs', 'executable-input-outputs'} else 'compiler'
            retained.append(context.material(kind, row['name'], row['digest']))

    def bound_receipt(filename, name, maximum):
        raw = read_file(output / filename, maximum)
        row = captured.get(name)
        require(row is not None and row['digest'] == digest(raw) and row['size'] == len(raw),
                'compatibility-context-stale-or-unbound-receipt')
        return raw, decode(raw, maximum)

    buffer_selected = report['language'] == 'typescript' and (context.BUFFER_MATERIALS[0] in captured
            or (output / 'typescript-buffer-selection.json').exists())
    if buffer_selected:
        buffer_raw, _ = bound_receipt('typescript-buffer-selection.json', context.BUFFER_MATERIALS[0], 65536)
        recipe_raw, _ = bound_receipt('recipe-inputs.json', 'build-recipe', 8 * 1024 * 1024)
        retained.extend(typescript_buffer_materials(buffer_raw, recipe_raw, source_inputs))
    net_selected = report['language'] == 'typescript' and (context.NET_MATERIALS[0] in captured
            or (output / 'typescript-net-selection.json').exists())
    if net_selected:
        net_raw, _ = bound_receipt('typescript-net-selection.json', context.NET_MATERIALS[0], 65536)
        net_recipe_raw, _ = bound_receipt('recipe-inputs.json', 'build-recipe', 8 * 1024 * 1024)
        retained.extend(typescript_net_materials(net_raw, net_recipe_raw, source_inputs))

    runtime_path = output / 'runtime-profile.json'
    owner_runtime = output / 'standard-runtime-selection.json'
    validated_owner = None
    if runtime_path.exists() or owner_runtime.exists():
        filename = 'standard-runtime-selection.json' if owner_runtime.exists() else 'runtime-profile.json'
        name = 'standard-runtime-selection' if owner_runtime.exists() else 'runtime-profile'
        if not owner_runtime.exists() and report['language'] == 'java' and 'java-runtime-profile' in captured:
            require('runtime-profile' not in captured, 'compatibility-context-ambiguous-runtime-material')
            name = 'java-runtime-profile'
        raw, runtime = bound_receipt(filename, name, 65536 if owner_runtime.exists() else 4 * 1024 * 1024)
        if owner_runtime.exists():
            guest_runtime_receipts.verify_build(runtime, report['language'], files, source_inputs, component,
                [row for row in materials if row['name'] != 'standard-runtime-selection'])
            validated_owner = runtime
        require(isinstance(runtime, dict) and isinstance(runtime.get('profile'), str),
                'compatibility-context-runtime-receipt')
        profile = compatibility.token(runtime['profile'])
        retained.append(context.material('runtime', 'selected-standard-runtime', digest(raw), profile=profile))
        selected = {'state': 'selected-unqualified', 'profile': profile, 'receiptDigest': digest(raw)}
        if owner_runtime.exists():
            selected['receiptName'] = filename
            selected['ownerIssue'] = runtime['ownerIssue']
            retained.append(context.material('runtime', 'selected-runtime-original',
                runtime['originalRuntimeInputsDigest'], profile=profile))
            for transform in runtime['transformations']:
                retained.append(context.material('generated', transform['name'], transform['resultDigest'],
                    original=transform['originalDigest'], transformation=digest(encode(transform))))
        # A compiler receipt identifies selection. Even a "qualified" string
        # cannot establish this component's reachability or runtime behavior.
    if buffer_selected:
        typescript_buffer_owner(validated_owner, digest(buffer_raw), digest(recipe_raw))
    if net_selected:
        typescript_net_owner(validated_owner, digest(net_raw), digest(net_recipe_raw))
    if report['language'] == 'java' and 'generated-bindings' in captured:
        _, bindings = bound_receipt('bindings.json', 'generated-bindings', 4 * 1024 * 1024)
        require(isinstance(bindings, dict), 'compatibility-context-java-bindings')
        if 'coroutineCompiler' in bindings:
            recipe = captured.get('build-recipe')
            require(recipe is not None and selected['state'] == 'selected-unqualified',
                    'compatibility-context-java-compiler-runtime-required')
            retained.extend(java_compiler_materials(bindings, selected['profile'], recipe['digest']))
    patches_path = output / 'compiler-patches.json'
    if patches_path.exists():
        raw, patches = bound_receipt('compiler-patches.json', 'automatic-compiler-patches', 4 * 1024 * 1024)
        require(isinstance(patches, dict) and patches.get('formatVersion') == 1
                and isinstance(patches.get('patches'), list) and len(patches['patches']) <= 64,
                'compatibility-context-patch-receipt')
        recipe = captured.get('build-recipe')
        require(recipe is not None, 'compatibility-context-patch-recipe-required')
        for patch in patches['patches']:
            require(isinstance(patch, dict) and {'name', 'profile', 'original', 'selected', 'selection'} <= patch.keys(),
                    'compatibility-context-patch-identity-required')
            require(isinstance(patch['original'], dict) and isinstance(patch['selected'], dict),
                    'compatibility-context-patch-preimage-required')
            transformation = digest(encode({'recipeDigest': recipe['digest'], 'name': patch['name'],
                                           'profile': patch['profile'], 'selection': patch['selection']}))
            retained.append(context.material('patch', patch['name'], patch['selected']['digest'],
                profile=patch['profile'], original=patch['original']['digest'], transformation=transformation))
    # Prefer all identified runtime/patch entries if a compiler observation
    # already fills the finite material count. Omission never becomes support.
    dependencies, omitted = dependency_materials(files, source_inputs, report['language'])
    retained.extend(dependencies)
    retained.sort(key=lambda row: (row['kind'] == 'dependency',
                                   row['kind'] not in {'runtime', 'patch'} and not (
                                       (buffer_selected or net_selected) and row['kind'] == 'compiler' and row['name'] == 'build-recipe'),
                                   row['kind'], row['name']))
    omitted += max(0, len(retained) - context.MAX_MATERIALS)
    value = context.create(report, retained[:context.MAX_MATERIALS], selected, omitted=omitted)
    write_json(output / 'compatibility-context.json', value)
    captured_graph = guest_runtime_receipts.captured_graph(files)
    graph = digest(encode(captured_graph)) if captured_graph is not None else None
    guest_emitted_code.emit(output, component, digest(source_inputs), selected.get('profile', 'not-observed'),
        report['runtimeProfile'], graph=graph, recipe=captured.get('build-recipe', {}).get('digest'))
    from tools import guest_api_analysis
    guest_api_analysis.emit(output, report, value)
    require(read_file(output / 'compatibility-report.json', compatibility.MAX_BYTES) == report_raw,
            'compatibility-context-report-was-mutated')
    return value
