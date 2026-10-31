"""Exact retained root-retirement catalogue candidate; no runtime promotion."""
from pathlib import Path
import copy
import hashlib
import json
import subprocess
import sys
import types
import zipfile

HEAD = '72707ee61ce4784f7c866f2835f474554df8d922'
ZIP_SHA = '1fb393cb5c05aa72852be342449bb0c12cff6923f32f76c79af6ac18f953c5ca'
PREFIX = 'crates/latent-component-threading/src/'
BASE = PREFIX + 'rust_catalogue/'

def sha(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()

def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()

def replace_once(raw, before, after):
    if isinstance(before, str):
        before, after = before.encode(), after.encode()
    assert raw.count(before) == 1, before
    return raw.replace(before, after, 1)

def generate(root, artifact, output, check_git=False):
    root, artifact, output = Path(root), Path(artifact), Path(output)
    sys.path.insert(0, str(root))
    from tools import rust_thread_object_graph as graph
    from tools import rust_thread_host_catalogue as host
    from tools import rust_owned_thread_component as component
    from tools.rust_thread_callback_paths import section
    raw_zip = artifact.read_bytes()
    assert len(raw_zip) == 52711306 and sha(raw_zip) == 'sha256:' + ZIP_SHA
    archive = zipfile.ZipFile(artifact)
    assert len(archive.infolist()) == 116 and archive.testzip() is None
    sources = json.loads(archive.read('source-inputs.json'))
    assert sources['head'] == HEAD and len(sources['files']) == 239
    if check_git:
        queries = ''.join(HEAD + ':' + row['path'] + '\n' for row in sources['files']).encode()
        actual = subprocess.check_output(['git', 'cat-file', '--batch'], input=queries, cwd=root)
        assert len(actual) <= 16 * 1024 * 1024
        offset = 0
        for row in sources['files']:
            end = actual.index(b'\n', offset)
            blob, kind, size = actual[offset:end].decode().split()
            offset = end + 1
            data = actual[offset:offset + int(size)]
            offset += int(size)
            assert actual[offset:offset + 1] == b'\n'
            offset += 1
            assert kind == 'blob' and blob == row['gitBlob']
            assert len(data) == row['size'] and sha(data) == row['digest']
        assert offset == len(actual)
    observation = json.loads(archive.read('application-diagnostic/original-object-graph.json'))
    original = archive.read('application-diagnostic/raw-core.wasm')
    assert sha(original) == 'sha256:8cd26a5f34ec90f23af43dfcb21b0b619b369ed2199a5368a24572bb96cbf177'
    libraries = tuple(graph.Library(row['label'], archive.read(
        'application-diagnostic/captured-futures-executor.rlib' if row['label'] == 'captured-futures-executor.rlib'
        else 'owned-sysroot/sysroot/lib/rustlib/wasm32-unknown-unknown/lib/' + row['label']), row['digest'])
        for row in observation['libraries'])
    _, _, exports = graph.memory_table(original)
    roots = tuple(name for name, (kind, _) in exports.items() if kind == 0 and name.startswith('__lsf_rust_'))
    extras = []
    for label, raw in graph.archive(libraries[-1].content):
        for node in graph.object_nodes(raw, libraries[-1].label + '/' + label)[0]:
            if node['kind'] == 0 and node['name'].endswith(('_10ThreadPool3new', '_10ThreadPool14spawn_admitted', '_4Pool12admit_future')):
                extras.append((libraries[-1].label, node['name']))
    assert len(extras) == 3
    reobserved = graph.observe_objects(original, libraries, roots, tuple(extras))
    assert json.loads(json.dumps(reobserved)) == observation
    previous = json.loads((root / BASE / 'origin.json').read_bytes())
    built = json.loads(archive.read('owned-sysroot/std-sysroot-build.json'))
    origin = {
        'run': 41219448914, 'job': 124590751594, 'head': HEAD, 'event': 'push',
        'artifact': 13049262956, 'artifactZipSha256': ZIP_SHA,
        'compilerDistributionDigest': built['compilerDistributionDigest'],
        'sysrootIdentity': built['identity'],
        'sourceRecipeDigest': sha(archive.read('application-diagnostic/recipe-inputs.json')),
        'originRawCoreDigest': sha(original), 'sourceProfile': built['profile'],
        'compilerRust': built['rust'], 'compilerCommit': built['rustCommit'],
        'threadSourcePathRemap': built['threadSourcePathRemap'],
        'owningStatus': '34-native-controls-passed;repaired-sysroot-and-unchanged-application-built;previous-native-catalogue-refused;76-library-controls-not-reached',
        'actualOriginalLinkerLayout': observation['originalLinkerLayout'],
        'actualGuestExecuted': False, 'normalComponentProduced': False,
    }
    image, manifest = host.catalogue(original, libraries, observation, host.ROOT_EXPORTS,
        tuple(('captured-futures-executor.rlib', name) for name in host.ADDITIONAL_ROOT_SYMBOLS), origin)
    assert len(manifest['nodes']) == 1221
    assert sum(len(row['references']) for row in manifest['nodes']) == 5246
    assert len(image) == 176189 and sha(image) == 'sha256:eca9883441a2e8ef0b4ea721c53932866d117503382c6e8805cb7d7661fd1b8b'
    progress = [row for row in manifest['nodes'] if row['originalSymbol'].endswith('executor_root12progress_all')]
    assert len(progress) == 1
    notification = [ref for ref in progress[0]['references'] if ref['kind'] == 0 and 'node' in ref['referent']
        and manifest['nodes'][ref['referent']['node']]['originalSymbol'].endswith('executor_root7changed')]
    assert len(notification) == 1 and notification[0]['offset'] == 816
    host_source = replace_once((root / 'tools/rust_thread_host_catalogue.py').read_bytes(),
        "for row in manifest['nodes']) == 5245,", "for row in manifest['nodes']) == 5246,")
    emitter = types.ModuleType('reviewed_catalogue_emitter')
    exec(compile(host_source, 'reviewed_catalogue_emitter', 'exec'), emitter.__dict__)
    records = emitter.rust_records(image, manifest)
    sealed = archive.read('application-diagnostic/callback-isolated-core.wasm')
    sync_core = archive.read('application-diagnostic/derived/core.wasm')
    adapted = component.adapt_original_public_wit(sync_core)
    assert sha(adapted) == 'sha256:e976d80b529cdc91e5a6f2255d4aeb8db6412a690b039578c75a7dbd76363c22'
    # Reconstruct only a source candidate. Exact hosted wasm-tools output must
    # subsequently match; this is NOT relabeled as a retained encoder event.
    shell = (root / BASE / 'normal-component-shell.bin').read_bytes()
    encoded_producers = (root / BASE / 'encoded-producers.bin').read_bytes()
    def encode_candidate(core):
        main = bytearray(core[:8]); consumed = merged = 0
        for kind, payload in graph.sections(core):
            name = graph.Reader(payload).name() if kind == 0 else None
            if name and name.startswith('component-type:'):
                consumed += 1
                continue
            if name == 'producers':
                merged += 1
                payload = encoded_producers
            main.extend(section(kind, payload))
        assert consumed == merged == 1
        reader = graph.Reader(shell[8:]); result = bytearray(shell[:8]); replaced = 0
        while reader.p < len(reader.raw):
            kind = reader.byte(); payload = reader.blob(reader.number())
            if kind == 1 and not payload:
                replaced += 1; payload = bytes(main)
            result.extend(section(kind, payload))
        assert replaced == 1
        return bytes(result)
    normal = encode_candidate(adapted)
    projected = host.normal_component_envelope(adapted, normal)
    assert projected['normal-component-shell.bin'] == shell
    assert projected['original-wit-metadata.bin'] == (root / BASE / 'adapted-wit-metadata.bin').read_bytes()
    envelope = copy.deepcopy(previous['normalComponentEnvelope'])
    envelope.update(componentDigest=sha(normal), componentBytes=len(normal),
        derivedCoreDigest=sha(adapted), originalSyncCoreDigest=sha(sync_core),
        nativeVerifierExecuted=False, nativeVerifierPassed=False)
    envelope['candidateSource'] = {
        'compilerRun': 41219448914, 'compilerJob': 124590751594, 'compilerHead': HEAD,
        'compilerArtifact': 13049262956, 'compilerArtifactZipSha256': ZIP_SHA,
        'platform': 'ubuntu-24.04-x86_64', 'toolSha256': envelope['toolSha256'],
        'sourceProjectionOnly': True, 'hostedConfirmation': False,
        'nativeNormalProofPassed': False, 'mandatory76Reached': False,
    }
    current = {key: value for key, value in manifest.items() if key not in ('nodes', 'roots')}
    current.update(nodeCount=1221, referenceCount=5246, rootCount=11,
        normalComponentEnvelope=envelope,
        normalComponentEnvelopeStatus='source-projected candidate; exact hosted encoding and mandatory 76 controls pending',
        beforeRootRetirementRepair=previous,
        currentSourceObservation={
            'head': HEAD, 'rawCore': {'digest': sha(original), 'bytes': len(original)},
            'sealedCoreDigest': sha(sealed), 'syncCoreDigest': sha(sync_core),
            'sourceAdaptedCoreDigest': sha(adapted), 'normalComponentProduced': False,
            'actualGuestExecuted': False, 'nativeControlsPassed': 34,
            'sourceMechanismControlsPassed': 0,
            'originalCatalogueFailure': 'rust-original-full-body-or-signature',
            'retirementNotification': notification[0],
        })
    objects = (root / PREFIX / 'rust_objects.rs').read_bytes()
    objects = replace_once(objects, 'const REFERENCE_COUNT: usize = 5245;', 'const REFERENCE_COUNT: usize = 5246;')
    objects = replace_once(objects, '4b38efc1a41848dee2ec1d8bd1eb4861c5698181bc2ec1daae8058e2fdeb2486', sha(sealed)[7:])
    objects = replace_once(objects, 'deae45d5e79418aaf552948f38afc5d8e98f2ccf494aa8ebe55842a4d3ecc423', sha(adapted)[7:])
    objects = replace_once(objects, '41184446196, artifact 13036816711.', '41219448914, artifact 13049262956.')
    objects = replace_once(objects,
        '//! is the independently verified a9809 compiler observation retained by run\n//! 41109207452.',
        '//! is the independently verified root-retirement observation retained by run\n//! 41219448914.')
    needle = '        let body = module.body(selected).unwrap();\n'
    replacement = '''        // The original retirement path must notify the existing completion
        // queue. This binds the reviewed extra edge without relaxing any
        // full-body, referent, mutation or incoming-dispatch check below.
        let notifications = node
            .references
            .iter()
            .filter(|reference| {
                reference.kind == 0
                    && matches!(&reference.target, Target::Definition(index)
                        if catalogue::NODES[*index as usize].name.ends_with("executor_root7changed"))
            })
            .count();
        assert_eq!(notifications, 1);
''' + needle
    objects = replace_once(objects, needle, replacement)
    routing = replace_once((root / PREFIX / 'rust_component.rs').read_bytes(), 'fixed1221-node/5245-edge', 'fixed1221-node/5246-edge')
    routing = replace_once(routing, 'f401e388a7542b8f9cd9bbd987dbcc65814262d6', HEAD)
    changes = {
        'tools/rust_thread_host_catalogue.py': host_source,
        PREFIX + 'rust_catalogue.rs': records,
        PREFIX + 'rust_objects.rs': objects,
        PREFIX + 'rust_component.rs': routing,
        BASE + 'original-body-image.bin': image,
        BASE + 'catalogue-original-core.wasm': original,
        BASE + 'catalogue-normal-component.wasm': normal,
        BASE + 'origin.json': json_bytes(current),
    }
    test_name = 'tools/tests/test_rust_thread_host_catalogue.py'
    tests = (root / test_name).read_bytes()
    # Preserve every previous exact receipt assertion against its historical
    # object; the current projected fixtures get independent exact assertions.
    tests = replace_once(tests,
        "        envelope = origin['normalComponentEnvelope']\n",
        "        previous = origin['beforeRootRetirementRepair']\n"
        "        envelope = previous['normalComponentEnvelope']\n"
        "        candidate = origin['normalComponentEnvelope']\n")
    for field in ('historicalCatalogueOrigin', 'historicalNormalComponentFixture'):
        tests = tests.replace(("origin['" + field + "']").encode(),
                              ("previous['" + field + "']").encode())
    tests = replace_once(tests, "origin['origin']['head'], 'f401e388a7542b8f9cd9bbd987dbcc65814262d6'",
        "previous['origin']['head'], 'f401e388a7542b8f9cd9bbd987dbcc65814262d6'")
    tests = replace_once(tests, "origin['normalComponentEnvelopeStatus'],",
        "previous['normalComponentEnvelopeStatus'],")
    tests = tests.replace(b"origin['currentSourceObservation']['normalComponent",
                          b"previous['currentSourceObservation']['normalComponent")
    tests = replace_once(tests, 'self.assertEqual(len(component), 250260)',
        'self.assertEqual(len(component), ' + str(len(normal)) + ')')
    tests = replace_once(tests,
        "                         '0ded5f17359bbff107af47e422549765de2e17f4829853ed2011225d85a56107')",
        "                         '" + sha(normal)[7:] + "')")
    tests = replace_once(tests, "self.assertEqual(envelope['componentBytes'], len(component))",
        "self.assertEqual(candidate['componentBytes'], len(component))")
    tests = replace_once(tests, "self.assertEqual(envelope['componentDigest'],\n",
        "self.assertEqual(candidate['componentDigest'],\n")
    extra = """
        self.assertEqual(origin['origin']['head'], '72707ee61ce4784f7c866f2835f474554df8d922')
        self.assertEqual(origin['origin']['event'], 'push')
        self.assertEqual(origin['referenceCount'], 5246)
        self.assertEqual(previous['referenceCount'], 5245)
        self.assertEqual(envelope['componentBytes'], 250260)
        self.assertEqual(envelope['componentDigest'],
                         'sha256:0ded5f17359bbff107af47e422549765de2e17f4829853ed2011225d85a56107')
        self.assertEqual(candidate['derivedCoreDigest'],
                         'sha256:e976d80b529cdc91e5a6f2255d4aeb8db6412a690b039578c75a7dbd76363c22')
        self.assertEqual(origin['normalComponentEnvelopeStatus'],
                         'source-projected candidate; exact hosted encoding and mandatory 76 controls pending')
        self.assertTrue(candidate['candidateSource']['sourceProjectionOnly'])
        self.assertFalse(candidate['candidateSource']['hostedConfirmation'])
        self.assertFalse(candidate['candidateSource']['nativeNormalProofPassed'])
        self.assertFalse(candidate['candidateSource']['mandatory76Reached'])
        self.assertFalse(origin['currentSourceObservation']['normalComponentProduced'])
        self.assertFalse(origin['runtimeQualified'])
        self.assertFalse(origin['generationGrantsAuthority'])
        self.assertEqual(origin['originalBodyImageDigest'],
                         'sha256:eca9883441a2e8ef0b4ea721c53932866d117503382c6e8805cb7d7661fd1b8b')
        self.assertEqual(origin['currentSourceObservation']['retirementNotification']['offset'], 816)
"""
    tests = replace_once(tests,
        "    def test_reviewed_roots_require_public_lifecycle_and_private_pool_entrypoints(self):",
        extra + "\n    def test_reviewed_roots_require_public_lifecycle_and_private_pool_entrypoints(self):")
    changes[test_name] = tests
    contract_name = 'tools/ci/contracts/python/test_rust_thread_host_catalogue.py.json'
    contract = (root / contract_name).read_bytes()
    changes[contract_name] = replace_once(contract,
        'Bind the refreshed TLS catalogue candidate and preserve the previous hosted envelope origin',
        'Bind exact root-retirement catalogue and source-projected component; preserve every historical hosted receipt assertion and require independent encoder confirmation')
    output.mkdir(parents=True, exist_ok=False)
    identities = {}
    for name, data in changes.items():
        assert len(data) <= 4 * 1024 * 1024
        path = output / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        identities[name] = {'bytes': len(data), 'sha256': sha(data),
            'gitBlob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}
    (output / 'reviewed-files.json').write_bytes(json_bytes(identities))
    print(json.dumps(identities, indent=2))

if __name__ == '__main__':
    generate(*sys.argv[1:4], check_git='--check-git-source' in sys.argv[4:])
