import hashlib
import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SDK = ROOT / "sdk/java-client"
MAVEN = "https://repo.maven.apache.org/maven2/"
COORDINATES = [
    *(f"io.grpc:{artifact}:1.84.0" for artifact in (
        "grpc-api", "grpc-core", "grpc-context", "grpc-util", "grpc-stub",
        "grpc-protobuf", "grpc-protobuf-lite", "grpc-netty-shaded")),
    "com.google.protobuf:protobuf-java:3.25.9",
    "com.google.api.grpc:proto-google-common-protos:2.64.1",
    "com.google.guava:guava:33.6.0-android",
    "com.google.guava:failureaccess:1.0.3",
    "com.google.guava:listenablefuture:9999.0-empty-to-avoid-conflict-with-guava",
    "com.google.code.gson:gson:2.14.0",
    "com.google.code.findbugs:jsr305:3.0.2",
    "com.google.errorprone:error_prone_annotations:2.50.0",
    "com.google.j2objc:j2objc-annotations:3.1",
    "com.google.android:annotations:4.1.1.4",
    "org.codehaus.mojo:animal-sniffer-annotations:1.27",
    "org.jspecify:jspecify:1.0.0",
    "io.perfmark:perfmark-api:0.27.0",
    "javax.annotation:javax.annotation-api:1.3.2",
]


def entry(coordinate, classifier=None):
    group, artifact, version = coordinate.split(":")
    suffix = f"-{classifier}.exe" if classifier else ".jar"
    filename = f"{artifact}-{version}{suffix}"
    location = f"{group.replace('.', '/')}/{artifact}/{version}/{filename}"
    with urllib.request.urlopen(MAVEN + location, timeout=30) as response:
        content = response.read(64 * 1024 * 1024 + 1)
    if len(content) > 64 * 1024 * 1024:
        raise ValueError("dependency exceeds download bound")
    return {"path": location, "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content), "platform": classifier or "any"}


def main():
    entries = [entry(coordinate) for coordinate in COORDINATES]
    for platform in ("windows-x86_64", "linux-x86_64"):
        entries.append(entry("com.google.protobuf:protoc:3.25.9", platform))
        entries.append(entry("io.grpc:protoc-gen-grpc-java:1.84.0", platform))
    content = json.dumps({"schemaVersion": 1, "maven": MAVEN, "artifacts": entries}, indent=2) + "\n"
    path = "sdk/java-client/dependencies.lock.json"
    current = SDK / "dependencies.lock.json"
    print("*** Begin Patch")
    if current.exists():
        print(f"*** Update File: {path}\n@@")
        for line in current.read_text(encoding="utf-8").splitlines():
            print("-" + line)
    else:
        print(f"*** Add File: {path}")
    for line in content.splitlines():
        print("+" + line)
    print("*** End Patch")


if __name__ == "__main__":
    main()
