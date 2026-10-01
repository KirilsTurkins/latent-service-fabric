"""Signed-node qualification inputs; never used by application/runtime dispatch."""
from pathlib import Path

from tools.application_dependencies import LOCK, MANIFEST, capture, document
from tools.application_dependency_store import Store, materialize
from tools.build_snapshot import canonical, digest

JSMN = 'sha256:1ed6154dedf009212a08a397e9c4ed50a0ce31d5a8301bb294e137ae3188c13b'


def install(project: Path, outside: Path) -> dict:
    """Capture a real third-party parser and outside-project transitive library."""
    outside.mkdir(mode=0o700)
    resources = outside / 'resources'
    library = outside / 'developer-owned-library'
    resources.mkdir()
    library.mkdir()
    # A captured immutable byte resource, consumed through ordinary C includes.
    resource = b'{"prefix":"Hello, "}'
    (resources / 'greeting.inc').write_text(','.join(str(byte) for byte in resource) + ',0\n', encoding='ascii')
    (library / 'qualified.h').write_text('const unsigned char *qualified_prefix(void);\n', encoding='ascii')
    (library / 'qualified.c').write_text('''#include "qualified.h"
#include "jsmn.h"
#include <stddef.h>
static const unsigned char data[] = {
#include "greeting.inc"
};
const unsigned char *qualified_prefix(void) {
    jsmn_parser parser;
    jsmntok_t tokens[3];
    jsmn_init(&parser);
    int count = jsmn_parse(&parser, (const char *)data, sizeof(data) - 1, tokens, 3);
    if (count != 3 || tokens[2].type != JSMN_STRING || tokens[2].end - tokens[2].start != 7) return NULL;
    return data + tokens[2].start;
}
''', encoding='ascii')
    artifacts = [
        {'id': 'developer-owned/qualification/1', 'role': 'application', 'format': 'directory',
         'mount': 'dependencies/developer-library', 'source': {'path': str(library)},
         'dependencies': ['zserge/jsmn/1.1.0', 'developer-owned/resource/1'],
         'metadata': {'cSources': ['qualified.c'], 'includeDirectories': ['.'], 'license': 'Apache-2.0'}},
        {'id': 'zserge/jsmn/1.1.0', 'role': 'application', 'format': 'file',
         'mount': 'dependencies/parser/jsmn.h',
         'source': {'repository': 'upstream', 'path': 'zserge/jsmn/v1.1.0/jsmn.h', 'digest': JSMN},
         'dependencies': [], 'metadata': {'includeDirectories': ['.'], 'license': 'MIT', 'headerOnly': True}},
        {'id': 'developer-owned/resource/1', 'role': 'resource', 'format': 'directory',
         'mount': 'dependencies/immutable-data', 'source': {'path': str(resources)},
         'dependencies': [], 'metadata': {'includeDirectories': ['.'], 'logicalPath': 'greeting.inc',
                                          'mediaType': 'text/plain', 'license': 'Apache-2.0'}}]
    manifest = {'formatVersion': 1, 'language': 'c', 'selection': {'target': 'wasm32-wasi'},
                'nativeLocks': [], 'artifacts': artifacts, 'transformations': []}
    (project / MANIFEST).write_bytes(canonical(manifest) + b'\n')
    lock = capture(project, repositories={'upstream': {'url': 'https://raw.githubusercontent.com'}})
    # Turn all resolved originals into stable CAS references; later compilation
    # must not rely on either the original local library or a remote fetch.
    store = Store(project / 'dependency-inputs/objects')
    for declaration, resolved in zip(artifacts, lock['artifacts']):
        if declaration['format'] == 'file':
            original = resolved['original']
            declaration['source'] = {'path': str(store.path(original['digest']))}
    (project / MANIFEST).write_bytes(canonical(manifest) + b'\n')
    lock = capture(project)
    (project / LOCK).write_bytes(canonical(lock) + b'\n')
    source = project / 'src/main.c'
    before = source.read_bytes()
    if before.count(b'#include "lsf/text.h"') != 1 or before.count(b'memcpy(bytes, "Hello, ", 7);') != 1:
        raise ValueError('C dependency qualification source hook changed')
    after = before.replace(b'#include "lsf/text.h"', b'#include "lsf/text.h"\n#include "qualified.h"\n#define JSMN_HEADER\n#include "jsmn.h"')
    after = after.replace(b'memcpy(bytes, "Hello, ", 7);',
                          b'const char direct_json[] = "{\\\"answer\\\":42}";\n'
                          b'    jsmn_parser direct_parser;\n    jsmntok_t direct_tokens[3];\n'
                          b'    jsmn_init(&direct_parser);\n'
                          b'    lsf_require(jsmn_parse(&direct_parser, direct_json, sizeof(direct_json) - 1, direct_tokens, 3) == 3);\n'
                          b'    lsf_require(direct_tokens[2].type == JSMN_PRIMITIVE);\n'
                          b'    lsf_require(direct_tokens[2].end - direct_tokens[2].start == 2);\n'
                          b'    const unsigned char *prefix = qualified_prefix();\n    lsf_require(prefix != NULL);\n    memcpy(bytes, prefix, 7);')
    if after == before or b'memcpy(bytes, "Hello, ", 7);' in after:
        raise ValueError('C dependency qualification source hook changed')
    source.write_bytes(after)
    # Native sources are only needed at capture time; delete their content to
    # ensure the ordinary builder actually consumes the closed store.
    for selected in (library / 'qualified.c', library / 'qualified.h', resources / 'greeting.inc'):
        selected.unlink()
    return {'formatVersion': 1, 'thirdParty': 'zserge/jsmn/1.1.0', 'thirdPartyDigest': JSMN,
            'developerOwned': 'developer-owned/qualification/1',
            'directApplicationCalls': ['zserge/jsmn/1.1.0', 'developer-owned/qualification/1'],
            'transitiveCalls': ['developer-owned/qualification/1 -> zserge/jsmn/1.1.0'],
            'resourceDigest': digest(resource),
            'offlineOriginals': 'unavailable-after-capture', 'sourceDigest': digest(after)}


