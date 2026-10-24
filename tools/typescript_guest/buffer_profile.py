"""Pure compiler-owned Buffer profile; module availability grants no authority."""
PROFILE = 'lsf-node-buffer-v1'
DECLARATION = 'sdk/typescript-guest/runtime/buffer.d.ts'
BACKEND = 'tools/typescript_guest/node_buffer.mjs'
RESOLVER = 'tools/typescript_guest/buffer_builtin.mjs'


def verify_captured_declaration(selection: dict | None, expected: bytes, read_captured) -> None:
    """Legacy unselected captures need no new file; selected inputs stay exact."""
    if selection is not None and read_captured() != expected:
        raise ValueError('captured TypeScript buffer declarations differ from the selected backend')


def check_selection(observation: dict, backend_digest: str) -> dict | None:
    selected = observation.get('standardBufferModules', [])
    if selected not in ([], ['node:buffer']):
        raise ValueError('typescript-standard-buffer-module-set')
    if not selected:
        if any(key in observation for key in ('standardBufferProfile', 'standardBufferBackendDigest')):
            raise ValueError('typescript-unused-buffer-profile')
        return None
    if (selected != ['node:buffer'] or observation.get('standardBufferProfile') != PROFILE
            or observation.get('standardBufferBackendDigest') != backend_digest):
        raise ValueError('typescript-standard-buffer-selection-drift')
    return {'schemaVersion': 'latent.typescript.standard-buffer-selection.v1',
            'profile': PROFILE, 'modules': selected, 'backendDigest': backend_digest,
            'maximumBufferBytes': 1024 * 1024, 'maximumInputStringCodeUnits': 4 * 1024 * 1024,
            'unsafeAllocation': 'zero-filled', 'globalBufferInstalled': False,
            'nativeStorage': False, 'authority': 'none', 'qualification': 'unknown',
            'apiSupport': 'finite-source-subset; signed qualification not run'}


def validate_selection(selected, backend_digest: str):
    """Compare parsed JSON values with exact JSON types, independent of layout."""
    import json
    expected = check_selection({'standardBufferModules': ['node:buffer'],
        'standardBufferProfile': PROFILE, 'standardBufferBackendDigest': backend_digest}, backend_digest)
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if canonical(selected) != canonical(expected):
        raise ValueError('typescript-standard-buffer-retained-selection-drift')
    return selected


def retain_selection(compiled, output, backend_digest: str):
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
    validate_selection(json.loads(raw), backend_digest)
    (output / name).write_bytes(raw)
    return ((name, 'asset', 'application/vnd.latent.typescript.buffer-selection.v1+json'),), [
        {'name': 'typescript-standard-buffer', 'digest': digest(raw), 'size': len(raw)}]
