"""Private, exact-preimage restoration of the pinned WASI RNG API stubs."""
from dataclasses import dataclass
import json
from pathlib import Path
import xml.etree.ElementTree as XML

from tools.build_observation import file_identity
from tools.dotnet_guest import http_errors
from tools.rust_capsule_project import digest, inventory, read_file, snapshot, write_json

PROFILE = 'dotnet-standard-rng-managed-v1'
SOURCE = 'sha256:7264a768f8e344533902eb61582fef1f737699bd5f11305b7f752193c809b8b4'
MAXIMUM = 512 * 1024

UPSTREAM = {'profile': 'dotnet-standard-rng-managed-v1',
 'revision': '8449ba666dd991e495d8363d9852f18eb86a1aa1',
 'repository': 'https://github.com/dotnet/runtimelab',
 'files': {'HexConverter.cs': {'digest': 'sha256:e470bdd76aad0ebf22dfcf14179a52f203b29f8f6215402c90a9e148c1705fed',
                               'size': 28511},
           'LICENSE.TXT': {'digest': 'sha256:cfc21f5e8bd655ae997eec916138b707b1d290b83272c02a95c9f821b8c87310',
                           'size': 1116},
           'RandomNumberGenerator.cs': {'digest': 'sha256:1844e4962e9824d79f0eaa998128b79810c53f365742cbbd53a1478774fead0c',
                                        'size': 18912},
           'RandomNumberGeneratorImplementation.Browser.cs': {'digest': 'sha256:c76b4d79dcff5a3eb39c396996286416d88fc845523060ae190ce9b4ded32a59',
                                                              'size': 495},
           'RandomNumberGeneratorImplementation.cs': {'digest': 'sha256:b96c87da91ddf287a97b2f7c4bb211ef3fa873a5c6abb2a07c01532474110f00',
                                                      'size': 3560}}}


def verify_source(source):
    files = snapshot(source)
    if json.loads(files["upstream.json"]) != UPSTREAM:
        raise ValueError("managed-entropy-upstream-identity")
    for name, expected in UPSTREAM["files"].items():
        body = files.get("upstream/" + name)
        if body is None or digest(body) != expected["digest"] or len(body) != expected["size"]:
            raise ValueError("managed-entropy-upstream-preimage")
    text = files["upstream/RandomNumberGenerator.cs"].decode("utf-8")
    begin = text.index("        [Obsolete(")
    end = text.index("        public void Dispose()", begin)
    text = text[:begin] + text[end:]
    text = text.replace("namespace System.Security.Cryptography", "namespace Lsf.StandardEntropy")
    text = text.replace("public abstract class RandomNumberGenerator : IDisposable",
                        "public abstract class RandomNumberGenerator : global::System.Security.Cryptography.RandomNumberGenerator")
    text = text.replace("public virtual ", "public override ").replace("public abstract void GetBytes",
            "public abstract override void GetBytes").replace("protected virtual void Dispose", "protected override void Dispose")
    expected = {"RandomNumberGenerator.cs": text.encode("utf-8"), "HexConverter.cs": files["upstream/HexConverter.cs"]}
    for name in ("RandomNumberGeneratorImplementation.cs", "RandomNumberGeneratorImplementation.Browser.cs"):
        expected[name] = files["upstream/" + name].replace(b"namespace System.Security.Cryptography", b"namespace Lsf.StandardEntropy")
    if any(files[name] != body for name, body in expected.items()):
        raise ValueError("managed-entropy-unreviewed-source-derivation")
    return files


def original(path):
    value = file_identity(path, 'standard-rng-original-framework', MAXIMUM)
    if value['digest'] != SOURCE or value['size'] != 284672:
        raise ValueError('managed-entropy-unsupported-framework-preimage')
    return value


@dataclass
class Port:
    source: Path
    originals: tuple
    identities: dict
    capture: bytes
    targets: Path
    target_bytes: bytes
    references: Path
    evidence: dict

    def recheck(self):
        if inventory(snapshot(self.source)) != self.capture:
            raise ValueError('managed-entropy-source-drift')
        for path in self.originals:
            original(path)
        for path, identity in self.identities.items():
            if file_identity(path, identity['name'], MAXIMUM) != identity:
                raise ValueError('managed-entropy-generated-material-drift')
        if read_file(self.targets, MAXIMUM) != self.target_bytes:
            raise ValueError('managed-entropy-target-drift')

    def finish(self, project, output):
        self.recheck()
        expected = {str(path) for path in self.identities}
        references = read_file(self.references, MAXIMUM).decode('utf-8-sig').splitlines()
        if (not 1 <= len(references) <= 512 or any(references.count(path) != 1 for path in expected)
                or any(Path(path).name == 'System.Security.Cryptography.dll' and path not in expected
                       for path in references)):
            raise ValueError('managed-entropy-reference-binding')
        matched = []
        responses = list((project / 'obj').rglob('*.rsp'))
        if len(responses) > 64:
            raise ValueError('managed-entropy-response-count')
        total = 0
        for path in responses:
            body = read_file(path, 1024 * 1024)
            total += len(body)
            if total > 4 * 1024 * 1024:
                raise ValueError('managed-entropy-response-bytes')
            selected = [line[3:].strip('"') for line in body.decode('utf-8-sig').splitlines()
                        if line.startswith('-r:') and Path(line[3:].strip('"')).name in {
                            'System.Security.Cryptography.dll', 'Lsf.StandardEntropy.dll'}]
            if selected:
                if len(selected) != 2 or set(selected) != expected:
                    raise ValueError('managed-entropy-native-reference-drift')
                matched.append({'digest': digest(body), 'size': len(body)})
        if len(matched) != 1:
            raise ValueError('managed-entropy-native-reference-not-observed')
        result = {**self.evidence, 'nativeAotReferenceBinding': matched,
                  'referenceListDigest': digest(read_file(self.references, MAXIMUM))}
        write_json(output / 'managed-entropy-port.json', result)
        return result


