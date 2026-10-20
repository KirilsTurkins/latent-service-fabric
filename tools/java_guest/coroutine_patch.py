"""Exact TeaVM 0.15 copied-phi repair in a private compiler JAR, never its cache."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import zipfile

from tools.rust_capsule_project import read_file

UPSTREAM_SHA256 = '5fb6d1c6e33fb4418239ec4c3cb93435b194bf5b3d36e8350836e2830567ba8c'
BEFORE = 'phi.getIncomings().removeIf(incoming -> !domainSet.contains(incoming.getSource().getIndex()));'
AFTER = ('phi.getIncomings().removeIf(incoming -> !domainSet.contains(incoming.getSource().getIndex())\n'
         '                            && !copiedSet.contains(incoming.getSource().getIndex()));')
DOMAIN = 'var domainSet = IntHashSet.from(remaining);'
COPIED_DOMAIN = DOMAIN + '\n            var copiedSet = IntHashSet.from(copies);'
CLASS_ROOT = 'org/teavm/backend/lowlevel/transform/'
PATCH_CLASSES = frozenset(CLASS_ROOT + name for name in (
    'CoroutineTransformation.class', 'CoroutineTransformation$1.class',
    'CoroutineTransformation$SplittingBackend.class'))
CONTROL = CLASS_ROOT + 'Check.class'
MAX_JAR_BYTES = 64 * 1024 * 1024


def corrected_source(raw: bytes) -> bytes:
    if hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('unreviewed-teavm-coroutine-source')
    source = raw.decode('utf-8')
    if source.count(BEFORE) != 1 or source.count(DOMAIN) != 1:
        raise ValueError('unreviewed-teavm-coroutine-predicate')
    return source.replace(DOMAIN, COPIED_DOMAIN).replace(BEFORE, AFTER).encode('utf-8')


def checked_jars(compiler, project: Path) -> list[Path]:
    from tools.java_guest.compiler import source_module
    module = source_module(compiler.sdk / 'tools/dependencies.py')
    observed = module.cache_inventory(compiler.dependency_cache)
    lock = json.loads(read_file(project / 'dependencies.lock.json'))
    module.verify_inventory(observed, lock, project / 'gradle/verification-metadata.xml')
    selected = []
    for row in observed['artifacts']:
        parts = row['path'].split('/')
        group, name, version, filename = '.'.join(parts[:-3]), *parts[-3:]
        candidates = list((compiler.dependency_cache / group / name / version).glob('*/' + filename))
        if len(candidates) != 1:
            raise ValueError('coroutine-patch-jar-selection')
        path = candidates[0]
        if module.file_identity(path) != {'sha256': row['sha256'], 'size': row['size']}:
            raise ValueError('coroutine-patch-jar-mutated')
        selected.append(path)
    return selected


def jar_identities(cache: Path, jars: list[Path]) -> list[dict]:
    result = []
    for path in jars:
        group, name, version, _key, filename = path.relative_to(cache).parts
        raw = read_file(path, MAX_JAR_BYTES)
        result.append({'coordinate': '/'.join((group.replace('.', '/'), name, version, filename)),
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
    return sorted(result, key=lambda row: row['coordinate'])


def jar_entries(path: Path) -> dict[str, bytes]:
    raw = read_file(path, MAX_JAR_BYTES)
    import io
    result, total = {}, 0
    with zipfile.ZipFile(io.BytesIO(raw)) as jar:
        for member in jar.infolist():
            if (len(result) >= 32768 or member.filename in result
                    or member.file_size > 16 * 1024 * 1024 or member.flag_bits & 1
                    or member.filename.startswith('/') or '\\' in member.filename
                    or '..' in member.filename.split('/')):
                raise ValueError('coroutine-patch-jar-entry')
            total += member.file_size
            if total > 128 * 1024 * 1024:
                raise ValueError('coroutine-patch-jar-bound')
            result[member.filename] = jar.read(member)
    if {name for name in result if name.startswith(CLASS_ROOT + 'CoroutineTransformation')
            and name.endswith('.class')} != PATCH_CLASSES:
        raise ValueError('coroutine-patch-class-closure')
    return result


def replace_jar(original: Path, classes: Path, target: Path) -> dict:
    entries = jar_entries(original)
    actual = {path.relative_to(classes).as_posix() for path in classes.rglob('*') if path.is_file()}
    if actual != PATCH_CLASSES | {CONTROL} or target.exists():
        raise ValueError('coroutine-patch-compiled-closure')
    identities = {}
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as output:
        for name, raw in sorted(entries.items()):
            if name in PATCH_CLASSES:
                replacement = read_file(classes / name, 1024 * 1024)
                if not replacement.startswith(b'\xca\xfe\xba\xbe'):
                    raise ValueError('coroutine-patch-class-format')
                identities[name] = {'originalSha256': hashlib.sha256(raw).hexdigest(),
                    'replacementSha256': hashlib.sha256(replacement).hexdigest()}
                raw = replacement
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            output.writestr(entry, raw)
    observed = jar_entries(target)
    if set(observed) != set(entries) or any(observed[name] != raw
            for name, raw in entries.items() if name not in PATCH_CLASSES):
        raise ValueError('coroutine-patch-unrelated-jar-entry-changed')
    return {'originalJarSha256': hashlib.sha256(read_file(original, MAX_JAR_BYTES)).hexdigest(),
        'replacementJarSha256': hashlib.sha256(read_file(target, MAX_JAR_BYTES)).hexdigest(),
        'replacedClasses': identities, 'unchangedEntries': len(entries) - len(PATCH_CLASSES)}


def stage(compiler, project: Path, destination: Path) -> dict:
    # The first ordinary classes task has already populated the strictly checked cache.
    jars = checked_jars(compiler, project)
    original = [path for path in jars if path.name == 'teavm-core-0.15.0.jar']
    if len(original) != 1:
        raise ValueError('coroutine-patch-core-selection')
    identities = jar_identities(compiler.dependency_cache, jars)
    sdk = compiler.sdk / 'fibers/compiler-patch'
    folder = project / 'compiler-patch'; folder.mkdir()
    source = folder / 'CoroutineTransformation.java'
    raw = read_file(sdk / 'CoroutineTransformation.java')
    corrected = corrected_source(raw); source.write_bytes(corrected)
    control = folder / 'Check.java'; control.write_bytes(read_file(sdk / 'Check.java'))
    # Compiler.run provides the original process, output and remaining-time bounds.
    classes = folder / 'classes'
    read_file(sdk / 'Compile.java')
    compiler.run('java-coroutine-patch', 'java', sdk / 'Compile.java', source, control, classes,
                 os.pathsep.join(map(str, jars)))
    replacement = folder / 'teavm-core-patched.jar'
    receipt = replace_jar(original[0], classes, replacement)
    for mode, selected in (('original', original[0]), ('corrected', replacement)):
        classpath = os.pathsep.join(map(str, [selected, classes, *[p for p in jars if p != original[0]]]))
        observed = compiler.run('java-coroutine-' + mode + '-control', 'java', '-cp', classpath,
            'org.teavm.backend.lowlevel.transform.Check', mode)
        if json.loads(observed) != {'schemaVersion': 'latent.java.coroutine-phi-control.v1',
                'mode': mode, 'passed': True}:
            raise ValueError('coroutine-patch-real-ir-control')
    if identities != jar_identities(compiler.dependency_cache, checked_jars(compiler, project)):
        raise ValueError('coroutine-patch-original-input-mutated')
    build = project / 'build.gradle'; script = read_file(build).decode('utf-8')
    before = "dependencies { classpath 'org.teavm:teavm-gradle-plugin:0.15.0' }"
    after = ("dependencies { classpath files('compiler-patch/teavm-core-patched.jar'); "
             "classpath 'org.teavm:teavm-gradle-plugin:0.15.0' }")
    if script.count(before) != 1:
        raise ValueError('coroutine-patch-buildscript-drift')
    script = script.replace(before, after)
    script += '''
tasks.named('generateC') {
    doFirst {
        def actual = Class.forName('org.teavm.backend.lowlevel.transform.CoroutineTransformation',
            false, org.teavm.backend.c.CTarget.class.classLoader)
        def selected = file('compiler-patch/teavm-core-patched.jar').canonicalFile
        if (new File(actual.protectionDomain.codeSource.location.toURI()).canonicalFile != selected) {
            throw new GradleException('coroutine-patch-loaded-class-mismatch')
        }
        def hash = java.security.MessageDigest.getInstance('SHA-256').digest(selected.bytes).encodeHex().toString()
        if (hash != '__PATCH_SHA256__') throw new GradleException('coroutine-patch-loaded-jar-mutated')
        file('compiler-patch/loaded.json').text = groovy.json.JsonOutput.toJson([
            schemaVersion: 'latent.java.coroutine-compiler-load.v1',
            selectedOwnedReplacement: true, replacementJarSha256: hash])
    }
}
'''.replace('__PATCH_SHA256__', receipt['replacementJarSha256'])
    build.write_bytes(script.encode('utf-8'))
    receipt.update(schemaVersion='latent.java.coroutine-compiler-patch.v1',
        upstreamSourceSha256=UPSTREAM_SHA256, correctedSourceSha256=hashlib.sha256(corrected).hexdigest(),
        realOriginalIrDefectObserved=True, realCorrectedIrInputsPreserved=True,
        originalInputsUnchanged=True, checkedCompilerJars=identities)
    return receipt


def loaded(project: Path, receipt: dict, *, compiler=None) -> dict:
    if compiler is not None and receipt['checkedCompilerJars'] != jar_identities(
            compiler.dependency_cache, checked_jars(compiler, project)):
        raise ValueError('coroutine-patch-original-input-mutated')
    actual = json.loads(read_file(project / 'compiler-patch/loaded.json', 4096))
    if (type(actual) is not dict or actual.get('selectedOwnedReplacement') is not True
            or actual != {'schemaVersion': 'latent.java.coroutine-compiler-load.v1',
            'selectedOwnedReplacement': True, 'replacementJarSha256': receipt['replacementJarSha256']}):
        raise ValueError('coroutine-patch-loaded-receipt-mismatch')
    if hashlib.sha256(read_file(project / 'compiler-patch/teavm-core-patched.jar', MAX_JAR_BYTES)).hexdigest() != receipt['replacementJarSha256']:
        raise ValueError('coroutine-patch-used-jar-mutated')
    return {**receipt, 'loadedCompiler': actual}
