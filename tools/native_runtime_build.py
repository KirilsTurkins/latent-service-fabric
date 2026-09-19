"""Native release assembly from exact, observed Linux build outputs."""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import io
import os
from pathlib import Path
import re
import tarfile
import zipfile

from tools.native_runtime.common import document, encode, require
from tools.native_runtime import files, verify


def bootstrap(source: Path, epoch: int) -> bytes:
    output = io.BytesIO()
    stamp = datetime.fromtimestamp(max(epoch, 315532800), timezone.utc).timetuple()[:6]
    entries = {"__main__.py": b"from native_runtime.cli import main\nraise SystemExit(main())\n"}
    for path in sorted((source / "tools/native_runtime").glob("*.py")):
        require(not path.is_symlink(), "bootstrap-source-must-be-regular")
        with path.open("rb") as stream:
            data = stream.read(1_048_577)
        require(len(data) <= 1_048_576, "bootstrap-source-byte-limit")
        entries["native_runtime/" + path.name] = data
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(entries.items()):
            entry = zipfile.ZipInfo(name, date_time=stamp)
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    return output.getvalue()


def elf_identity(path: Path, run) -> list[str]:
    with files.regular(path) as descriptor:
        header = os.read(descriptor, 64)
    require(len(header) == 64 and header[:6] == b"\x7fELF\x02\x01" and header[18:20] == b"\x3e\x00",
            "prebuilt-linux-x86_64-elf-required")
    dynamic = run(["readelf", "--dynamic", str(path)], maximum=131072).decode()
    dependencies = sorted(set(re.findall(r"\(NEEDED\).*\[([^\]]+)\]", dynamic)))
    require("libc.so.6" in dependencies and "RPATH" not in dynamic and "RUNPATH" not in dynamic,
            "unexpected-native-linkage")
    symbols = run(["readelf", "--version-info", str(path)], maximum=262144).decode()
    versions = [tuple(map(int, match)) for match in re.findall(r"GLIBC_([0-9]+)\.([0-9]+)", symbols)]
    require(versions and max(versions) <= (2, 39), "glibc-symbol-floor-exceeds-supported-host")
    program = run(["readelf", "--program-headers", str(path)], maximum=65536)
    require(b"/lib64/ld-linux-x86-64.so.2" in program, "unsupported-native-interpreter")
    return dependencies


def shared_license(package: dict, packages: list[dict], checksums: dict, policy: dict) -> tuple[Path, dict]:
    require(policy.get("schemaVersion") == "latent.native-shared-license-sources.v1", "shared-license-source-policy-required")
    matches = [source for source in policy["sources"]
               if source["packages"].get(package["name"]) == package["version"]]
    require(len(matches) == 1, "dependency-license-text-missing-" + package["name"] + "-" + package["version"])
    source = matches[0]
    donors = [entry for entry in packages if entry["name"] == source["donor"]["name"]
              and entry["version"] == source["donor"]["version"]]
    require(len(donors) == 1, "shared-license-donor-missing")
    donor = donors[0]
    for entry in (package, donor):
        require(entry.get("repository", "").removesuffix(".git") == source["repository"]
                and entry.get("license") == source["license"]
                and checksums.get((entry["name"], entry["version"], entry.get("source"))), "shared-license-source-identity-mismatch")
        vcs = document(files.read(Path(entry["manifest_path"]).parent / ".cargo_vcs_info.json", 8192))
        require(vcs.get("git", {}).get("sha1") == source["sourceCommit"], "shared-license-exact-revision-required")
    name = verify.relative(source["donor"]["file"])
    require("/" not in name, "shared-license-root-file-required")
    path = Path(donor["manifest_path"]).parent / name
    require(files.digest(path) == source["sha256"], "shared-license-reviewed-root-digest-mismatch")
    return path, {"sourceUrl": source["sourceUrl"], "sha256": source["sha256"], "donor": source["donor"],
                  "donorCrateSha256": checksums[(donor["name"], donor["version"], donor["source"])]}


