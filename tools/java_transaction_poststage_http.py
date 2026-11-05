"""A separate Java guest attempts immediate HTTP after staging bounded work."""
import json
from pathlib import Path

from tools.java_transaction_schema import SOURCE, create as schema_project
from tools.rust_capsule_project import digest, read_file, read_json
from tools.transaction_guest_variants import HTTP, forbidden_http, replace_once

VARIANT = 'put-once-poststage-http-denial'


def create(directory: Path, profile: str) -> Path:
    project = schema_project(directory, 'legacy-v1', effect='current-http', http_profile=profile)
    source_path = project / SOURCE
    source = forbidden_http(read_file(source_path).decode(), 'java').encode()
    world_path = project / 'wit/world.wit'
    world = replace_once(read_file(world_path).decode(), 'world service {',
                         'world service {\n    import ' + HTTP + ';').encode()
    dependency = read_file(project / 'vendor/lsf/wit/platform/http-v2/package.wit')
    target = project / 'wit/deps/http-v2/package.wit'
    target.parent.mkdir(parents=True, exist_ok=False)
    target.write_bytes(dependency)
    source_path.write_bytes(source)
    world_path.write_bytes(world)
    lock = read_json(project / 'sdk-lock.json')
    lock['template']['sourceDigest'] = digest(source)
    lock['template']['witDigest'] = digest(world)
    (project / 'sdk-lock.json').write_bytes(json.dumps(lock, indent=2).encode() + b'\n')
    schema = read_json(project / 'application-schema-inputs.json')
    schema['sourceDigest'] = digest(source)
    (project / 'application-schema-inputs.json').write_bytes(json.dumps(schema, indent=2).encode() + b'\n')
    declaration = {'schemaVersion': 'latent.java.poststage-http-denial-input.v1', 'variant': VARIANT,
        'sourceDigest': digest(source), 'worldDigest': digest(world),
        'companionDigest': digest(read_file(project / 'transaction-binding.json')),
        'callAfter': ['state-put', 'intent-stage'], 'expectedTypedError': 'permission-denied',
        'expectedBusinessResult': 'rejected', 'componentCompiled': False,
        'signedExecutionQualified': False, 'postStageRollbackQualified': False}
    (project / 'java-poststage-http-denial-input.json').write_bytes(json.dumps(declaration, indent=2).encode() + b'\n')
    return project
