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
RELOCATED_IMPORTS = ('IntHashSet', 'IntIntHashMap', 'IntSet')


def corrected_source(raw: bytes) -> bytes:
    if hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('unreviewed-teavm-coroutine-source')
    source = raw.decode('utf-8')
    if source.count(BEFORE) != 1 or source.count(DOMAIN) != 1:
        raise ValueError('unreviewed-teavm-coroutine-predicate')
    source = source.replace(DOMAIN, COPIED_DOMAIN).replace(BEFORE, AFTER)
    # The published 0.15.0 artifacts relocate HPPC, unlike the Git source tree.
    for name in RELOCATED_IMPORTS:
        before = 'import com.carrotsearch.hppc.' + name + ';'
        if source.count(before) != 1:
            raise ValueError('unreviewed-teavm-coroutine-relocation')
        source = source.replace(before, 'import org.teavm.hppc.' + name + ';')
    return source.encode('utf-8')


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


def check_relocated_classes(jars: list[Path]) -> None:
    import io
    selected = [path for path in jars if path.name == 'teavm-relocated-libs-hppc-0.15.0.jar']
    if len(selected) != 1:
        raise ValueError('coroutine-patch-relocated-library')
    with zipfile.ZipFile(io.BytesIO(read_file(selected[0], MAX_JAR_BYTES))) as jar:
        entries = jar.infolist()
        if len(entries) > 32768 or len({entry.filename for entry in entries}) != len(entries):
            raise ValueError('coroutine-patch-relocated-entries')
        for name in RELOCATED_IMPORTS:
            entry = jar.getinfo('org/teavm/hppc/' + name + '.class')
            if entry.is_dir() or entry.file_size > 1024 * 1024 or not jar.read(entry).startswith(b'\xca\xfe\xba\xbe'):
                raise ValueError('coroutine-patch-relocated-class')


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


CLASSPATH_DECLARATION = "dependencies { classpath 'org.teavm:teavm-gradle-plugin:0.15.0' }"
_CLASSPATH_RECORD_HOOK = """
// Record the original resolved compiler graph in the already-required classes task.
tasks.named('classes') {
    doLast {
        def configuration = buildscript.configurations.classpath
        def artifacts = configuration.resolvedConfiguration.resolvedArtifacts
        def rows = configuration.files.collect { selected ->
            def artifact = artifacts.find { it.file.canonicalFile == selected.canonicalFile }
            if (artifact == null || !selected.isFile() || selected.length() > 67108864) {
                throw new GradleException('coroutine-patch-original-classpath-artifact')
            }
            def id = artifact.moduleVersion.id
            [coordinate: id.group.replace('.', '/') + '/' + id.name + '/' + id.version + '/' + selected.name,
             sha256: java.security.MessageDigest.getInstance('SHA-256').digest(selected.bytes).encodeHex().toString(),
             bytes: selected.length()]
        }
        if (rows.isEmpty() || rows.size() > 512) throw new GradleException('coroutine-patch-original-classpath-bound')
        def text = groovy.json.JsonOutput.toJson([
            schemaVersion: 'latent.java.original-compiler-classpath.v1',
            outOfProcess: tasks.named('generateC').get().outOfProcess.get(), files: rows])
        if (text.getBytes('UTF-8').length > 262144) throw new GradleException('coroutine-patch-original-classpath-bound')
        file('coroutine-patch-original-classpath.json').text = text
    }
}
"""


def record_original_classpath(project: Path) -> None:
    build = project / 'build.gradle'
    script = read_file(build).decode('utf-8')
    if script.count(CLASSPATH_DECLARATION) != 1 or _CLASSPATH_RECORD_HOOK in script:
        raise ValueError('coroutine-patch-classpath-record-drift')
    build.write_bytes((script + _CLASSPATH_RECORD_HOOK).encode('utf-8'))