def dependency_inventory(metadata: dict, lock: dict, commit: str, epoch: int,
                         license_policy: dict) -> tuple[dict, dict[str, Path]]:
    packages = {entry["id"]: entry for entry in metadata["packages"]}
    roots = {entry["id"] for entry in metadata["packages"] if entry["name"] in {"latent", "latentd", "latent-wasmtime"}}
    nodes = {entry["id"]: entry for entry in metadata["resolve"]["nodes"]}
    selected = set()
    pending = list(roots)
    while pending:
        package = pending.pop()
        if package in selected:
            continue
        selected.add(package)
        pending.extend(entry["pkg"] for entry in nodes[package]["deps"]
                       if any(kind["kind"] is None for kind in entry["dep_kinds"]))
    checksums = {(entry["name"], entry["version"], entry.get("source")): entry.get("checksum")
                 for entry in lock["package"]}
    identifiers = {key: "SPDXRef-crate-" + hashlib.sha256(key.encode()).hexdigest()[:24] for key in selected}
    result = []
    relationships = []
    licenses = {}
    for key in sorted(selected):
        package = packages[key]
        checksum = checksums.get((package["name"], package["version"], package.get("source")))
        entry = {"SPDXID": identifiers[key], "name": package["name"], "versionInfo": package["version"],
                 "downloadLocation": f"https://crates.io/api/v1/crates/{package['name']}/{package['version']}/download"
                 if checksum else f"git+https://github.com/KirilsTurkins/latent-service-fabric@{commit}",
                 "filesAnalyzed": False, "licenseConcluded": "NOASSERTION",
                 "licenseDeclared": package.get("license") or "NOASSERTION", "copyrightText": "NOASSERTION"}
        if checksum:
            entry["checksums"] = [{"algorithm": "SHA256", "checksumValue": checksum}]
            directory = Path(package["manifest_path"]).parent
            candidates = {path for pattern in ("LICENSE*", "LICENCE*", "COPYING*", "NOTICE*")
                          for path in directory.glob(pattern) if path.is_file() and not path.is_symlink()}
            if package.get("license_file"):
                declared = Path(package["license_file"])
                declared = declared if declared.is_absolute() else directory / declared
                require(declared.resolve().is_relative_to(directory.resolve()), "license-outside-package")
                candidates.add(declared)
            if not candidates:
                shared, origin = shared_license(package, list(packages.values()), checksums, license_policy)
                candidates.add(shared)
                entry["comment"] = "Shared monorepo root license from the exact published revision: " + encode(origin).decode().strip()
            for path in sorted(candidates):
                name = f"licenses/{package['name']}-{package['version']}/{path.name}"
                verify.relative(name)
                licenses[name] = path
        result.append(entry)
        if key in roots:
            relationships.append({"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
                                  "relatedSpdxElement": identifiers[key]})
        for dependency in nodes[key]["deps"]:
            if dependency["pkg"] in selected and any(kind["kind"] is None for kind in dependency["dep_kinds"]):
                relationships.append({"spdxElementId": identifiers[key], "relationshipType": "DEPENDS_ON",
                                      "relatedSpdxElement": identifiers[dependency["pkg"]]})
    sbom = {"spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
            "name": "LSF native runtime dependency inventory",
            "documentNamespace": "https://github.com/KirilsTurkins/latent-service-fabric/native-sbom/" + commit,
            "creationInfo": {"creators": ["Tool: lsf-native-runtime-builder-v1"],
                             "created": datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "documentComment": "Resolved non-dev dependency closure of the three native release packages; includes build-time crates, not a static link map. System glibc/libgcc remain OS prerequisites.",
            "packages": result, "relationships": relationships}
    return sbom, licenses


def assemble(output: Path, source: Path, identity: dict, assets: dict[str, Path | bytes],
             compatibility: dict, provenance: dict, sbom: dict, epoch: int) -> dict:
    require(not output.exists(), "new-release-output-directory-required")
    output.mkdir(mode=0o700, parents=True)
    installer = bootstrap(source, epoch)
    assets = {**assets, "lsf-install.pyz": installer, "release-source.json": encode(identity),
              "build-provenance.json": encode(provenance), "sbom.spdx.json": encode(sbom)}
    inventory = []
    name = f"lsf-{identity['version']}-{verify.TARGET}.tar.gz"
    with (output / name).open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=epoch) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
            for path, value in sorted(assets.items()):
                verify.relative(path)
                mode = 0o755 if path in {"bin/latent", "bin/latentd", "bin/latent-aot-compiler"} else 0o644
                if isinstance(value, bytes):
                    payload = io.BytesIO(value)
                    size = len(value)
                    digest = hashlib.sha256(value).hexdigest()
                else:
                    require(value.is_file() and not value.is_symlink(), "build-artifact-not-regular")
                    size = value.stat().st_size
                    digest = files.digest(value)
                    payload = value.open("rb")
                require(size <= files.MAX_FILE, "build-artifact-byte-limit")
                with payload:
                    header = tarfile.TarInfo(path)
                    header.size = size
                    header.mode = mode
                    header.mtime = epoch
                    header.uid = header.gid = 0
                    header.uname = header.gname = "root"
                    archive.addfile(header, payload)
                inventory.append({"path": path, "size": size, "sha256": digest, "mode": mode})
    (output / "lsf-install.pyz").write_bytes(installer)
    manifest = {"schemaVersion": "latent.native-release.v1", "version": identity["version"],
                "sourceCommit": identity["sourceCommit"], "target": verify.TARGET,
                "toolchain": identity["toolchain"], "engine": identity["engine"], "platform": verify.PLATFORM,
                "compatibility": compatibility, "files": inventory,
                "archive": {"name": name, "sha256": files.digest(output / name), "size": (output / name).stat().st_size},
                "bootstrap": {"name": "lsf-install.pyz", "sha256": hashlib.sha256(installer).hexdigest(), "size": len(installer)}}
    verify.manifest(manifest, identity["version"])
    (output / "release.json").write_bytes(encode(manifest))
    sums = "".join(files.digest(output / path) + "  " + path + "\n"
                   for path in sorted((name, "lsf-install.pyz", "release.json")))
    (output / "SHA256SUMS").write_text(sums, encoding="ascii", newline="\n")
    return manifest
