"""Exact e3 diagnostic assets reconstructed from fixed cdd source identities.

This is private qualification data. The guest cannot select an origin, change
limits, or request a reconstruction. All three identities are checked.
"""
from __future__ import annotations
import hashlib
import struct
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, read_file

MAX_SOURCE = 1024 * 1024
MAX_DELTA = 65536
MAX_OPERATIONS = 4096
SPECS = {
    'body-image': ('crates/latent-component-threading/src/rust_catalogue/original-body-image.bin', 'crates/latent-component-threading/src/rust_catalogue/legacy/legacy-delta-0.bin', 176189, 1048, 176171, 'eca9883441a2e8ef0b4ea721c53932866d117503382c6e8805cb7d7661fd1b8b', '4b0186d3152b819d30bbff0eb36198f19032edaa2241fd3eac2e76c35e3aa45f', '96f285899ad07269dafc3a539c6d3247ac7ec441aa8807575718e18ab9e156c8'),
    'normal-component': ('crates/latent-component-threading/src/rust_catalogue/catalogue-normal-component.wasm', 'crates/latent-component-threading/src/rust_catalogue/legacy/legacy-delta-1.bin', 250281, 9771, 250260, '0d66c4828a608e9ec0048205ac6f38539e417f62dbdaeb6b7bdc245aa1c073c8', '759318911a66164bb8fa0e5d577ffb0bd174da16460edbb5f800ed91f29add6b', '0ded5f17359bbff107af47e422549765de2e17f4829853ed2011225d85a56107'),
    'original-core': ('crates/latent-component-threading/src/rust_catalogue/catalogue-original-core.wasm', 'crates/latent-component-threading/src/rust_catalogue/legacy/legacy-delta-2.bin', 261403, 10523, 261378, '8cd26a5f34ec90f23af43dfcb21b0b619b369ed2199a5368a24572bb96cbf177', 'ae60e1cc8bfeec71bc4511c525a3c7e2f7d09d2e7612cf1a8be7a7923f52d60b', '7b280a32bc87a8db318432f47f8190816b6722f1402d1e2e161142788bdb0c69'),
    'catalogue': ('crates/latent-component-threading/src/rust_catalogue.rs', 'crates/latent-component-threading/src/rust_catalogue/legacy/legacy-delta-3.bin', 773942, 29049, 773854, '22f15eaffd568c260c3e515fc294bb90fdd06bdf7c0f1ddf79c4e767ae47462d', '37dd44f97c19a50872bdc7f8ef4bab08990b58c173d1cfd9a2174bfc32668226', '62aa5a141cc2c3825e5d2b6ff0ce6f95412592bde5824a6163293b9c6f0ba95d'),
    'origin': ('crates/latent-component-threading/src/rust_catalogue/origin.json', 'crates/latent-component-threading/src/rust_catalogue/legacy/legacy-delta-4.bin', 31675, 1745, 21800, '3496ab40d1dd467fe03a725bdf4899eec010e7c8f8cb238ad8abb9788dfaf77a', '8eb138871cc6b05a7c8ad3681f5931ae9adc5787bba1bb3c38757b8a1ec4a06c', 'fb587eec2be86959bfe4d4251b5fe1635e02881f4426cc4f5ac4ee9dbf0b3ea7'),
}


def _decode(source: bytes, patch: bytes, expected: int) -> bytes:
    require(type(source) is bytes and len(source) <= MAX_SOURCE
            and type(patch) is bytes and len(patch) <= MAX_DELTA
            and type(expected) is int and 0 < expected <= MAX_SOURCE
            and patch[:5] == b'LSFD1' and len(patch) >= 13, 'rust-legacy-delta-header')
    size, count = struct.unpack_from('<II', patch, 5)
    require(size == expected and 0 < count <= MAX_OPERATIONS, 'rust-legacy-delta-bounds')
    cursor, output = 13, bytearray()
    for _ in range(count):
        require(cursor < len(patch), 'rust-legacy-delta-truncated')
        tag = patch[cursor]; cursor += 1
        if tag == 0:
            require(cursor + 8 <= len(patch), 'rust-legacy-delta-copy-header')
            offset, length = struct.unpack_from('<II', patch, cursor); cursor += 8
            require(length > 0 and offset <= len(source) and length <= len(source) - offset,
                    'rust-legacy-delta-copy-range')
            value = source[offset:offset + length]
        elif tag == 1:
            require(cursor + 4 <= len(patch), 'rust-legacy-delta-literal-header')
            length, = struct.unpack_from('<I', patch, cursor); cursor += 4
            require(length > 0 and cursor + length <= len(patch), 'rust-legacy-delta-literal-range')
            value = patch[cursor:cursor + length]; cursor += length
        else:
            raise ValueError('rust-legacy-delta-opcode')
        require(len(output) + len(value) <= expected, 'rust-legacy-delta-output-bound')
        output.extend(value)
    require(cursor == len(patch) and len(output) == expected, 'rust-legacy-delta-incomplete-or-trailing')
    return bytes(output)


def reconstruct(source: bytes, patch: bytes, spec: tuple) -> bytes:
    _, _, source_size, patch_size, target_size, source_hash, patch_hash, target_hash = spec
    require(type(source) is bytes and len(source) == source_size and source_size <= MAX_SOURCE
            and hashlib.sha256(source).hexdigest() == source_hash, 'rust-legacy-source-identity')
    require(type(patch) is bytes and len(patch) == patch_size and patch_size <= MAX_DELTA
            and hashlib.sha256(patch).hexdigest() == patch_hash, 'rust-legacy-delta-identity')
    output = _decode(source, patch, target_size)
    require(hashlib.sha256(output).hexdigest() == target_hash, 'rust-legacy-target-identity')
    return output


def read_legacy(name: str) -> bytes:
    require(type(name) is str and name in SPECS, 'rust-legacy-fixed-name')
    spec = SPECS[name]
    return reconstruct(read_file(ROOT / spec[0], MAX_SOURCE), read_file(ROOT / spec[1], MAX_DELTA), spec)
