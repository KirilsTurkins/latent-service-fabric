"""Explicit pinned Gradle resolution of ordinary Maven coordinates and local JARs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import tomllib
from urllib.parse import urlsplit

from tools.application_dependencies import (MANIFEST, LOCK, MAX_CLOSURE_BYTES, capture, document,
                                           metadata, label, validate_manifest)
from tools.application_dependency_store import DependencyError, Store, read_bytes, regular_path
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_snapshot import canonical, digest
from tools.java_resource_artifacts import capture_resources, release_profile
from tools import java_registry_tls
from tools import java_annotation_processors
from tools.rust_capsule_project import ROOT

DECLARATIONS = "java-dependencies.json"
RESOLUTION = "java-resolved.lock.json"
TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")


def declarations(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != {"formatVersion", "dependencies", "localJars", "repositories", "selection"}
            or type(value["formatVersion"]) is not int or value["formatVersion"] != 1 or not isinstance(value["dependencies"], list)
            or not isinstance(value["localJars"], list) or not isinstance(value["repositories"], list)
            or len(value["dependencies"]) + len(value["localJars"]) > 256 or not 1 <= len(value["repositories"]) <= 64
            or not isinstance(value["selection"], dict)):
        raise DependencyError("java-dependency-declarations")
    metadata(value["selection"])
    release_profile(value["selection"].get("release", 25))
    for row in value["dependencies"]:
        if (not isinstance(row, dict) or set(row) not in ({"group", "name", "version", "scope", "exclusions"},
                {"group", "name", "version", "scope", "exclusions", "processorClasses"},
                {"group", "name", "version", "scope", "exclusions", "processorInput"})
                or not all(isinstance(row[key], str) and TOKEN.fullmatch(row[key]) for key in ("group", "name", "version"))
                or not re.fullmatch(r"[0-9][A-Za-z0-9_.-]*", row["version"]) or "SNAPSHOT" in row["version"]
                or row["scope"] not in {"compile", "runtime"} or not isinstance(row["exclusions"], list)
                or len(row["exclusions"]) > 256):
            raise DependencyError("java-maven-coordinate-or-scope-invalid")
        if 'processorClasses' in row:
            java_annotation_processors.classes(row['processorClasses'])
        if 'processorInput' in row and row['processorInput'] is not True:
            raise DependencyError('java-annotation-processor-input-declaration-invalid')
        for excluded in row["exclusions"]:
            if (not isinstance(excluded, dict) or set(excluded) != {"group", "name"}
                    or not all(isinstance(excluded[key], str) and TOKEN.fullmatch(excluded[key]) for key in excluded)):
                raise DependencyError("java-maven-exclusion-invalid")
    for row in value["repositories"]:
        if (not isinstance(row, dict) or set(row) not in ({"id", "url"}, {"id", "url", "tlsTrust"})
                or not isinstance(row["id"], str) or not TOKEN.fullmatch(row["id"])
                or not isinstance(row["url"], str)):
            raise DependencyError("java-repository-policy-invalid")
        parsed = urlsplit(row["url"])
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise DependencyError("java-repository-credentials-denied")
    java_registry_tls.certificates(value)
    for row in value["localJars"]:
        if (not isinstance(row, dict) or set(row) not in ({"id", "path", "dependencies"},
                {"id", "path", "dependencies", "processorClasses"},
                {"id", "path", "dependencies", "processorInput"})
                or not isinstance(row["dependencies"], list) or len(row["dependencies"]) > 1024
                or not isinstance(row["path"], str) or not 0 < len(row["path"]) <= 4096 or '\0' in row["path"]):
            raise DependencyError("java-local-jar-declaration-invalid")
        if 'processorClasses' in row:
            java_annotation_processors.classes(row['processorClasses'])
        if 'processorInput' in row and row['processorInput'] is not True:
            raise DependencyError('java-annotation-processor-input-declaration-invalid')
        label(row['id'])
        if len(set(row['dependencies'])) != len(row['dependencies']):
            raise DependencyError('java-local-jar-declaration-invalid')
        for dependency in row['dependencies']:
            label(dependency)
    if (len({(row['group'], row['name']) for row in value['dependencies']}) != len(value['dependencies'])
            or len({row['id'] for row in value['localJars']}) != len(value['localJars'])
            or len({row['id'].upper().replace('-', '_') for row in value['repositories']}) != len(value['repositories'])):
        raise DependencyError('java-declaration-identity-or-credential-slot-ambiguous')
    return value


def script(config: dict) -> str:
    # Data is serialized into an SDK-owned task; application Gradle/plugin code
    # never executes. Gradle performs its native conflict/exclusion resolution.
    encoded = json.dumps(config, ensure_ascii=True).replace("\\", "\\\\").replace("'", "\\'")
    return """import groovy.json.JsonOutput