def prepare(compiler, project, output):
    source = compiler.sdk / 'tools/managed-entropy'
    before = verify_source(source)
    capture = inventory(before)
    root = compiler.package_cache / http_errors.PACKAGE
    originals = tuple(root / folder / 'System.Security.Cryptography.dll'
                      for folder in ('lib', 'native-hidden'))
    original_inputs = [original(path) for path in originals]
    cecil = http_errors.cecil_path(compiler.tools)
    http_errors.require_digest(cecil, http_errors.CECIL_DIGEST, 'managed-entropy-cecil')
    owned = output / 'managed-entropy-port'
    owned.mkdir(mode=0o700)
    staged = owned / 'source'
    staged.mkdir()
    for name, body in before.items():
        path = staged / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    (staged / 'global.json').write_bytes(read_file(compiler.sdk / 'global.json'))
    for name, destination in (('ManagedEntropy', 'helper'), ('Rewrite', 'rewrite')):
        compiler.run('managed-entropy-build-' + name.lower(), compiler.dotnet, 'build', staged / (name + '.csproj'),
                     '-c', 'Release', '--output', owned / destination,
                     '--artifacts-path', owned / ('artifacts-' + destination),
                     '-p:LsfCecilPath=' + str(cecil), '-p:RestoreConfigFile=' + str(staged / 'nuget.config'),
                     '-p:NuGetAudit=false', '-nodeReuse:false', '-p:UseSharedCompilation=false',
                     '-p:ImportDirectoryBuildProps=false', '-p:ImportDirectoryBuildTargets=false')
    helper = owned / 'helper/Lsf.StandardEntropy.dll'
    assembly = owned / 'System.Security.Cryptography.dll'
    receipt = owned / 'rewrite.json'
    compiler.run('managed-entropy-rewrite', compiler.dotnet, owned / 'rewrite/Rewrite.dll',
                 originals[1], helper, assembly, receipt)
    result = json.loads(read_file(receipt, MAXIMUM))
    identities = {path: file_identity(path, name, MAXIMUM) for path, name in (
        (helper, 'standard-rng-helper'), (assembly, 'standard-rng-derived-framework'))}
    if (result.get('patch') != 'latent.dotnet.standard-rng-managed.v1'
            or result.get('sourceDigest') != SOURCE or result.get('cecilDigest') != http_errors.CECIL_DIGEST
            or result.get('helperDigest') != identities[helper]['digest']
            or result.get('outputDigest') != identities[assembly]['digest']
            or len(set(result.get('replaced', []))) != 17 or result.get('unchangedMethods') != 3240
            or result.get('namedAlgorithmFactorySupported') is not False
            or result.get('applicationAssemblyEdits') != 0 or result.get('sharedPackageModified') is not False):
        raise ValueError('managed-entropy-rewrite-receipt')
    for name, body in before.items():
        if read_file(staged / name) != body:
            raise ValueError('managed-entropy-staged-source-drift')
    targets = owned / 'ManagedEntropy.targets'
    target_bytes = before['ManagedEntropy.targets']
    targets.write_bytes(target_bytes)
    references = owned / 'references.txt'
    document = XML.fromstring(read_file(project / 'Capsule.csproj', MAXIMUM))
    props = XML.SubElement(document, 'PropertyGroup')
    for name, path in (('OriginalPublic', originals[0]), ('OriginalPrivate', originals[1]),
                       ('Assembly', assembly), ('Helper', helper), ('ReferenceReceipt', references)):
        XML.SubElement(props, 'LsfManagedEntropy' + name).text = http_errors.msbuild_literal(path)
    XML.SubElement(document, 'Import', Project=http_errors.msbuild_literal(targets))
    (project / 'Capsule.csproj').write_bytes(XML.tostring(document, encoding='utf-8', xml_declaration=True))
    evidence = {**result, 'profile': PROFILE, 'frameworkInputs': original_inputs,
                'sourceCaptureDigest': digest(capture), 'targetsDigest': digest(target_bytes),
                'helper': identities[helper], 'derived': identities[assembly], 'nativeAotReferenceBinding': None}
    write_json(compiler.commands.output / 'managed-entropy-preparation.json', evidence)
    if compiler.isolation:
        compiler.isolation.protect_inputs(helper, assembly, targets)
    port = Port(source, originals, identities, capture, targets, target_bytes, references, evidence)
    port.recheck()
    return port
