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

from tools.application_dependencies import MANIFEST, LOCK, capture, document, metadata
from tools.application_dependency_store import DependencyError, Store, read_bytes, regular_path
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_snapshot import canonical, digest
from tools.java_resource_artifacts import capture_resources, release_profile
from tools.rust_capsule_project import ROOT

DECLARATIONS = "java-dependencies.json"
RESOLUTION = "java-resolved.lock.json"
TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")


def declarations(value: dict) -> dict:
    if (set(value) != {"formatVersion", "dependencies", "localJars", "repositories", "selection"}
            or value["formatVersion"] != 1 or not isinstance(value["dependencies"], list)
            or not isinstance(value["localJars"], list) or not isinstance(value["repositories"], list)
            or len(value["dependencies"]) + len(value["localJars"]) > 256 or not value["repositories"]):
        raise DependencyError("java-dependency-declarations")
    metadata(value["selection"])
    release_profile(value["selection"].get("release", 25))
    for row in value["dependencies"]:
        if (set(row) != {"group", "name", "version", "scope", "exclusions"}
                or not all(isinstance(row[key], str) and TOKEN.fullmatch(row[key]) for key in ("group", "name", "version"))
                or not re.fullmatch(r"[0-9][A-Za-z0-9_.-]*", row["version"]) or "SNAPSHOT" in row["version"]
                or row["scope"] not in {"compile", "runtime"} or not isinstance(row["exclusions"], list)):
            raise DependencyError("java-maven-coordinate-or-scope-invalid")
        for excluded in row["exclusions"]:
            if set(excluded) != {"group", "name"} or not all(TOKEN.fullmatch(excluded[key]) for key in excluded):
                raise DependencyError("java-maven-exclusion-invalid")
    for row in value["repositories"]:
        if set(row) != {"id", "url"} or not TOKEN.fullmatch(row["id"]):
            raise DependencyError("java-repository-policy-invalid")
        parsed = urlsplit(row["url"])
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise DependencyError("java-repository-credentials-denied")
    for row in value["localJars"]:
        if set(row) != {"id", "path", "dependencies"} or not isinstance(row["dependencies"], list):
            raise DependencyError("java-local-jar-declaration-invalid")
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
    project = regular_path(project)
    if candidate.exists():
        raise DependencyError("java-lock-candidate-exists")
    declaration_bytes = read_bytes(project / DECLARATIONS)
    config = declarations(document(project / DECLARATIONS))
    pins = tomllib.loads(read_bytes(ROOT / "tools/toolchain.toml").decode())
    store = Store(project / "dependency-inputs/objects")
    with tempfile.TemporaryDirectory(prefix="lsf-java-resolution-") as owned:
        work = Path(owned)
        environment = build_environment(work)
        environment.update(HOME=str(work / "home"), USERPROFILE=str(work / "home"), GRADLE_USER_HOME=str(work / "gradle"))
        if "JAVA_HOME" in os.environ:
            environment["JAVA_HOME"] = os.environ["JAVA_HOME"]
        # Separately configured private-feed credentials exist only here.
        for row in config["repositories"]:
            prefix = "LSF_REGISTRY_" + row["id"].upper().replace("-", "_")
            for suffix in ("_USERNAME", "_PASSWORD"):
                if prefix + suffix in os.environ:
                    environment[prefix + suffix] = os.environ[prefix + suffix]
        resolver_path = shutil.which(gradle, path=environment.get("PATH"))
        if not resolver_path:
            raise DependencyError("java-pinned-resolver-unavailable")
        resolver_digest = digest(read_bytes(Path(resolver_path)))
        java = shutil.which("java", path=environment.get("PATH"))
        if not java:
            raise DependencyError("java-pinned-resolution-jdk-unavailable")
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
        result = run_bounded_result([resolver_path, "--no-daemon", "captureRuntime"], work, environment, 300, 4 * 1024 * 1024)
        if result.returncode:
            raise DependencyError("java-maven-resolution-failed-private-diagnostics-discarded")
        resolved = document(work / "resolved.json")
        if len(resolved["graph"]) > 1024 or len(resolved["artifacts"]) > 1024:
            raise DependencyError("java-dependency-graph-limit")
        graph = {row["id"]: row for row in resolved["graph"]}
        jar_ids = {row["id"] for row in resolved["artifacts"]}
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
                "source": {"path": store.path(identity["digest"]).relative_to(project).as_posix()},
                "dependencies": [], "metadata": {"ecosystem": "maven", "assetType": "maven-resolution-metadata", "coordinates": coordinate}})
        artifacts, identities = [], {}
        for index, row in enumerate(sorted(resolved["artifacts"], key=lambda row: row["id"])):
            if row["type"] != "jar" or row["classifier"] is not None:
                raise DependencyError("java-selected-artifact-type-unsupported")
            path = regular_path(Path(row["file"]))
            if not path.is_relative_to(work):
                raise DependencyError("java-resolver-artifact-escape")
            identity = store.put(read_bytes(path))
            source = store.path(identity["digest"]).relative_to(project).as_posix()
            component = graph[row["id"]]
            edges = sorted({edge["selected"] if edge["selected"] in jar_ids else primary_metadata.get(edge["selected"], edge["selected"])
                            for edge in component["dependencies"]})
            artifacts.append({"id": row["id"], "role": "application", "format": "file",
                "mount": f"dependencies/java/{index:04d}.jar", "source": {"path": source}, "dependencies": edges,
                "metadata": {"ecosystem": "maven", "coordinates": row["id"], "scope": "selected-runtime",
                             "resolution": component, "repositoryPolicy": [row["id"] for row in config["repositories"]]}})
            identities[row["id"]] = identity
        artifacts.extend(metadata_rows)
        for row in config["localJars"]:
            identity = store.put(read_bytes(regular_path(project / row["path"])))
            artifacts.append({"id": row["id"], "role": "application", "format": "file",
                "mount": f"dependencies/java/{len(artifacts):04d}.jar",
                "source": {"path": store.path(identity["digest"]).relative_to(project).as_posix()},
                "dependencies": row["dependencies"], "metadata": {"ecosystem": "captured-local-jar", "scope": "runtime"}})
            identities[row["id"]] = identity
        artifacts = capture_resources(project, store, artifacts)
        if read_bytes(project / DECLARATIONS) != declaration_bytes or digest(read_bytes(Path(resolver_path))) != resolver_digest:
            raise DependencyError("java-resolution-input-mutated")
        native = {"formatVersion": 1, "resolver": {"name": "gradle", "version": pins["sdk"]["gradle"],
                  "executableDigest": resolver_digest, "jdkVersion": pins["sdk"]["java"], "jdkExecutableDigest": digest(read_bytes(Path(java)))}, "graph": list(graph.values()),
                  "artifacts": identities, "configurationDigest": digest(read_bytes(project / DECLARATIONS)),
                  "selection": config["selection"], "lifecycleScripts": "disabled"}
        (project / RESOLUTION).write_bytes(canonical(native) + b"\n")
        manifest = {"formatVersion": 1, "language": "java", "selection": config["selection"],
                    "nativeLocks": [DECLARATIONS, RESOLUTION], "artifacts": artifacts, "transformations": []}
        (project / MANIFEST).write_bytes(canonical(manifest) + b"\n")
        lock = capture(project)
        with candidate.open("xb") as stream:
            stream.write(canonical(lock) + b"\n")
        return lock