def use_static_archive(project: Path, archive: Path, profile: dict, outside: Path, *,
                       library_identity: str = 'developer-owned/qualification/1') -> dict:
    """Explicitly resolve a source-built archive with its captured public header/data."""
    import tempfile
    manifest, lock = document(project / MANIFEST), document(project / LOCK)
    resolved = {item['id']: item for item in lock['artifacts']}
    declarations = {item['id']: item for item in manifest['artifacts']}
    library_id = 'developer-owned/qualification/1'
    resource_id = 'developer-owned/resource/1'
    parser_id = 'zserge/jsmn/1.1.0'
    store = Store(project / 'dependency-inputs/objects')
    outside.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix='captured-static-', dir=outside) as owned:
        temporary = Path(owned).resolve(strict=True)
        if not temporary.is_relative_to(outside.resolve(strict=True)):
            raise ValueError('C static qualification staging boundary changed')
        header = temporary / 'qualified.h'
        row = next(item for item in resolved[library_id]['files'] if item['path'] == 'qualified.h')
        header.write_bytes(store.get(row['digest'], row['size']))
        resources = temporary / 'immutable-data'
        resources.mkdir(mode=0o700)
        materialize(resolved[resource_id]['files'], resources, store)
        header_id = 'developer-owned/public-header/1'
        library = {'id': library_identity, 'role': 'application', 'format': 'file',
            'mount': 'dependencies/developer-library.a', 'source': {'path': str(archive)},
            'dependencies': [header_id, parser_id, resource_id],
            'metadata': {'archiveProfile': profile, 'license': 'Apache-2.0'}}
        parser = declarations[parser_id]
        parser['source'] = {'path': str(store.path(resolved[parser_id]['files'][0]['digest']))}
        resource = declarations[resource_id]
        resource['source'] = {'path': str(resources)}
        public_header = {'id': header_id, 'role': 'application', 'format': 'file',
            'mount': 'dependencies/developer-header/qualified.h', 'source': {'path': str(header)},
            'dependencies': [], 'metadata': {'includeDirectories': ['.'], 'license': 'Apache-2.0'}}
        manifest['artifacts'] = [library, parser, resource, public_header]
        (project / MANIFEST).write_bytes(canonical(manifest) + b'\n')
        lock = capture(project)
        (project / LOCK).write_bytes(canonical(lock) + b'\n')
    return {'formatVersion': 1, 'archiveProfileDigest': digest(canonical(profile)),
            'sourceLibraryInventoryDigest': digest(canonical(resolved[library_id]['files'])),
            'libraryIdentity': library_identity,
            'archiveDigest': next(item for item in lock['artifacts'] if item['id'] == library_identity)['files'][0]['digest'],
            'lockDigest': digest(canonical(lock)), 'originalHeaderAndResource': 'unavailable-after-capture',
            'directApplicationCalls': ['zserge/jsmn/1.1.0', library_identity]}
