"""Exercise installed source validation before any guest compiler can start."""
import os

if __package__:
    from .dev_packaged_process import read_json, require, write_json
else:
    from dev_packaged_process import read_json, require, write_json


def descriptors(api, workspace, project):
    path = project / 'latent.project.json'
    original = path.read_bytes()
    descriptor = read_json(path)
    observed = {}
    try:
        for name, fields, rejection in (
            ('unknown-field', {'implicitCredential': 'must-not-be-selected'}, 'unknown-or-missing-field'),
            ('abi', {'hostAbi': 'unsupported-qualification-abi'}, 'incompatible-host-abi'),
            ('traversal', {'inputRoots': ['../outside-project']}, 'source-path-traversal')):
            write_json(path, {**descriptor, **fields})
            observed[name] = api.call('build', '--workspace', workspace, '--project', project, rejection={rejection})
    finally:
        path.write_bytes(original)
    return observed


def source_paths(api, workspace, project):
    observed = {}
    app = project / 'app'
    first, second = app / 'qualification-caf\u00e9.txt', app / 'qualification-cafe\u0301.txt'
    require(not first.exists() and not second.exists(), 'new-source-alias-fixtures-required')
    try:
        first.write_bytes(b'first distinct source file')
        with second.open('xb') as stream:
            stream.write(b'second distinct source file')
        require(not os.path.samefile(first, second), 'actual-distinct-alias-files-required')
        observed['unicodeAlias'] = api.call('build', '--workspace', workspace, '--project', project,
            rejection={'source-case-or-unicode-collision'})
    finally:
        # Only the two newly created author files are removed, never a tree.
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)
    alias = app / 'qualification-hardlink.rs'
    require(not alias.exists(), 'new-source-hardlink-fixture-required')
    try:
        os.link(app / 'src/lib.rs', alias)
        observed['hardlink'] = api.call('build', '--workspace', workspace, '--project', project,
            rejection={'single-link-regular-file-required'})
    finally:
        alias.unlink(missing_ok=True)
    if os.name == 'posix':
        link = app / 'qualification-symbolic-link.rs'
        require(not link.exists() and not link.is_symlink(), 'new-source-symlink-fixture-required')
        try:
            link.symlink_to('src/lib.rs')
            observed['symbolicLink'] = api.call('build', '--workspace', workspace, '--project', project,
                rejection={'source-link-rejected'})
        finally:
            link.unlink(missing_ok=True)
    return observed
