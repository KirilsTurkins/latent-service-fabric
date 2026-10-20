"""Fixed public retained components with original compile records kept verbatim."""
from __future__ import annotations
import json
from pathlib import Path

from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.resource_tenant_inputs import REPOSITORY_ID, original_build
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, write_json

ORIGINALS = {'go': {'artifact': 12250800303, 'name': 'go-embedded-resource-reference-ba710b00000d7ea946f85dcf66148a98de19f800', 'bytes': 1562695, 'digest': 'sha256:e044d506fc8b4444bc665768c1b8b24421dc907c9366700edd3137a0e8de68f5', 'run': 39390308334, 'head': 'ba710b00000d7ea946f85dcf66148a98de19f800', 'buildPrefix': 'go-embedded-resources/build/', 'node': 'go-embedded-resources/node/workflow.json', 'invocations': 35, 'expected': {'component': {'sha256': 'sha256:7dd5a28a600109ee552a5fed7883b652b80fe0acd6a84dd265734d0293368adc', 'bytes': 2683719}, 'buildComplete': {'sha256': 'sha256:1db57098591d23cc02f8d273593bdc5011d3ca996311045883f0d74705f7805b', 'bytes': 2076}, 'buildObservation': {'sha256': 'sha256:cda7dc65bb203b2a857e984820658f6b3b21042b1d8d1056bcd16d4d62f47772', 'bytes': 3338}, 'sourceInputs': {'sha256': 'sha256:1fe4a58ca52c704f6ce045c36e76d3274122cf85f3bce516c6c4461fc1580d18', 'bytes': 14238}, 'node': {'sha256': 'sha256:b36afaf4d46ae77c6450bc073ae35e9ccbbbaafa2df0cd5395687243d20076dc', 'bytes': 355683}}, 'originalOuterJobSucceeded': True}, 'typescript': {'artifact': 12253448936, 'name': 'embedded-resource-typescript-192c7b92faa7c8e0d222c62c1cbcf5d0e25cb0b5', 'bytes': 4784604, 'digest': 'sha256:c50e9349267003f5a41d078bd9dbe579d78c2e14a954bda5accbaffd0513c512', 'run': 39394464486, 'head': '192c7b92faa7c8e0d222c62c1cbcf5d0e25cb0b5', 'buildPrefix': 'embedded-resources/build/', 'node': 'embedded-resources/node/workflow.json', 'invocations': 33, 'expected': {'component': {'sha256': 'sha256:586333831376b61fcbbef856653e32588b9503d193230d6f0ae13f1fabbb3d8d', 'bytes': 12474310}, 'buildComplete': {'sha256': 'sha256:ef09dfceef771dce02c25264969c3035af9531aab1e768aead67a09b81644965', 'bytes': 2337}, 'buildObservation': {'sha256': 'sha256:3495424288727a2ce83fbd3ac39ff04f4da6acc1b62f27f0c7a7e63ca86fb695', 'bytes': 3653}, 'sourceInputs': {'sha256': 'sha256:83b8eb77ffe44444266fc70925e1c20515e555ab7d4e686e9a1bbb1ba834bc07', 'bytes': 8576}, 'node': {'sha256': 'sha256:fb382424f0bc72061961d9fe651330cb6d81c9d508cf5baf6327b57f46c71825', 'bytes': 326138}}, 'originalOuterJobSucceeded': False}, 'java': {'artifact': 12247220241, 'name': 'java-resource-replay-7b5119c5448405b20771e8a020b5e823cc72a0d6', 'bytes': 1130688, 'digest': 'sha256:f24c7a1b03f9578e72d71a9a50f1292fe9b064eb4fe8aa01e051ecfcbcc8f74b', 'run': 39383037165, 'head': '7b5119c5448405b20771e8a020b5e823cc72a0d6', 'buildPrefix': 'java-resource-replay/build/', 'node': 'java-resource-replay/node/workflow.json', 'invocations': 39, 'expected': {'component': {'sha256': 'sha256:5755d74429d5074b8be03570f6218736a74212fcaf63fd468e18448b8486acc0', 'bytes': 619577}, 'buildComplete': {'sha256': 'sha256:1f611b80b33cdd75c5ff289e145ce4862b0404a891c3cbcb3d4b96466fb7674b', 'bytes': 8880}, 'buildObservation': {'sha256': 'sha256:8e616a65298478fba66a9eb6c173c7027c8bdd3ddd56bb7e828efff404e0d7e8', 'bytes': 3468}, 'sourceInputs': {'sha256': 'sha256:2f7bc7710ea5ead5ddb15486d9f4e927454b06e80f75e71383baf293ad3a3f9b', 'bytes': 34393}, 'node': {'sha256': 'sha256:a4e863cbf57307fc2dbc60d62b4386a14ffc52b17bbe7f8ce24bafe5e72af94e', 'bytes': 400512}}, 'originalOuterJobSucceeded': True}, 'rust': {'artifact': 12257859357, 'name': 'embedded-resource-rust-706880aff3e70b46be97bb2119c8c32dda30e74b', 'bytes': 1634454, 'digest': 'sha256:99aea7c8c5be63bc36c39f1c2d919f624a197a43183770a2d87e135560de73c9', 'run': 39407973986, 'head': '706880aff3e70b46be97bb2119c8c32dda30e74b', 'buildPrefix': 'embedded-resources/build/', 'node': 'embedded-resources/node/workflow.json', 'invocations': 33, 'expected': {'component': {'sha256': 'sha256:4af8ffb63f5d5d54c1b22be581f174aa2d54462588d9079c5dcb59075c982472', 'bytes': 26481}, 'buildComplete': {'sha256': 'sha256:ff2a6abff12ec44e64fcb9e4f94ba706b14585402fd711057401acce72a491ed', 'bytes': 1474}, 'buildObservation': {'sha256': 'sha256:8f75b274a57e75ca2559582ddcade0c5ac2e491898de54e871bd8b00a30ecb56', 'bytes': 3332}, 'sourceInputs': {'sha256': 'sha256:0e12fc74f201bd7744b694431731170d9e52a0689edfd1cf83013572b23f2eba', 'bytes': 8500}, 'node': {'sha256': 'sha256:e7cc8ab8f4d15d36a8a2ffb6d2470f2c8e152a32b12df16262185c5636b1c40d', 'bytes': 325645}}, 'originalOuterJobSucceeded': True}}
RECORDS = ('BUILD-COMPLETE.json','build-observation.json','source-inputs.json',
           'package-inputs.json','deployment.json')


