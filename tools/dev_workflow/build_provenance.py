"""Join the observed compiler output to the separate completed packaging step."""
from __future__ import annotations

from pathlib import Path
import time

from . import paths, state
from .common import decode, digest, encode, require


def complete(source: Path, descriptor: dict, cli: Path, expected_packager: str, package: dict) -> None:
    if "adapter" not in descriptor["build"]:
        return
    output = source / descriptor["build"]["outputRoot"]
    raw = paths.read(output, "build-observation.json", 32768)
    marker_raw = paths.read(output, "BUILD-COMPLETE.json", 65536)
    observation, marker = decode(raw), decode(marker_raw)
    component, size = paths.digest_file(source, descriptor["artifacts"]["component"], 64 * 1024 * 1024)
    require(marker.get("formatVersion") == 1 and marker.get("observationDigest") == digest(raw)
            and marker.get("packageAssembled") is False and marker.get("componentDigest") == component
            and observation.get("componentDigest") == component and observation.get("componentSize") == size,
            "compiler-observation-does-not-match-packaged-component")
    packager, packager_size = paths.digest_file(cli.parent, cli.name, 256 * 1024 * 1024)
    require(packager == expected_packager and package["componentDigest"] == component,
            "packager-changed-during-observed-packaging")
    materials = observation["materials"]
    require(isinstance(materials, list) and all(item.get("name") != "packager" for item in materials),
            "compiler-must-not-claim-controller-packaging")
    finished = int(time.time())
    require(observation["startedAt"] <= observation["finishedAt"] <= finished
            and finished - observation["startedAt"] <= 900, "controller-packaging-observation-clock")
    # Preserve the compiler's original unsigned statement verbatim. The joined
    # statement adds only the binary actually used by the completed public CLI
    # package operation. Neither statement grants admission or publisher trust.
    paths.write_new(output / "compiler-build-observation.json", raw)
    paths.write_new(output / "compiler-BUILD-COMPLETE.json", marker_raw)
    observation["materials"] = sorted([*materials, {"name": "packager", "digest": packager, "size": packager_size}],
                                      key=lambda item: item["name"])
    observation["finishedAt"] = finished
    state.atomic(output, "build-observation.json", observation)
    marker.update(observationDigest=digest(encode(observation)), packageAssembled=True)
    state.atomic(output, "BUILD-COMPLETE.json", marker)
    state.atomic(output, "controller-packaging.json", {"schemaVersion": "latent.dev.packaging-observation.v1",
        "compilerObservation": digest(raw), "observation": marker["observationDigest"],
        "packager": packager, "packageDigest": package["packageDigest"], "finishedAt": finished,
        "authority": "observed-local-build"})
