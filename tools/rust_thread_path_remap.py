"""Deterministic compiler diagnostic paths for the selected thread profile.

Original source/CAS bytes and actual input directories remain protected by
their existing capture/Prepared guards. No path or byte mask grants authority.
"""
from pathlib import Path

from tools.dev_workflow.common import require
from tools.rust_capsule_project import checked_path

STD = '/lsf/rust/library'
APPLICATION = '/lsf/application'


def source_mapping(root: Path, destination: str) -> dict:
    root = checked_path(root).resolve(strict=True)
    require(root.is_dir() and destination in (STD, APPLICATION), 'rust-thread-remap-input-directory')
    source = str(root)
    require(len(source) <= 4096 and not any(char in source for char in ('=', '\x1f', '\0')),
            'rust-thread-remap-source-prefix')
    return {'sourceRoot': source, 'mappedRoot': destination,
            'argument': '--remap-path-prefix=' + source + '=' + destination}


def standard_flags(root: Path, base: str) -> tuple[list[str], dict]:
    mapping = source_mapping(root, STD)
    return [*base.split(), mapping['argument']], mapping


def verify_standard_receipt(mapping, flags, base: str) -> None:
    require(isinstance(mapping, dict) and set(mapping) == {'sourceRoot', 'mappedRoot', 'argument'},
            'rust-thread-remap-receipt-shape')
    source = mapping['sourceRoot']
    require(isinstance(source, str) and 0 < len(source) <= 4096 and Path(source).is_absolute()
            and not any(char in source for char in ('=', '\x1f', '\0'))
            and mapping['mappedRoot'] == STD
            and mapping['argument'] == '--remap-path-prefix=' + source + '=' + STD
            and flags == [*base.split(), mapping['argument']], 'rust-thread-remap-receipt-arguments')