def original_classpath(compiler, project: Path, jars: list[Path]) -> list[Path]:
    from tools.rust_capsule_project import decode_json
    record = decode_json(read_file(project / 'coroutine-patch-original-classpath.json', 262144))
    if (type(record) is not dict or set(record) != {'schemaVersion', 'outOfProcess', 'files'}
            or record['schemaVersion'] != 'latent.java.original-compiler-classpath.v1'
            or record['outOfProcess'] is not False or type(record['files']) is not list
            or not 0 < len(record['files']) <= 512):
        raise ValueError('coroutine-patch-original-classpath-schema')
    identities = {row['coordinate']: row for row in jar_identities(compiler.dependency_cache, jars)}
    paths = {jar_identities(compiler.dependency_cache, [path])[0]['coordinate']: path for path in jars}
    selected, seen = [], set()
    for row in record['files']:
        if (type(row) is not dict or set(row) != {'coordinate', 'sha256', 'bytes'}
                or type(row['coordinate']) is not str or row['coordinate'] in seen
                or type(row['bytes']) is not int or row != identities.get(row['coordinate'])):
            raise ValueError('coroutine-patch-original-classpath-identity')
        seen.add(row['coordinate']); selected.append(paths[row['coordinate']])
    if sum(path.name == 'teavm-core-0.15.0.jar' for path in selected) != 1:
        raise ValueError('coroutine-patch-original-classpath-core')
    return selected


def _groovy_path(path: Path) -> str:
    value = path.as_posix()
    if any(char in value for char in '\x00\r\n'):
        raise ValueError('coroutine-patch-classpath-path')
    return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"


def stage(compiler, project: Path, destination: Path) -> dict:
    # The first ordinary classes task has already populated the strictly checked cache.
    jars = checked_jars(compiler, project)
    check_relocated_classes(jars)
    captured_classpath = original_classpath(compiler, project, jars)
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
    # Replace, rather than compete with, the exact original resolved graph.
    # Its transitive files remain in their original order; no application JARs
    # or guessed dependencies are added to the compiler loader.
    selected_classpath = [replacement if path == original[0] else path for path in captured_classpath]
    after = "dependencies { classpath files(" + ', '.join(map(_groovy_path, selected_classpath)) + ") }"
    if script.count(CLASSPATH_DECLARATION) != 1 or script.count(_CLASSPATH_RECORD_HOOK) != 1:
        raise ValueError('coroutine-patch-buildscript-drift')
    script = script.replace(_CLASSPATH_RECORD_HOOK, '').replace(CLASSPATH_DECLARATION, after)
    script += '''
tasks.named('generateC') {
    doFirst {
        if (outOfProcess.get() != false) throw new GradleException('coroutine-patch-process-mode-drift')
        def actual = Class.forName('org.teavm.backend.lowlevel.transform.CoroutineTransformation',
            false, org.teavm.backend.c.CTarget.class.classLoader)
        def selected = file('compiler-patch/teavm-core-patched.jar').canonicalFile
        def source = new File(actual.protectionDomain.codeSource.location.toURI())
        if (!java.nio.file.Files.isRegularFile(source.toPath(), java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
            throw new GradleException('coroutine-patch-loaded-source-bound')
        }
        def observed = source.canonicalFile
        if (observed.length() > 67108864) throw new GradleException('coroutine-patch-loaded-source-bound')
        def hash = java.security.MessageDigest.getInstance('SHA-256').digest(selected.bytes).encodeHex().toString()
        if (hash != '__PATCH_SHA256__') throw new GradleException('coroutine-patch-loaded-jar-mutated')
        def actualHash = java.security.MessageDigest.getInstance('SHA-256').digest(observed.bytes).encodeHex().toString()
        def kind = observed == selected ? 'owned-replacement' : actualHash == hash ? 'byte-identical-copy' : 'other'
        println('latent.java.coroutine-loader.v1 ' + groovy.json.JsonOutput.toJson([
            sourceKind: kind, sourceSha256: actualHash, expectedSha256: hash]))
        // Gradle 9.1 agent transforms may expose a byte-identical original copy.
        // Identity, rather than its cache pathname, is the compiler boundary.
        if (actualHash != hash) {
            throw new GradleException('coroutine-patch-loaded-class-mismatch')
        }
        def expectedClasses = new groovy.json.JsonSlurper().parseText('__EXPECTED_CLASSES__')
        def loadedClasses = [:]
        expectedClasses.each { name, expected ->
            def loadedClass = Class.forName(name.substring(0, name.length() - 6).replace('/', '.'), false, actual.classLoader)
            if (loadedClass.classLoader != actual.classLoader ||
                    new File(loadedClass.protectionDomain.codeSource.location.toURI()).canonicalFile != observed) {
                throw new GradleException('coroutine-patch-loaded-class-source')
            }
            def resource = actual.classLoader.getResource(name)
            def connection = resource?.openConnection()
            if (!(connection instanceof java.net.JarURLConnection) ||
                    new File(connection.jarFileURL.toURI()).canonicalFile != observed) {
                throw new GradleException('coroutine-patch-loaded-class-resource')
            }
            connection.useCaches = false
            def bytes = connection.inputStream.withCloseable { it.readNBytes(1048577) }
            if (bytes.length > 1048576) throw new GradleException('coroutine-patch-loaded-class-bound')
            def classHash = java.security.MessageDigest.getInstance('SHA-256').digest(bytes).encodeHex().toString()
            if (classHash != expected) throw new GradleException('coroutine-patch-loaded-class-bytes')
            loadedClasses[name] = classHash
        }
        file('compiler-patch/loaded.json').text = groovy.json.JsonOutput.toJson([
            schemaVersion: 'latent.java.coroutine-compiler-load.v1',
            selectedOwnedReplacement: true, replacementJarSha256: hash,
            loadedJarSha256: actualHash, codeSourceKind: kind, loadedClasses: loadedClasses])
    }
}
'''.replace('__PATCH_SHA256__', receipt['replacementJarSha256']).replace('__EXPECTED_CLASSES__',
        json.dumps({name: row['replacementSha256'] for name, row in receipt['replacedClasses'].items()},
                   sort_keys=True, separators=(',', ':')))
    build.write_bytes(script.encode('utf-8'))
    receipt.update(schemaVersion='latent.java.coroutine-compiler-patch.v1',
        upstreamSourceSha256=UPSTREAM_SHA256, correctedSourceSha256=hashlib.sha256(corrected).hexdigest(),
        realOriginalIrDefectObserved=True, realCorrectedIrInputsPreserved=True,
        originalInputsUnchanged=True, checkedCompilerJars=identities,
        publishedHppcRelocation='org.teavm.hppc',
        originalBuildscriptClasspath=[jar_identities(compiler.dependency_cache, [path])[0]
            for path in captured_classpath])
    preparation = json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(preparation) > 262144:
        raise ValueError('coroutine-patch-preparation-bound')
    (compiler.directory / 'coroutine-compiler-preparation.json').write_bytes(preparation)
    return receipt


