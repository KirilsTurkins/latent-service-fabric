"""Exact6fd locked inputs for the existing bounded private observer build."""
from pathlib import Path
import re
import tomllib
from tools.java_resource_private_build import private_target, retain_private_cargo
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import digest, read_file

LOCK='sha256:6e0dae431659b4486fac4dce4aac6ef8ff24c5eee9fe8b2f7e2195a8cd42e3c4'


def locked_registry_inputs(root: Path) -> dict:
    raw=read_file(root/'Cargo.lock',1024*1024)
    require(len(raw)==112657 and digest(raw)==LOCK,'rust-private-exact6fd-lock')
    packages=tomllib.loads(raw.decode())['package']
    require(0<len(packages)<=2048 and all(not row.get('source') or (
        row['source']=='registry+https://github.com/rust-lang/crates.io-index'
        and re.fullmatch('[a-f0-9]{64}',row.get('checksum',''))) for row in packages),
        'rust-private-checksummed-registry-only')
    return {'lock':file_identity(root/'Cargo.lock'),'packages':len(packages),
        'registryPackages':sum(bool(row.get('source')) for row in packages),
        'target':'x86_64-unknown-linux-gnu','locked':True,'buildScriptsExecuted':False}
