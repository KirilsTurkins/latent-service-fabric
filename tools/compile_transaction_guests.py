#!/usr/bin/env python3
"""Build authored transaction guests with the maintained language compilers.

The positive aggregate and actual forbidden-HTTP variant retain independent
captured projects, SDK locks, components and bounded failure diagnostics.
These receipts establish compilation, not signing, admission or node execution.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tomllib

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.java_guest.surface import surface
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot, write_json
from tools.transaction_guest_project import TEMPLATE
from tools.transaction_guest_variants import CHILD, HTTP, LANGUAGES, SOURCES, create as variant_project

WORLD = "examples:transactional-aggregate/service@1.0.0"
VARIANTS = ("aggregate", "forbidden-http", "result-boundary")
JAVA_SCHEMA_VARIANTS = ("put-once-legacy-v1", "put-once-compatible-v2", "put-once-writer-v2")
JAVA_DIAGNOSTIC_VARIANT = "put-once-diagnostics"
JAVA_ACCEPTANCE_VARIANTS = ("put-once-values", "forbidden-child")
JAVA_EARLY_HTTP_VARIANT = 'forbidden-http-before-stage'


def authored_project(language: str, variant: str, output: Path, *, java_current_http_profile: str | None = None) -> Path:
    if java_current_http_profile is not None and language != "java":
        raise ValueError("current HTTP source profile requires explicit Java compilation")
    if variant == JAVA_EARLY_HTTP_VARIANT:
        if language != 'java' or java_current_http_profile is not None:
            raise ValueError('early HTTP denial requires a separate explicit Java source without effect profile')
        from tools.java_transaction_http_denial import create
        return create(output)
    if variant in JAVA_ACCEPTANCE_VARIANTS:
        if language != "java":
            raise ValueError("Java state value and child-refusal inputs require the Java compiler")
        if variant == "forbidden-child":
            return variant_project(output, language, variant)
        from tools.java_transaction_values import create
        return create(output, http_profile=java_current_http_profile)
    if variant == JAVA_DIAGNOSTIC_VARIANT:
        if language != "java":
            raise ValueError("Java post-stage diagnostics require the Java compiler")
        from tools.java_transaction_diagnostics import create
        return create(output, http_profile=java_current_http_profile)
    if variant in JAVA_SCHEMA_VARIANTS:
        if language != "java":
            raise ValueError("Java schema qualification requires the Java compiler")
        from tools.java_transaction_schema import create
        return create(output, variant.removeprefix("put-once-"),
                      effect="current-http" if java_current_http_profile is not None else "put-once",
                      http_profile=java_current_http_profile)
    if variant in {"forbidden-http", "result-boundary"}:
        name = "transaction-rust-aggregate" if variant == "result-boundary" else None
        return variant_project(output, language, variant, name)
    if variant != "aggregate":
        raise ValueError("unknown authored transaction variant")
    if language == "rust":
        from tools.rust_capsule_project import create
    elif language == "c":
        from tools.c_capsule_project import create
    elif language == "typescript":
        from tools.typescript_guest.project import create
    elif language == "go":
        from tools.go_capsule_project import create
    elif language == "java":
        from tools.java_capsule_project import create
    elif language == "dotnet":
        from tools.dotnet_guest.project import create
    else:
        raise ValueError("unknown transaction guest language")
    return create(output, TEMPLATE, "transaction-" + language + "-aggregate")


def check_surface(expected: dict, actual: dict, variant: str) -> None:
    if variant not in (*VARIANTS, "forbidden-child") or actual["exports"] != expected["exports"]:
        raise ValueError("authored transaction export or variant changed")
    mandatory = {"latent:state/key-value@0.2.0", "latent:intents/staging@0.1.0"}
    if not mandatory <= actual["imports"].keys() or (HTTP in actual["imports"]) != (variant == "forbidden-http"):
        raise ValueError("authored transaction or forbidden effect import missing")
    if (CHILD in actual["imports"]) != (variant == "forbidden-child"):
        raise ValueError("actual forbidden synchronous child call missing or unexpected")
    for name, imported in actual["imports"].items():
        declared = expected["imports"].get(name)
        if declared is None:
            raise ValueError("undeclared runtime or application authority survived compilation")
        # Native dead-code elimination can omit unused operations/types. Every
        # retained function and canonical owner must preserve its exact shape.
        for category in ("types", "functions"):
            if any(declared[category].get(key) != value for key, value in imported[category].items()):
                raise ValueError("authored transaction nominal type or async signature changed")
    if variant == "forbidden-http" and actual["imports"][HTTP]["functions"].get("send") != expected["imports"][HTTP]["functions"]["send"]:
        raise ValueError("actual forbidden asynchronous HTTP call missing")


def compile_project(language: str, work: Path, output: Path, command: Commands,
                    *, tools: Path | None, wasi_sdk: Path | None,
                    java_read_only_cache: Path | None = None) -> tuple[Path, dict]:
    vendor = work / "vendor/lsf"
    pins = (json.loads(read_file(work / "sdk-lock.json"))["toolchain"] if language == "rust"
            else tomllib.loads(read_file(vendor / "tools/toolchain.toml").decode()))
    if language == "rust":
        selected, materials = resolve_tools(pins, work, command.environment)
        command.environment["RUSTC"] = str(selected["rustc"])
        for name in ("cargo", "rustc"):
            if command.run(name + "-version", selected[name], "--version").split()[:2] != [name.encode(), b"1.97.1"]:
                raise ValueError("unreviewed authored Rust compiler:" + name)
        bindgen = Path(shutil.which("wit-bindgen", path=command.environment["PATH"]) or "missing-wit-bindgen").resolve(strict=True)
        if command.run("bindgen-version", bindgen, "--version").strip() != b"wit-bindgen-cli 0.62.0":
            raise ValueError("unreviewed authored Rust binding generator")
        binding_identity = file_identity(bindgen, "wit-bindgen")
        for name in ("bindings", "bindings-check"):
            command.run(name, bindgen, "rust", work / "wit", "--world", WORLD, "--generate-all", "--out-dir", output / name)
        bindings = snapshot(output / "bindings")
        if bindings != snapshot(output / "bindings-check"):
            raise ValueError("authored Rust binding drift")
        command.run("actual-authored-rust", selected["cargo"], "build", "--locked", "--release", "--lib", "--target", "wasm32-unknown-unknown")
        target = Path(command.environment.get("CARGO_TARGET_DIR", work / "target"))
        name = json.loads(read_file(work / "capsule-project.json"))["name"].replace("-", "_")
        component = output / "component.wasm"
        command.run("compose", selected["wasm-tools"], "component", "new", target / ("wasm32-unknown-unknown/release/" + name + ".wasm"), "-o", component)
        for material in materials:
            if file_identity(selected[material["name"]], material["name"]) != material:
                raise ValueError("authored Rust compiler changed during the build")
        if file_identity(bindgen, "wit-bindgen") != binding_identity:
            raise ValueError("authored Rust binding generator changed during the build")
        return component, {"tools": [*materials, binding_identity], "bindings": json.loads(inventory(bindings))}
    if language == "c":
        from tools.c_guest.compiler import Compiler
        compiler = Compiler(output / "compiler", 900, sdk=vendor / "sdk/c-guest", platform=None, config=pins, commands=command)
        component, binding = compiler.compile([work / SOURCES[language]], work / "wit", WORLD, output / "compiled")
        from tools.c_guest.bindings import generate
        _, second = generate(compiler.run, work / "wit", WORLD, output / "bindings-check", platform=None)
        if second != binding:
            raise ValueError("authored C binding drift")
    elif language == "java":
        from tools.java_guest.compiler import Compiler
        if wasi_sdk is None:
            raise ValueError("authored Java requires its pinned --wasi-sdk")
        cache_selection = {} if java_read_only_cache is None else {"read_only_cache": java_read_only_cache}
        compiler = Compiler(output / "compiler", wasi_sdk, sdk=vendor / "sdk/java-guest",
                            platform=vendor / "wit/platform", config=pins, **cache_selection)
        component, binding = compiler.compile(work / "src", work / "wit", WORLD, output / "compiled")
        (output / "compiler-inputs.json").write_bytes(compiler.compiler_inputs)
    elif language == "go":
        from tools.go_guest.compiler import Compiler
        compiler = Compiler(output / "compiler", vendor / "sdk/go-guest", command)
        component, binding = compiler.compile(work / "src", work / "wit", WORLD, output / "compiled")
    else:
        if tools is None:
            raise ValueError("authored managed guest requires --tools")
        if language == "typescript":
            from tools.typescript_guest.compiler import Compiler
            compiler = Compiler(tools, command, {name: read_file(vendor / "sdk/typescript-guest/tools" / name) for name in ("package.json", "package-lock.json")})
        elif language == "dotnet":
            from tools.dotnet_guest.compiler import Compiler
            compiler = Compiler(tools, command, vendor)
        else:
            raise ValueError("unknown transaction guest language")
        component, binding = compiler.compile(work, WORLD, output / "compiled")
    compiler.check_unchanged()
    details = {"bindings": binding}
    if hasattr(compiler, "materials"):
        details["tools"] = compiler.materials
    if hasattr(compiler, "records"):
        details["commands"] = compiler.records
    if hasattr(compiler, "before"):
        details["compilerClosureDigest"] = digest(json.dumps(compiler.before, sort_keys=True, separators=(",", ":")).encode())
    return component, details


def compile_guests(language: str, output: Path, *, tools: Path | None = None, wasi_sdk: Path | None = None,
                   java_schema_put_once: bool = False, java_post_stage_diagnostic: bool = False,
                   java_state_acceptance: bool = False, java_current_http_profile: str | None = None,
                   java_read_only_cache: Path | None = None, java_early_http_denial: bool = False) -> None:
    if type(java_early_http_denial) is not bool or (java_early_http_denial and
            (language != 'java' or java_schema_put_once or java_post_stage_diagnostic
             or java_state_acceptance or java_current_http_profile is not None)):
        raise ValueError('early HTTP denial requires the exclusive explicit Java compiler selection')
    if type(java_schema_put_once) is not bool or (java_schema_put_once and language != "java"):
        raise ValueError("Java schema qualification requires an explicit Java compiler selection")
    if (type(java_post_stage_diagnostic) is not bool
            or (java_post_stage_diagnostic and (language != "java" or java_schema_put_once))):
        raise ValueError("post-stage diagnostic qualification requires the exclusive explicit Java compiler")
    if type(java_state_acceptance) is not bool or (java_state_acceptance and
            (language != "java" or java_schema_put_once or java_post_stage_diagnostic)):
        raise ValueError("state acceptance inputs require the exclusive explicit Java compiler selection")
    if java_current_http_profile is not None:
        import re
        if (language != "java" or not (java_schema_put_once or java_post_stage_diagnostic or java_state_acceptance)
                or not isinstance(java_current_http_profile, str)
                or re.fullmatch(r"qualified-http-v1:[0-9a-f]{64}", java_current_http_profile) is None):
            raise ValueError("current HTTP profile requires a bounded explicit Java schema, diagnostic or value selection")
    if java_read_only_cache is not None and (
            language != "java" or not isinstance(java_read_only_cache, Path)
            or not java_read_only_cache.is_absolute() or not java_read_only_cache.is_dir()
            or java_read_only_cache.is_symlink()):
        raise ValueError("read-only Java cache requires an existing explicit absolute directory and Java compiler")
    output = fresh(output)
    variants = ((JAVA_EARLY_HTTP_VARIANT,) if java_early_http_denial else JAVA_ACCEPTANCE_VARIANTS if java_state_acceptance else (JAVA_DIAGNOSTIC_VARIANT,) if java_post_stage_diagnostic
                else (*VARIANTS, *JAVA_SCHEMA_VARIANTS) if java_schema_put_once else VARIANTS)
    for variant in variants:
        if variant == "result-boundary" and language != "rust":
            continue
        current = fresh(output / variant)
        report = {"schemaVersion": "latent.transaction-guest.compiler.v1", "language": language,
            "variant": variant, "evidenceKind": "authored-component-compiler", "status": "running",
            "compiled": False, "signedNodeExecutionQualified": False, "admissionRejectionQualified": False,
            "world": WORLD, "hostAbiDigest": json.loads(read_file(ROOT / "wit/host-abi-phase4-v1.json"))["digest"]}
        command = None
        try:
            work = authored_project(language, variant, current / "project", **(
                {} if java_current_http_profile is None else {"java_current_http_profile": java_current_http_profile}))
            captured = snapshot(work)
            source = inventory(captured)
            (current / "source-inputs.json").write_bytes(source)
            report["sourceDigest"] = digest(source)
            from tools.transaction_guest_project import CURRENT_HTTP_PROFILE
            if CURRENT_HTTP_PROFILE in captured:
                report.update(nativeEffectProfile="current-v2-http", nativeEffectOperation="http",
                              currentHttpProfileInputDigest=digest(captured[CURRENT_HTTP_PROFILE]))
            owner = {"rust": "tools.rust_capsule_build", "c": "tools.c_capsule_build", "typescript": "tools.typescript_guest.build",
                     "go": "tools.go_capsule_build", "java": "tools.java_capsule_build", "dotnet": "tools.dotnet_guest.build"}[language]
            import importlib
            recipe = (*importlib.import_module(owner).RECIPE, "tools/compile_transaction_guests.py", "tools/transaction_guest_variants.py")
            if variant in JAVA_SCHEMA_VARIANTS or variant in {JAVA_DIAGNOSTIC_VARIANT, "put-once-values"}:
                recipe += ("tools/java_transaction_schema.py", "examples/java-transaction-schema/AggregateCodec.java",
                           "contracts/state/application-aggregate-v1.schema.json",
                           "contracts/state/application-aggregate-v2.schema.json")
                report.update(applicationVariant=variant.removeprefix("put-once-"),
                              effect="current-http" if CURRENT_HTTP_PROFILE in captured else "put-once",
                              applicationSchemaInputDigest=digest(captured["application-schema-inputs.json"]),
                              deferredHttpRequirementsDigest=digest(captured["deferred-http-requirements.json"]))
            if variant == JAVA_DIAGNOSTIC_VARIANT:
                recipe += ("tools/java_transaction_diagnostics.py", "examples/java-transaction-schema/TransactionDiagnostics.java")
                report["diagnosticInputDigest"] = digest(captured["transaction-diagnostic-inputs.json"])
            if variant == "put-once-values":
                recipe += ("tools/java_transaction_values.py",)
                report["valueInputDigest"] = digest(captured["transaction-value-inputs.json"])
            if variant == JAVA_EARLY_HTTP_VARIANT:
                recipe += ('tools/java_transaction_http_denial.py',)
                report['earlyHttpDenialInputDigest'] = digest(captured['java-early-http-denial-input.json'])
                report['immediateHttpDenialQualified'] = False
                report['postStageRollbackQualified'] = False
            recipe_inputs = inventory({name: read_file(ROOT / name) for name in recipe})
            (current / "recipe-inputs.json").write_bytes(recipe_inputs)
            report["recipeDigest"] = digest(recipe_inputs)
            archive = current / "source.tar.gz"
            with archive.open("xb") as retained, gzip.GzipFile(fileobj=retained, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as source_archive:
                    for name, raw in captured.items():
                        entry = tarfile.TarInfo(name)
                        entry.size, entry.mode = len(raw), 0o644
                        source_archive.addfile(entry, io.BytesIO(raw))
            report["sourceArchiveDigest"] = digest(read_file(archive, 32 * 1024 * 1024))
            report["companionDigest"] = digest(captured["transaction-binding.json"])
            command = Commands(work, current, build_environment(current), deadline_seconds=900)
            report["sourceRevision"] = command.run("source-revision", "git", "-C", ROOT, "rev-parse", "HEAD").decode().strip()
            report["workingTreeChanged"] = bool(command.run("source-status", "git", "-C", ROOT, "status", "--porcelain", "--untracked-files=normal").strip())
            # CARGO_TARGET_DIR is intentionally owner-local and shared by these
            # two authored guest projects, not the workspace or another session.
            command.environment["CARGO_TARGET_DIR"] = str(output / "rust-target")
            wasm = Path(shutil.which("wasm-tools", path=command.environment["PATH"]) or "missing-wasm-tools").resolve(strict=True)
            if command.run("validator-version", wasm, "--version").split()[:2] != [b"wasm-tools", b"1.254.0"]:
                raise ValueError("unreviewed authored guest validator")
            expected = surface(json.loads(command.run("authored-wit", wasm, "component", "wit", work / "wit", "--json")), WORLD)
            cache_selection = {} if java_read_only_cache is None else {"java_read_only_cache": java_read_only_cache}
            component, details = compile_project(language, work, current, command,
                                                 tools=tools, wasi_sdk=wasi_sdk, **cache_selection)
            command.run("validate-authored-component", wasm, "validate", "--features", "all", component)
            actual = surface(json.loads(command.run("actual-component-wit", wasm, "component", "wit", component, "--json")))
            check_surface(expected, actual, "aggregate" if variant in JAVA_SCHEMA_VARIANTS
                          or variant in {JAVA_DIAGNOSTIC_VARIANT, "put-once-values"}
                          else 'forbidden-http' if variant == JAVA_EARLY_HTTP_VARIANT else variant)
            if any(read_file(work / name) != raw for name, raw in captured.items()):
                raise ValueError("captured guest source changed during compilation")
            if inventory({name: read_file(ROOT / name) for name in recipe}) != recipe_inputs:
                raise ValueError("authored compiler recipe changed during compilation")
            (current / "component.wit").write_bytes(command.run("retained-component-wit", wasm, "component", "wit", component))
            report.update(status="compiled", compiled=True, componentDigest=digest(read_file(component, 64 * 1024 * 1024)),
                          componentBytes=component.stat().st_size, actualImports=sorted(actual["imports"]), details=details)
        except BaseException as error:
            report.update(status="failed", reason=str(error))
            raise
        finally:
            if command is not None:
                report["commands"] = command.records
            write_json(current / "report.json", report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True, choices=LANGUAGES)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tools", type=Path)
    parser.add_argument("--wasi-sdk", type=Path)
    parser.add_argument("--java-schema-put-once", action="store_true",
                        help="also compile all three captured Java schema/deferred-HTTP variants without node-execution claims")
    parser.add_argument("--java-post-stage-diagnostic", action="store_true",
                        help="compile only the separate captured Java post-stage fault variant without node-execution claims")
    parser.add_argument("--java-state-acceptance", action="store_true",
                        help="compile separate unsigned-value/UTF-8 state and typed forbidden-child inputs")
    parser.add_argument('--java-early-http-denial', action='store_true',
                        help='compile only the separate typed HTTP denial before state/intent staging; no execution claim')
    parser.add_argument("--java-current-http-profile",
                        help="exact constructor-derived native HTTP profile for fresh Java captures; never an approval")
    parser.add_argument("--java-read-only-cache", type=Path,
                        help="existing pinned Java compiler cache; verify through the current read-only cache owner")
    arguments = parser.parse_args()
    compile_guests(arguments.language, arguments.output, tools=arguments.tools, wasi_sdk=arguments.wasi_sdk,
                   java_schema_put_once=arguments.java_schema_put_once,
                   java_post_stage_diagnostic=arguments.java_post_stage_diagnostic,
                   java_state_acceptance=arguments.java_state_acceptance,
                   java_current_http_profile=arguments.java_current_http_profile,
                   java_read_only_cache=arguments.java_read_only_cache,
                   java_early_http_denial=arguments.java_early_http_denial)


if __name__ == "__main__":
    main()
