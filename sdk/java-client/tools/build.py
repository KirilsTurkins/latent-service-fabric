import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from java_toolchain import baseline, check_jdk, executable, release, verify_classes, verify_jar


ROOT = Path(__file__).resolve().parents[3]
SDK = ROOT / "sdk/java-client"
BUILD = SDK / "build"


def jars():
    lock = json.loads((SDK / "dependencies.lock.json").read_text(encoding="utf-8"))
    return [BUILD / "deps" / Path(artifact["path"]).name for artifact in lock["artifacts"] if artifact["platform"] == "any"]


def run(command, timeout=90):
    subprocess.run([str(value) for value in command], cwd=ROOT, check=True, timeout=timeout)


def download_locked(url, artifact):
    # A setup GET can be repeated after a finite Maven throttle/server response.
    # Never retry an integrity mismatch or put partial/unverified bytes in cache.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                content = response.read(artifact["size"] + 1)
            break
        except urllib.error.HTTPError as error:
            retry_after = error.headers.get("Retry-After", "0") if error.headers else "0"
            error.close()
            if (attempt == 2 or error.code not in (429, 502, 503, 504)
                    or not retry_after.isascii() or not retry_after.isdigit()
                    or len(retry_after) > 2 or int(retry_after) > 10):
                raise
            time.sleep(max(1 << attempt, int(retry_after)))
        except (urllib.error.URLError, ConnectionResetError, TimeoutError) as error:
            reason = error.reason if isinstance(error, urllib.error.URLError) else error
            if attempt == 2 or not isinstance(reason, (ConnectionResetError, TimeoutError)):
                raise
            time.sleep(1 << attempt)
    if len(content) != artifact["size"] or hashlib.sha256(content).hexdigest() != artifact["sha256"]:
        raise ValueError("locked dependency download mismatch")
    return content


def prepare():
    selected = {"Windows": "windows-x86_64", "Linux": "linux-x86_64"}.get(platform.system())
    if selected is None or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ValueError("locked Java generation supports Windows/Linux x86-64")
    lock = json.loads((SDK / "dependencies.lock.json").read_text(encoding="utf-8"))
    dependencies = BUILD / "deps"
    dependencies.mkdir(parents=True, exist_ok=True)
    executables = {}
    for artifact in lock["artifacts"]:
        if artifact["platform"] not in ("any", selected):
            continue
        filename = Path(artifact["path"]).name
        destination = dependencies / filename
        if not destination.exists():
            destination.write_bytes(download_locked(lock["maven"] + artifact["path"], artifact))
        if destination.stat().st_size != artifact["size"] or hashlib.sha256(destination.read_bytes()).hexdigest() != artifact["sha256"]:
            raise ValueError("locked dependency cache mismatch")
        if artifact["platform"] != "any":
            destination.chmod(0o755)
            executables["grpc" if filename.startswith("protoc-gen") else "protoc"] = destination
    generated = BUILD / "generated/java"
    generated.mkdir(parents=True, exist_ok=True)
    profile = json.loads((ROOT / "sdk/profile/client-profile.json").read_text(encoding="utf-8"))
    sources = sorted(ROOT / path for path in profile["sources"])
    run([executables["protoc"], f"-I{ROOT / 'api/proto'}", f"--java_out={generated}",
         f"--plugin=protoc-gen-grpc-java={executables['grpc']}", f"--grpc-java_out={generated}", *sources])
    selected = []
    for source in sources:
        text = source.read_text(encoding="utf-8")
        package = re.search(r"package ([\w.]+);", text).group(1).replace(".", "/")
        outer = source.stem.title()
        if re.search(rf"\b(?:message|enum|service) {outer}\b", text):
            outer += "OuterClass"
        names = [outer] + [service + "Grpc" for service in re.findall(r"service (\w+)", text)]
        selected.extend(str(generated / package / (name + ".java")) for name in names)
    (BUILD / "generated-sources.json").write_text(json.dumps(selected), encoding="utf-8")
    run([sys.executable, SDK / "tools/generate_bridge.py", "--check"])


def compile_java(tests, java_home):
    classes = BUILD / ("test-classes" if tests else "classes")
    if classes.exists():
        resolved = classes.resolve(strict=True)
        if resolved.parent != BUILD.resolve(strict=True) or classes.is_symlink():
            raise ValueError("Java class output escaped its owned build directory")
        shutil.rmtree(resolved)
    classes.mkdir(parents=True, exist_ok=True)
    directories = [SDK / "src/main/java", SDK / "src/transport/java", SDK / "src/example/java"]
    if tests:
        directories.extend([SDK / "src/test/java", SDK / "src/transportTest/java"])
    sources = sorted(source for directory in directories for source in directory.rglob("*.java"))
    sources.extend(Path(path) for path in json.loads((BUILD / "generated-sources.json").read_text(encoding="utf-8")))
    classpath = os.pathsep.join(map(str, jars()))
    arguments = ["--release", str(release()), "-encoding", "UTF-8", "-d", str(classes), "-cp", classpath, *map(str, sources)]
    argument_file = BUILD / "javac.args"
    argument_file.write_text("\n".join(json.dumps(value.replace("\\", "/")) for value in arguments), encoding="utf-8")
    run([executable(java_home, "javac"), f"@{argument_file}"])
    count = verify_classes(classes)
    print(f"Verified {count} non-preview Java {release()} classes", flush=True)
    return os.pathsep.join([str(classes), classpath])


def main():
    parser = argparse.ArgumentParser(description="Locked Java protobuf generation, native build and bounded tests")
    parser.add_argument("action", choices=("prepare", "build", "test", "classpath"))
    args = parser.parse_args()
    if args.action == "classpath":
        print(os.pathsep.join(map(str, [BUILD / "classes", *jars()])))
        return
    if args.action == "prepare":
        prepare()
        return
    java_home = check_jdk()
    print(f"Java SDK: Temurin {baseline()['java']}, release {release()}, {platform.system()} {platform.machine()}", flush=True)
    prepare()
    classpath = compile_java(args.action == "test", java_home)
    if args.action == "test":
        run([executable(java_home, "java"), "-ea", "-cp", classpath, "dev.latent.sdk.InvocationIdentityTest"], 45)
        run([executable(java_home, "java"), "-ea", "-cp", classpath, "dev.latent.sdk.transport.TransportTest"], 60)
    else:
        manifest = BUILD / "manifest.mf"
        class_path = "Class-Path: " + " ".join("deps/" + path.name for path in jars())
        lines = ["Manifest-Version: 1.0", class_path[:70]]
        class_path = class_path[70:]
        while class_path:
            lines.append(" " + class_path[:69])
            class_path = class_path[69:]
        manifest.write_text("\n".join(lines) + "\n\n", encoding="utf-8")
        jar = BUILD / "latent-java-client.jar"
        run([executable(java_home, "jar"), "--create", "--date=2026-01-01T00:00:00Z", "--file", jar,
             "--manifest", manifest, "--main-class", "dev.latent.sdk.examples.ProviderWorkflow", "-C", BUILD / "classes", "."])
        count = verify_jar(jar)
        print(f"Verified JAR contains {count} non-preview Java {release()} classes", flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as failure:
        raise SystemExit(f"Java build/test command failed with exit {failure.returncode}") from None
    except subprocess.TimeoutExpired:
        raise SystemExit("Java build/test command exceeded its finite deadline") from None
    except (OSError, ValueError) as failure:
        raise SystemExit(f"Java build/test failed: {failure}") from None