import groovy.json.JsonSlurper
def declaration = new JsonSlurper().parseText('""" + encoded + """')
repositories {
    declaration.repositories.each { repository ->
        maven { name = repository.id; url = uri(repository.url)
            def prefix = 'LSF_REGISTRY_' + repository.id.toUpperCase().replace('-', '_')
            if (System.getenv(prefix + '_USERNAME') != null) {
                credentials { username = System.getenv(prefix + '_USERNAME'); password = System.getenv(prefix + '_PASSWORD') }
            }
        }
    }
}
configurations { capturedRuntime }
configurations.capturedRuntime {
    attributes {
        attribute(org.gradle.api.attributes.Usage.USAGE_ATTRIBUTE, objects.named(org.gradle.api.attributes.Usage, org.gradle.api.attributes.Usage.JAVA_RUNTIME))
        attribute(org.gradle.api.attributes.Category.CATEGORY_ATTRIBUTE, objects.named(org.gradle.api.attributes.Category, org.gradle.api.attributes.Category.LIBRARY))
        attribute(org.gradle.api.attributes.LibraryElements.LIBRARY_ELEMENTS_ATTRIBUTE, objects.named(org.gradle.api.attributes.LibraryElements, org.gradle.api.attributes.LibraryElements.JAR))
        attribute(org.gradle.api.attributes.java.TargetJvmVersion.TARGET_JVM_VERSION_ATTRIBUTE, 25)
    }
    resolutionStrategy.failOnDynamicVersions()
    resolutionStrategy.failOnChangingVersions()
}
dependencies {
    declaration.dependencies.each { dependency ->
        add('capturedRuntime', dependency.group + ':' + dependency.name + ':' + dependency.version) {
            dependency.exclusions.each { excluded -> exclude group: excluded.group, module: excluded.name }
        }
    }
}
tasks.register('captureRuntime') {
    doLast {
        def configuration = configurations.capturedRuntime
        def graph = configuration.incoming.resolutionResult.allComponents.findAll {
            it.id instanceof org.gradle.api.artifacts.component.ModuleComponentIdentifier
        }.collect { component ->
            [id: component.moduleVersion.toString(), group: component.moduleVersion.group,
             name: component.moduleVersion.name, version: component.moduleVersion.version,
             selectedBy: component.selectionReason.toString(), variants: component.variants.collect { variant ->
                [name: variant.displayName, attributes: variant.attributes.keySet().collectEntries { key -> [key.name, variant.attributes.getAttribute(key).toString()] }]
             }, dependencies: component.dependencies.collect { dependency ->
                if (!(dependency instanceof org.gradle.api.artifacts.result.ResolvedDependencyResult)) throw new GradleException('uncaptured-dependency')
                [requested: dependency.requested.displayName, selected: dependency.selected.moduleVersion.toString()]
             }]
        }
        def artifacts = configuration.resolvedConfiguration.resolvedArtifacts.collect { artifact ->
            [id: artifact.moduleVersion.id.toString(), classifier: artifact.classifier, type: artifact.type, file: artifact.file.absolutePath]
        }
        file('resolved.json').text = JsonOutput.toJson([graph: graph, artifacts: artifacts]) + '\\n'
    }
}
"""


def resolve(project: Path, candidate: Path, *, gradle: str = "gradle") -> dict:
    from tools.java_dependency_authoring import transaction
    with transaction(project) as (owner, app, private, sdk):
        return _resolve(owner, app, private, sdk, candidate, gradle=gradle)


def _resolve(owner: Path, project: Path, private: Path, sdk, candidate: Path, *, gradle: str) -> dict:
    from tools.java_dependency_authoring import candidate_location, optional, replace, unchanged
    from tools.dev_workflow import paths
    from tools.rust_capsule_project import snapshot
    candidate = candidate_location(owner, candidate)
    if os.path.lexists(candidate):
        raise DependencyError("java-lock-candidate-exists")
    before = snapshot(project)
    previous_manifest, previous_lock = optional(owner, MANIFEST), optional(owner, LOCK)
    previous_graph = optional(project, RESOLUTION)
    recipe_paths = [Path(__file__), ROOT / 'tools/java_registry_tls.py', ROOT / 'tools/java_annotation_processors.py',
                    ROOT / 'tools/java_dependency_authoring.py', ROOT / 'tools/java_resource_artifacts.py',
                    ROOT / 'tools/java_application_dependencies.py', ROOT / 'tools/toolchain.toml']
    recipe_before = {str(path): digest(read_bytes(path)) for path in recipe_paths}
    declaration_bytes = read_bytes(project / DECLARATIONS)
    config = declarations(document(project / DECLARATIONS))
    pins = tomllib.loads(read_bytes(ROOT / "tools/toolchain.toml").decode())
    store = Store(owner / "dependency-inputs/objects")
    with tempfile.TemporaryDirectory(prefix="lsf-java-resolution-", dir=private) as owned:
        work = Path(owned)
        environment = build_environment(work)
        environment.update(HOME=str(work / "home"), USERPROFILE=str(work / "home"), GRADLE_USER_HOME=str(work / "gradle"))
        if "JAVA_HOME" in os.environ:
            environment["JAVA_HOME"] = os.environ["JAVA_HOME"]
        trust_sources = {}
        tools_before = {}
        resolver = {'name': 'captured-local-jar', 'version': '1', 'recipeDigest': recipe_before[str(Path(__file__))]}
        if config['dependencies']:
            # Validate selected credentials before acquisition, but pass them
            # only to the real resolution task, not tool/version/TLS parsing.
            registry_credentials = {}
            java_registry_tls.credentials(config, registry_credentials)
            resolver_path = shutil.which(gradle, path=environment.get("PATH"))
            if not resolver_path:
                raise DependencyError("java-pinned-resolver-unavailable")
            resolver_digest = digest(read_bytes(Path(resolver_path)))
            java = shutil.which("java", path=environment.get("PATH"))
            if not java:
                raise DependencyError("java-pinned-resolution-jdk-unavailable")
            tools_before = {resolver_path: resolver_digest, java: digest(read_bytes(Path(java)))}
            java_version = run_bounded_result([java, "-version"], work, environment, 30, 16384)
            reported = (java_version.stdout + java_version.stderr).decode("utf-8")
            if java_version.returncode or pins["sdk"]["java"] not in reported:
                raise DependencyError("java-pinned-resolution-jdk-version-mismatch")
            version = run_bounded_result([resolver_path, "--version"], work, environment, 30, 16384)
            if version.returncode or not re.search(r"\bGradle " + re.escape(pins["sdk"]["gradle"]) + r"\b", version.stdout.decode("utf-8")):
                raise DependencyError("java-pinned-resolver-version-mismatch")
            (work / "settings.gradle").write_text("rootProject.name = 'captured-application-resolution'\n", encoding="utf-8")
            (work / "gradle.properties").write_text("org.gradle.java.installations.auto-download=false\n", encoding="utf-8")
            (work / "build.gradle").write_text(script(config), encoding="utf-8")
            trust_arguments, trust_sources, trust_inputs, trust_identity = java_registry_tls.prepare(
                project, config, work, Path(java), environment)
            tools_before.update(trust_inputs)
            environment.update(registry_credentials)
            result = run_bounded_result([resolver_path, *trust_arguments, "--no-daemon", "captureRuntime"], work, environment, 300, 4 * 1024 * 1024)
            if result.returncode:
                raise DependencyError("java-maven-resolution-failed-private-diagnostics-discarded")
            resolved = document(work / "resolved.json")
            resolver = {'name': 'gradle', 'version': pins['sdk']['gradle'], 'executableDigest': resolver_digest,
                        'jdkVersion': pins['sdk']['java'], 'jdkExecutableDigest': tools_before[java]}
            if trust_identity is not None:
                resolver['tlsTrustInputs'] = trust_identity
        else:
            resolved = {'graph': [], 'artifacts': []}
        if len(resolved["graph"]) > 1024 or len(resolved["artifacts"]) > 1024:
            raise DependencyError("java-dependency-graph-limit")
        graph = {row["id"]: row for row in resolved["graph"]}
        jar_ids = {row["id"] for row in resolved["artifacts"]}
        if len(graph) != len(resolved['graph']) or len(jar_ids) != len(resolved['artifacts']):
            raise DependencyError('java-native-module-selection-ambiguous')
        # Fresh resolution metadata contains selected POMs, parent/BOM metadata
        # and Gradle module descriptors. Keep original bytes rather than infer
        # the complete native graph from the classpath's JAR names.
        metadata_files = sorted((work / "gradle/caches/modules-2/files-2.1").glob("*/*/*/*/*"))
        metadata_paths = [path for path in metadata_files if path.suffix in {".pom", ".module"}]
        metadata_rows = []
        primary_metadata = {}
        for index, selected_path in enumerate(metadata_paths):
            group, name, selected_version, _key, _filename = selected_path.relative_to(work / "gradle/caches/modules-2/files-2.1").parts
            coordinate = f"{group}:{name}:{selected_version}"
            selected_id = coordinate if coordinate in graph and coordinate not in jar_ids else coordinate + f"/metadata-{index}"
            if selected_id == coordinate and coordinate in primary_metadata:
                selected_id += f"/metadata-{index}"
            primary_metadata.setdefault(coordinate, selected_id)
            identity = store.put(read_bytes(selected_path))
            metadata_rows.append({"id": selected_id, "role": "application", "format": "file",
                "mount": f"dependencies/java/metadata/{index:04d}{selected_path.suffix}",
                "source": {"path": store.path(identity["digest"]).relative_to(owner).as_posix()},
                "dependencies": [], "metadata": {"ecosystem": "maven", "assetType": "maven-resolution-metadata", "coordinates": coordinate}})
        artifacts, identities = [], {}
        for index, row in enumerate(sorted(resolved["artifacts"], key=lambda row: row["id"])):
            if row["type"] != "jar" or row["classifier"] is not None:
                raise DependencyError("java-selected-artifact-type-unsupported")
            path = regular_path(Path(row["file"]))
            if not path.is_relative_to(work):
                raise DependencyError("java-resolver-artifact-escape")
            identity = store.put(read_bytes(path))
            source = store.path(identity["digest"]).relative_to(owner).as_posix()
            component = graph[row["id"]]
            edges = sorted({edge["selected"] if edge["selected"] in jar_ids else primary_metadata.get(edge["selected"], edge["selected"])
                            for edge in component["dependencies"]})
            artifacts.append({"id": row["id"], "role": "application", "format": "file",
                "mount": f"dependencies/java/{index:04d}.jar", "source": {"path": source}, "dependencies": edges,
                "metadata": {"ecosystem": "maven", "coordinates": row["id"], "scope": "selected-runtime",
                             "resolution": component, "repositoryPolicy": [row["id"] for row in config["repositories"]]}})
            identities[row["id"]] = identity
        artifacts.extend(metadata_rows)
        local_before = {}
        for row in config["localJars"]:
            selected = regular_path(project / row['path'])
            payload = read_bytes(selected)
            local_before[selected] = digest(payload)
            identity = store.put(payload)
            artifacts.append({"id": row["id"], "role": "application", "format": "file",
                "mount": f"dependencies/java/{len(artifacts):04d}.jar",
                "source": {"path": store.path(identity["digest"]).relative_to(owner).as_posix()},
                "dependencies": list(row["dependencies"]), "metadata": {"ecosystem": "captured-local-jar", "scope": "runtime",
                    "originalLocalPath": row['path']}})
            identities[row["id"]] = identity
        java_annotation_processors.mark(config, artifacts)
        artifacts = capture_resources(owner, store, artifacts)
        native = {"formatVersion": 1, "resolver": resolver, "graph": list(graph.values()),
                  "artifacts": identities, "configurationDigest": digest(read_bytes(project / DECLARATIONS)),
                  "selection": config["selection"], "lifecycleScripts": "disabled"}
        native_bytes = canonical(native) + b'\n'
        prefix = project.relative_to(owner).as_posix() + '/' if owner != project else ''
        manifest = {"formatVersion": 1, "language": "java", "selection": config["selection"],
                    "nativeLocks": [prefix + DECLARATIONS, prefix + RESOLUTION,
                                    *(prefix + name for name in trust_sources)], "artifacts": artifacts, "transformations": []}
        validate_manifest(manifest, 'java')
        manifest_bytes = canonical(manifest) + b'\n'
        check = work / 'capture-inputs'; check.mkdir(mode=0o700)
        (check / MANIFEST).write_bytes(manifest_bytes)
        for name, payload in ((DECLARATIONS, declaration_bytes), (RESOLUTION, native_bytes), *trust_sources.items()):
            target = check / (prefix + name); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        # Capture the exact final portable manifest. Its source objects are
        # verified private copies; no receipt identity is rewritten afterward.
        copied, copied_bytes = set(), 0
        for row in artifacts:
            source = row['source']['path']
            paths.relative(source)
            if source in copied:
                continue
            payload = read_bytes(owner / source)
            copied_bytes += len(payload)
            if copied_bytes > MAX_CLOSURE_BYTES:
                raise DependencyError('dependency-closure-limit')
            target = check / source; target.parent.mkdir(parents=True, exist_ok=True)
            paths.write_new(target, payload)
            copied.add(source)
        lock = capture(check, cache=owner / 'dependency-inputs/objects')
        if (snapshot(project) != before or read_bytes(project / DECLARATIONS) != declaration_bytes
                or any(digest(read_bytes(path)) != identity for path, identity in local_before.items())
                or any(digest(read_bytes(Path(path))) != identity for path, identity in tools_before.items())
                or any(digest(read_bytes(Path(path))) != identity for path, identity in recipe_before.items())
                or optional(owner, MANIFEST) != previous_manifest or optional(owner, LOCK) != previous_lock):
            raise DependencyError('java-declaration-lock-tool-or-capture-input-mutated')
        unchanged(owner, sdk)
        replace(owner, private, prefix + RESOLUTION, native_bytes, previous_graph, sdk)
        replace(owner, private, MANIFEST, manifest_bytes, previous_manifest, sdk)
        candidate.parent.mkdir(parents=True, exist_ok=True)
        paths.write_new(candidate, canonical(lock) + b'\n')
        return lock
