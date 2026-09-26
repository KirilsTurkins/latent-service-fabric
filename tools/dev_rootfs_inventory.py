"""Run inside the pinned image to retain its observed packages and license texts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> None:
    root = Path("/opt/latent-dev")
    output = root / "distribution"
    output.mkdir()
    licenses = output / "licenses"
    licenses.mkdir()
    shutil.copyfile(root / "LSF-LICENSE", licenses / "LSF.txt")
    python_license = Path("/usr/local/lib/python3.13/LICENSE.txt")
    if not python_license.is_file():
        raise RuntimeError("pinned-python-license-missing")
    shutil.copyfile(python_license, licenses / "Python-3.13.5.txt")
    for path in sorted(Path("/usr/share/common-licenses").iterdir()):
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to("/usr/share/common-licenses") or not resolved.is_file():
            raise RuntimeError("common-license-source-invalid")
        shutil.copyfile(resolved, licenses / ("common-" + path.name + ".txt"))
    packages = []
    observed = subprocess.check_output(["/usr/bin/dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n"], text=True)
    for line in sorted(observed.splitlines()):
        name, version = line.split("\t")
        copyright_file = Path("/usr/share/doc") / name.split(":")[0] / "copyright"
        # Debian's copyright files sometimes share a package-owned documentation directory.
        resolved = copyright_file.resolve(strict=True)
        if not resolved.is_relative_to("/usr/share/doc"):
            raise RuntimeError("package-license-outside-doc-root")
        raw = resolved.read_bytes()
        destination = "licenses/ubuntu-" + name.replace(":", "-") + ".txt"
        (output / destination).write_bytes(raw)
        packages.append({"name": name, "version": version, "licenseFile": destination,
                         "licenseSha256": "sha256:" + hashlib.sha256(raw).hexdigest()})
    source = json.loads((root / "source.json").read_bytes())
    record = {"schemaVersion": "latent.dev.rootfs-inventory.v1", **source,
              "osRelease": Path("/etc/os-release").read_text(), "python": sys.version.split()[0],
              "helperSha256": "sha256:" + hashlib.sha256((root / "helper.pyz").read_bytes()).hexdigest(),
              "packages": packages, "wslConfiguration": Path("/etc/wsl.conf").read_text(),
              "qualification": "image-assembly-only", "publisherAuthenticated": False}
    (output / "rootfs-inventory.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
