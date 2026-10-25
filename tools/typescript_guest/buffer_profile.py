"""Pure compiler-owned Buffer profile; module availability grants no authority."""
PROFILE = 'lsf-node-buffer-v1'
DECLARATION = 'sdk/typescript-guest/runtime/buffer.d.ts'
BACKEND = 'tools/typescript_guest/node_buffer.mjs'
RESOLVER = 'tools/typescript_guest/buffer_builtin.mjs'
GLOBAL_PROFILE = 'lsf-node-buffer-global-v1'
GLOBAL_RECIPE = {
    'selector': 'tools/typescript_guest/buffer_globals.mjs',
    'initializer': 'tools/typescript_guest/buffer_global_initializer.mjs',
    'declaration': 'sdk/typescript-guest/runtime/buffer-globals.d.ts',
}


def global_identities(root):
    from tools.rust_capsule_project import digest, read_file
    return {key: digest(read_file(root / name)) for key, name in GLOBAL_RECIPE.items()}


def verify_captured_declaration(selection: dict | None, expected: bytes, read_captured) -> None:
    """Legacy unselected captures need no new file; selected inputs stay exact."""
    if selection is not None and read_captured() != expected:
        raise ValueError('captured TypeScript buffer declarations differ from the selected backend')


def prepare_global_declarations(selection, expected: bytes, read_captured, directories, *, provided_node=False):
    """Selected-only finite declarations; captured Node supplies its own globals."""
    if selection is None or not selection['globalBufferInstalled']:
        return
    if read_captured() != expected:
        raise ValueError('captured TypeScript global Buffer declaration differs from the selected backend')
    if not provided_node:
        for directory in directories:
            (directory/'buffer-runtime-globals.d.ts').write_bytes(expected)


def check_selection(observation: dict, backend_digest: str, globals_expected=None) -> dict | None:
    selected = observation.get('standardBufferModules', [])
    if selected not in ([], ['node:buffer']):
        raise ValueError('typescript-standard-buffer-module-set')
    if not selected:
        if any(key in observation for key in ('standardBufferProfile', 'standardBufferBackendDigest',
                'standardBufferGlobalProfile', 'standardBufferGlobalReferences', 'standardBufferGlobalIdentities')):
            raise ValueError('typescript-unused-buffer-profile')
        return None
    if (selected != ['node:buffer'] or observation.get('standardBufferProfile') != PROFILE
            or observation.get('standardBufferBackendDigest') != backend_digest):
        raise ValueError('typescript-standard-buffer-selection-drift')
    value = {'schemaVersion': 'latent.typescript.standard-buffer-selection.v1',
            'profile': PROFILE, 'modules': selected, 'backendDigest': backend_digest,
            'maximumBufferBytes': 1024 * 1024, 'maximumInputStringCodeUnits': 4 * 1024 * 1024,
            'unsafeAllocation': 'zero-filled', 'globalBufferInstalled': False,
            'nativeStorage': False, 'authority': 'none', 'qualification': 'unknown',
            'apiSupport': 'finite-source-subset; signed qualification not run'}
    global_keys = {'standardBufferGlobalProfile', 'standardBufferGlobalReferences', 'standardBufferGlobalIdentities'}
    if global_keys & observation.keys():
        forms = observation.get('standardBufferGlobalReferences')
        if (not global_keys <= observation.keys() or observation['standardBufferGlobalProfile'] != GLOBAL_PROFILE
                or forms not in (['Buffer'], ['globalThis.Buffer'], ['Buffer', 'globalThis.Buffer'])
                or type(globals_expected) is not dict or set(globals_expected) != set(GLOBAL_RECIPE)
                or observation['standardBufferGlobalIdentities'] != {key: globals_expected[key] for key in ('selector', 'initializer')}):
            raise ValueError('typescript-standard-buffer-global-selection-drift')
        value.update(schemaVersion='latent.typescript.standard-buffer-selection.v2', globalBufferInstalled=True,
            globalProvision={'profile': GLOBAL_PROFILE, 'identities': globals_expected, 'references': forms,
                'initialization': 'compiler-owned-before-application-modules',
                'descriptor': {'writable': True, 'configurable': True, 'enumerable': False}})
    return value


def validate_selection(selected, backend_digest: str, globals_expected=None):
    """Compare parsed JSON values with exact JSON types, independent of layout."""
    import json
    observation = {'standardBufferModules': ['node:buffer'],
        'standardBufferProfile': PROFILE, 'standardBufferBackendDigest': backend_digest}
    if type(selected) is dict and selected.get('schemaVersion') == 'latent.typescript.standard-buffer-selection.v2':
        provision = selected.get('globalProvision', {})
        if type(provision) is not dict:
            raise ValueError('typescript-standard-buffer-global-selection-drift')
        observation.update(standardBufferGlobalProfile=provision.get('profile'),
            standardBufferGlobalReferences=provision.get('references'),
            standardBufferGlobalIdentities={key: globals_expected.get(key) for key in ('selector', 'initializer')}
                if type(globals_expected) is dict else None)
    expected = check_selection(observation, backend_digest, globals_expected)
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if canonical(selected) != canonical(expected):
        raise ValueError('typescript-standard-buffer-retained-selection-drift')
    return selected


def retain_selection(compiled, output, backend_digest: str, globals_expected=None):
    """Promote only an actually selected module into normal package evidence.

    The compiler writes this private result after real bundler selection. An
    unselected old project neither needs a declaration nor acquires this asset.
    The normal build binds the returned material into its signed observation.
    """
    import json
    from tools.rust_capsule_project import digest, read_file

    name = 'typescript-buffer-selection.json'
    path = compiled / name
    if not path.exists():
        return (), []
    raw = read_file(path, 65536)
    selected = validate_selection(json.loads(raw), backend_digest, globals_expected)
    (output / name).write_bytes(raw)
    version = 'v2' if selected['globalBufferInstalled'] else 'v1'
    return ((name, 'asset', 'application/vnd.latent.typescript.buffer-selection.' + version + '+json'),), [
        {'name': 'typescript-standard-buffer', 'digest': digest(raw), 'size': len(raw)}]
