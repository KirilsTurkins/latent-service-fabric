from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile


SDK = Path(__file__).resolve().parents[1]
ROOT = SDK.parents[1]


def run(command, *, cwd=None, environment=None, log=None, timeout=300):
    if log is None:
        subprocess.run(command, cwd=cwd, env=environment, check=True, timeout=timeout)
    else:
        with log.open("ab") as output:
            result = subprocess.run(command, cwd=cwd, env=environment, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f"build command failed; inspect {log}")


def download(directory, name, item):
    path = directory / name
    if not path.exists():
        request = urllib.request.Request(item["url"], headers={"User-Agent": "latent-c-sdk-build"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise RuntimeError(f"dependency integrity failure: {name}")
        path.write_bytes(data)
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise RuntimeError(f"cached dependency integrity failure: {name}")
    return path


def unpack(archive, destination, zipped=False):
    destination.mkdir(parents=True, exist_ok=True)
    if zipped:
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                target = (destination / entry.filename).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise RuntimeError("invalid dependency archive path")
            source.extractall(destination)
    else:
        with tarfile.open(archive) as source:
            source.extractall(destination, filter="data")


def prepare(build):
    deps = build / "deps"
    deps.mkdir(parents=True, exist_ok=True)
    python = build / "python"
    python.mkdir(exist_ok=True)
    lock = json.loads((SDK / "dependencies.lock.json").read_text())
    for name, item in lock.items():
        archive = download(deps, name + ".download", item)
        if item["url"].endswith(".whl"):
            unpack(archive, python, zipped=True)
        elif name == "protoc":
            unpack(archive, deps / "protoc", zipped=True)
            (deps / "protoc/bin/protoc").chmod(0o755)
        elif not (deps / name).exists():
            unpack(archive, deps / name)
    nanopb = next((deps / "nanopb").glob("nanopb-*"))
    nghttp2 = next((deps / "nghttp2").glob("nghttp2-*"))
    for component in lock["nghttp2"].get("bundled", []):
        for name, expected in component["files"].items():
            if hashlib.sha256((nghttp2 / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"bundled dependency integrity failure: {name}")
    environment = dict(os.environ, PYTHONPATH=str(python),
                       PATH=str(deps / "protoc/bin") + os.pathsep + os.environ["PATH"])
    return nanopb, nghttp2, environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path, default=ROOT / "target/c-sdk")
    parser.add_argument("--sanitize", action="store_true")
    parser.add_argument("--deps-only", action="store_true")
    parser.add_argument("--check-generated", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("supported build profile is Linux x86_64")
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    nanopb, nghttp2, environment = prepare(build)
    if args.deps_only:
        print(f"C dependencies verified in {build}")
        return
    sanitizers = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie"] if args.sanitize else []
    flags = ["-std=c11", "-O1" if args.sanitize else "-O2", "-g", "-fPIC", *sanitizers]
    compiler = os.environ.get("CC", "cc")
    marker = nghttp2 / ".latent-build-flags"
    selected = " ".join([compiler, *flags])
    if not marker.exists() or marker.read_text() != selected:
        configure_env = dict(environment, CC=compiler, CFLAGS=" ".join(flags),
                             LDFLAGS=" ".join(sanitizers + (["-no-pie"] if args.sanitize else [])))
        run([str(nghttp2 / "configure"), "--enable-lib-only", "--disable-shared", "--enable-static"],
            cwd=nghttp2, environment=configure_env, log=build / "dependency-build.log")
        run(["make", "-j2", "-C", "lib"], cwd=nghttp2, environment=configure_env,
            log=build / "dependency-build.log")
        marker.write_text(selected)
    generated = build / "generated"
    command = [sys.executable, str(SDK / "tools/generate.py"), "--build-dir", str(build)]
    if args.check_generated:
        command.append("--check")
    run(command, environment=environment)
    objects = build / "objects"
    objects.mkdir(exist_ok=True)
    include = [SDK / "include", SDK / "src", generated, nanopb,
               nghttp2 / "lib/includes", nghttp2 / "lib"]
    common = [*flags, "-D_POSIX_C_SOURCE=200809L", "-DPB_MESSAGE_NESTING_MAX=16",
              "-Wall", "-Wextra", "-Werror", "-Wpedantic"]
    for directory in include:
        common.extend(["-I", str(directory)])
    sources = [*sorted((SDK / "src").glob("*.c")),
               *sorted(generated.rglob("*.pb.c")), generated / "wire_generated.c",
               *(nanopb / name for name in ("pb_common.c", "pb_encode.c", "pb_decode.c"))]
    compiled = []
    for index, source in enumerate(sources):
        target = objects / f"{index}-{source.stem}.o"
        run([compiler, *common, "-c", str(source), "-o", str(target)], environment=environment)
        compiled.append(str(target))
    library = build / "liblatent.a"
    if library.exists():
        library.unlink()
    run(["ar", "rcs", str(library), *compiled])
    native = nghttp2 / "lib/.libs/libnghttp2.a"
    shutil.copy2(native, build / "libnghttp2.a")
    programs = {
        "semantic-tests": SDK / "tests/profile_semantics.c",
        "transport-tests": SDK / "tests/transport.c",
        "wire-tests": generated / "wire_vectors.c",
        "owner-bounds": SDK / "tests/owner_bounds.c",
        "private-config-tests": SDK / "tests/private_config.c",
        "provider-workflow": SDK / "examples/provider_workflow.c",
        "provider-client": SDK / "examples/provider_client.c",
    }
    for name, source in programs.items():
        if source.exists():
            support = [str(SDK / "examples/common.c"), str(SDK / "examples/private_config.c")] if name.startswith("provider-") or name == "private-config-tests" else []
            run([compiler, *common, str(source), *support, str(library), str(native),
                 *(["-no-pie"] if args.sanitize else []), "-o", str(build / name)], environment=environment)
    lock = json.loads((SDK / "dependencies.lock.json").read_text())
    (build / "build.json").write_text(json.dumps({"sanitize": args.sanitize,
                                                  "compiler": compiler,
                                                  "dependencies": lock}, indent=2) + "\n")
    print(f"C SDK built: {library}")


if __name__ == "__main__":
    main()
