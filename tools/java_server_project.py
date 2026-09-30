"""Create an ordinary-source Java server project with an explicit finite profile."""
from __future__ import annotations

import json
from pathlib import Path

from tools.java_capsule_project import ROOT, create, runtime_wit
from tools.java_server_source import PROFILE_ID
from tools.rust_capsule_project import canonical, digest, read_file


def create_server(directory: Path, name: str | None = None) -> Path:
    directory = create(directory, "greeting", name or "my-server")
    # This file belongs to the just-created template, before any developer edits.
    (directory / "src/dev/latent/app/Capsule.java").unlink()
    source = read_file(ROOT / "sdk/java-guest/server/templates/Server.java")
    wit = runtime_wit(read_file(ROOT / "wit/platform/web/package.wit"), "application-service")
    (directory / "src/dev/latent/app/Server.java").write_bytes(source)
    (directory / "wit/world.wit").write_bytes(wit)
    project = json.loads((directory / "capsule-project.json").read_bytes())
    project.update(world="latent:web/application-service@0.1.0", server={"profile": PROFILE_ID, "entryPoint": "dev.latent.app.Server"})
    (directory / "capsule-project.json").write_bytes(canonical(project) + b"\n")
    lock = json.loads((directory / "sdk-lock.json").read_bytes())
    lock["template"] = {"name": "httpserver", "sourceDigest": digest(source), "witDigest": digest(wit)}
    (directory / "sdk-lock.json").write_bytes(canonical(lock) + b"\n")
    (directory / "README.md").write_text(f"# {project['name']}\n\n"
        "Edit the ordinary `src/dev/latent/app/Server.java` and source helpers. "
        "The selected `lsf.java.httpserver.buffered.v1` compiler profile generates the invocation bridge.\n\n"
        "Build with `tools/java_capsule.py build` and the captured offline compiler cache. "
        "Inspect `server-source.json` and `server-profile.json`, then explicitly select hostname, methods and an "
        "equivalent enclosing mount using `tools/server_capsule.py`. These files grant no listener or catalog authority.\n\n"
        "See `docs/component-development/java-httpserver.md` for the precise member/lifecycle boundary, "
        "current qualification evidence and deployment workflow. Keep the captured SDK unchanged.\n", encoding="utf-8")
    return directory