def validate_producer(language, metadata):
    require(language in ORIGINALS, 'resource-tenant-original-language-not-prepared')
    selected = ORIGINALS[language]
    workflow = metadata.get('workflow_run', {})
    require(metadata.get('id') == selected['artifact'] and metadata.get('name') == selected['name']
        and metadata.get('size_in_bytes') == selected['bytes'] and metadata.get('digest') == selected['digest']
        and metadata.get('expired') is False and workflow.get('id') == selected['run']
        and workflow.get('head_sha') == selected['head']
        and workflow.get('repository_id') == workflow.get('head_repository_id') == REPOSITORY_ID,
        'resource-tenant-original-exact-producer')
    return selected


def public_wit(language):
    base = read_file(ROOT/'tools/toolchain-smoke/examples/tutorial_greeting/world.wit')
    result = {'wit/world.wit':base}
    if language == 'go':
        contracts = ('latent:clock/monotonic@0.1.0','latent:clock/wall@0.1.0','latent:random/random@0.1.0')
        require(base.count(b'world service {') == 1, 'resource-tenant-public-Go-world')
        result['wit/world.wit'] = base.replace(b'world service {', b'world service {\n'+
            b'\n'.join(b'    import '+name.encode()+b';' for name in contracts),1)
        result.update({f'wit/deps/{name}/package.wit':read_file(ROOT/f'wit/platform/{name}/package.wit')
            for name in ('clock','random')})
    elif language == 'java':
        from tools.java_capsule_project import runtime_wit
        result['wit/world.wit'] = runtime_wit(base,'service')
        result['wit/deps/clock/package.wit'] = read_file(ROOT/'wit/platform/clock/package.wit')
    return result


