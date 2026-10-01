"""Observed finite C library source compilation under captured compiler isolation."""
from pathlib import Path
import tempfile

from tools.application_dependencies import prepare
from tools.build_observation import public_repository
from tools.build_process import BuildProcessError
from tools.c_application_dependencies import selected
from tools.c_guest.compiler import Compiler
from tools.c_capsule_project import validate
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, checked_path, digest, fresh, inventory, read_file, snapshot, write_json
from tools.build_observation import build_environment


def build(project_path: Path, output: Path, repository: str, *, installed=None) -> Path:
    """Build captured declared library sources; callers separately review and resolve its archive."""
    from tools.c_capsule_build import RECIPE
    project_path, output = checked_path(project_path), checked_path(output)
    if output == project_path or output in project_path.parents or (
            project_path in output.parents and project_path / "target" not in output.parents):
        raise ValueError("archive output must be outside source or beneath its target directory")
    repository = public_repository(repository)
    output, commands, stage = fresh(output), None, "capture"
    try:
        files = snapshot(project_path)
        _project, _lock, pins = validate(files)
        source_inputs = inventory(files)
        recipe_inputs = inventory({name: read_file(ROOT / name) for name in RECIPE})
        (output / "source-inputs.json").write_bytes(source_inputs)
        (output / "recipe-inputs.json").write_bytes(recipe_inputs)
        with tempfile.TemporaryDirectory(prefix="lsf-c-static-") as owned:
            temporary, work = Path(owned), Path(owned) / "project"
            for name, raw in files.items():
                path = work / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            commands = Commands(work, output, build_environment(temporary))
            stage = "application-dependencies"
            closure = prepare(project_path, work, output, "c")
            if closure is None:
                raise ValueError("C archive source recipe requires resolved application dependencies")
            stage = "captured-compiler-isolation"
            compiler = Compiler(temporary / "compiler", 900, sdk=work / "vendor/lsf/sdk/c-guest", platform=None,
                                config=pins, commands=commands, installed=installed)
            isolation = compiler.enable_captured_isolation(temporary)
            import json
            application = selected(closure, compiler_digest=compiler.materials["zig"]["digest"],
                runtime_digest=digest(inventory(snapshot(compiler.sdk))),
                compiler_distribution_digest=digest(json.dumps(isolation["distributions"],
                    sort_keys=True, separators=(",", ":")).encode()))
            if application.archives or not application.sources:
                raise ValueError("C archive source recipe requires captured sources without prebuilt archives")
            write_json(output / "c-libraries.json", application.receipt)
            stage = "compile-static-archive"
            archive, profile = compiler.compile_static_archive(application.sources, temporary / "compiled",
                include_directories=application.includes, defines=application.defines)
            raw = read_file(archive, 64 * 1024 * 1024)
            (output / "library.a").write_bytes(raw)
            write_json(output / "archive-profile.json", profile)
            write_json(output / "compiler-inputs.json", isolation)
            stage = "final-integrity"
            if snapshot(project_path) != files or snapshot(work, exclude=("dependencies", "application-vendor")) != files:
                raise ValueError("C archive project changed during compilation")
            closure.check_unchanged()
            compiler.check_unchanged()
            if inventory({name: read_file(ROOT / name) for name in RECIPE}) != recipe_inputs:
                raise ValueError("C archive recipe changed during compilation")
            write_json(output / "STATIC-ARCHIVE-COMPLETE.json", {"formatVersion": 1,
                "source": {"repository": repository, "snapshotDigest": digest(source_inputs),
                           "repositoryTrust": "operator-asserted"},
                "recipeDigest": digest(recipe_inputs), "archiveDigest": digest(raw), "archiveSize": len(raw),
                "profileDigest": digest(read_file(output / "archive-profile.json")),
                "applicationClosureDigest": digest(read_file(output / "application-dependencies.json", 8 * 1024 * 1024)),
                "compilerInputsDigest": digest(read_file(output / "compiler-inputs.json", 8 * 1024 * 1024)),
                "commands": commands.records, "guestExecution": False, "packageAssembled": False})
        return output
    except BaseException as error:
        write_json(output / "STATIC-ARCHIVE-FAILED.json", {"formatVersion": 1, "stage": stage,
            "reason": str(error) if isinstance(error, (ValueError, BuildProcessError)) else type(error).__name__,
            "commands": commands.records if commands else []})
        raise