def loaded(project: Path, receipt: dict, *, compiler=None) -> dict:
    if compiler is not None and receipt['checkedCompilerJars'] != jar_identities(
            compiler.dependency_cache, checked_jars(compiler, project)):
        raise ValueError('coroutine-patch-original-input-mutated')
    actual = json.loads(read_file(project / 'compiler-patch/loaded.json', 4096))
    if (type(actual) is not dict or actual.get('selectedOwnedReplacement') is not True
            or type(actual.get('codeSourceKind')) is not str
            or actual.get('codeSourceKind') not in {'owned-replacement', 'byte-identical-copy'}
            or actual != {'schemaVersion': 'latent.java.coroutine-compiler-load.v1',
            'selectedOwnedReplacement': True, 'replacementJarSha256': receipt['replacementJarSha256'],
            'loadedJarSha256': receipt['replacementJarSha256'], 'codeSourceKind': actual.get('codeSourceKind'),
            'loadedClasses': {name: row['replacementSha256'] for name, row in receipt['replacedClasses'].items()}}):
        raise ValueError('coroutine-patch-loaded-receipt-mismatch')
    if hashlib.sha256(read_file(project / 'compiler-patch/teavm-core-patched.jar', MAX_JAR_BYTES)).hexdigest() != receipt['replacementJarSha256']:
        raise ValueError('coroutine-patch-used-jar-mutated')
    return {**receipt, 'loadedCompiler': actual}