def restored_public_bytes(language, name, selected, source, index):
    candidates = public_wit(language)
    if name in candidates:
        raw = candidates[name]
        require(source.get(name) == {'digest':digest(raw),'size':len(raw)},
            'resource-tenant-restored-WIT-original-source-mismatch')
    else:
        require(language == 'java' and name.startswith('resources/objects/'),
            'resource-tenant-unretained-public-file-not-authorized')
        # These are the published finite fixture bytes, never private package payloads.
        candidates = {digest(raw)[7:]:raw for raw in (
            'Gr\u00fc\u00dfe\0\u96ea\n'.encode(),bytes((0,255,128,65,13,10)),b'', '\u96ea'.encode())}
        key = name.removeprefix('resources/objects/')
        require(key in candidates, 'resource-tenant-unretained-resource-not-known')
        raw = candidates[key]
        require(any(row.get('object') == name and row.get('digest') == digest(raw)
            and row.get('size') == len(raw) for row in index.get('resources',[])),
            'resource-tenant-restored-object-not-original-index')
    require(selected == {'digest':digest(raw),'size':len(raw)},
        'resource-tenant-restored-public-package-input-mismatch')
    return raw


def prepare(language, directory: Path, metadata, output: Path):
    selected = validate_producer(language,metadata)
    prefix = directory/selected['buildPrefix']
    node_path = directory/selected['node']
    expected = selected['expected']
    require(file_identity(node_path) == expected['node'], 'resource-tenant-original-node-digest')
    node = read_json(node_path,4*1024**2)
    require(node.get('status') == 'passed' and node.get('language') == language
        and len(node['invocations']) == selected['invocations']
        and len({row['activation'] for row in node['invocations']}) == selected['invocations']
        and all(row['processReaped'] and row['response']['outcomeKnown'] is True for row in node['invocations'])
        and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
        'resource-tenant-original-node-not-passed')
    for name,field in (('component.wasm','component'),('BUILD-COMPLETE.json','buildComplete'),
                       ('build-observation.json','buildObservation'),('source-inputs.json','sourceInputs')):
        require(file_identity(prefix/name,64*1024**2) == expected[field],
            'resource-tenant-original-compiled-input-identity')
    inventory = read_json(prefix/'package-inputs.json',65536)
    require(type(inventory) is dict and 1 <= len(inventory) <= 128
        and all(type(name) is str and not name.startswith('/') and '..' not in name.split('/')
            and '\\' not in name and ':' not in name and type(row) is dict and set(row)=={'digest','size'}
            for name,row in inventory.items()), 'resource-tenant-original-inventory-shape')
    source = read_json(prefix/'source-inputs.json',16*1024**2)
    index = read_json(prefix/'resource-index.json') if 'resource-index.json' in inventory else {}
    output = fresh(output)
    restored = []
    for name in sorted(set(inventory)|set(RECORDS)):
        target = output/name; target.parent.mkdir(parents=True,exist_ok=True)
        if (prefix/name).exists():
            raw = read_file(prefix/name,64*1024**2)
        else:
            require(name in inventory, 'resource-tenant-original-record-missing')
            raw = restored_public_bytes(language,name,inventory[name],source,index)
            restored.append(name)
        if name in inventory:
            require(inventory[name] == {'digest':digest(raw),'size':len(raw)},
                'resource-tenant-original-package-file-drift')
        target.write_bytes(raw)
    original = original_build(output,language,expected)
    proof = {'producer':{key:selected[key] for key in ('artifact','name','bytes','digest','run','head')},
        'original':original,'originalNode':expected['node'],'restoredKnownPublicFiles':restored,
        'recordsRewritten':False,'componentCompiled':False,
        'originalOuterJobSucceeded':selected['originalOuterJobSucceeded'],
        'originalNodeProgrammeSucceeded':True}
    write_json(output/'resource-original-acquisition.json',proof)
    return output,expected,proof
