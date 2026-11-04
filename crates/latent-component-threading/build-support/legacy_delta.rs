//! Build-time, fixed-origin reconstruction of the historical diagnostic inputs.
//! This module is not reachable from the runtime and accepts no guest input.
use sha2::{Digest, Sha256};
use std::path::Path;

const MAX_SOURCE: usize = 1024 * 1024;
const MAX_DELTA: usize = 65536;
const MAX_OPERATIONS: usize = 4096;

#[derive(Clone, Copy)]
struct Spec {
    source: &'static str,
    delta: &'static str,
    output: &'static str,
    source_len: usize,
    delta_len: usize,
    target_len: usize,
    source_sha: &'static str,
    delta_sha: &'static str,
    target_sha: &'static str,
}

const SPECS: [Spec; 5] = [
    Spec {
        source: "src/rust_catalogue/original-body-image.bin",
        delta: "src/rust_catalogue/legacy/legacy-delta-0.bin",
        output: "rust_catalogue/original-body-image.bin",
        source_len: 176189,
        delta_len: 1048,
        target_len: 176171,
        source_sha: "eca9883441a2e8ef0b4ea721c53932866d117503382c6e8805cb7d7661fd1b8b",
        delta_sha: "4b0186d3152b819d30bbff0eb36198f19032edaa2241fd3eac2e76c35e3aa45f",
        target_sha: "96f285899ad07269dafc3a539c6d3247ac7ec441aa8807575718e18ab9e156c8",
    },
    Spec {
        source: "src/rust_catalogue/catalogue-normal-component.wasm",
        delta: "src/rust_catalogue/legacy/legacy-delta-1.bin",
        output: "legacy-normal-component.wasm",
        source_len: 250281,
        delta_len: 9771,
        target_len: 250260,
        source_sha: "0d66c4828a608e9ec0048205ac6f38539e417f62dbdaeb6b7bdc245aa1c073c8",
        delta_sha: "759318911a66164bb8fa0e5d577ffb0bd174da16460edbb5f800ed91f29add6b",
        target_sha: "0ded5f17359bbff107af47e422549765de2e17f4829853ed2011225d85a56107",
    },
    Spec {
        source: "src/rust_catalogue/catalogue-original-core.wasm",
        delta: "src/rust_catalogue/legacy/legacy-delta-2.bin",
        output: "legacy-original-core.wasm",
        source_len: 261403,
        delta_len: 10523,
        target_len: 261378,
        source_sha: "8cd26a5f34ec90f23af43dfcb21b0b619b369ed2199a5368a24572bb96cbf177",
        delta_sha: "ae60e1cc8bfeec71bc4511c525a3c7e2f7d09d2e7612cf1a8be7a7923f52d60b",
        target_sha: "7b280a32bc87a8db318432f47f8190816b6722f1402d1e2e161142788bdb0c69",
    },
    Spec {
        source: "src/rust_catalogue.rs",
        delta: "src/rust_catalogue/legacy/legacy-delta-3.bin",
        output: "rust_catalogue.rs",
        source_len: 773942,
        delta_len: 29049,
        target_len: 773854,
        source_sha: "22f15eaffd568c260c3e515fc294bb90fdd06bdf7c0f1ddf79c4e767ae47462d",
        delta_sha: "37dd44f97c19a50872bdc7f8ef4bab08990b58c173d1cfd9a2174bfc32668226",
        target_sha: "62aa5a141cc2c3825e5d2b6ff0ce6f95412592bde5824a6163293b9c6f0ba95d",
    },
    Spec {
        source: "src/rust_catalogue/origin.json",
        delta: "src/rust_catalogue/legacy/legacy-delta-4.bin",
        output: "legacy-origin.json",
        source_len: 31675,
        delta_len: 1745,
        target_len: 21800,
        source_sha: "3496ab40d1dd467fe03a725bdf4899eec010e7c8f8cb238ad8abb9788dfaf77a",
        delta_sha: "8eb138871cc6b05a7c8ad3681f5931ae9adc5787bba1bb3c38757b8a1ec4a06c",
        target_sha: "fb587eec2be86959bfe4d4251b5fe1635e02881f4426cc4f5ac4ee9dbf0b3ea7",
    },
];

fn sha_matches(bytes: &[u8], expected: &str) -> bool {
    let digest = Sha256::digest(bytes);
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut result = [0u8; 64];
    for (index, byte) in digest.iter().copied().enumerate() {
        result[index * 2] = HEX[usize::from(byte >> 4)];
        result[index * 2 + 1] = HEX[usize::from(byte & 15)];
    }
    expected.as_bytes() == result.as_slice()
}

fn take_u32(patch: &[u8], cursor: &mut usize) -> Result<usize, &'static str> {
    let end = cursor.checked_add(4).ok_or("legacy-delta-overflow")?;
    let value: [u8; 4] = patch
        .get(*cursor..end)
        .ok_or("legacy-delta-truncated")?
        .try_into()
        .map_err(|_| "legacy-delta-truncated")?;
    *cursor = end;
    Ok(u32::from_le_bytes(value) as usize)
}

fn decode(source: &[u8], patch: &[u8], target_len: usize) -> Result<Vec<u8>, &'static str> {
    if patch.len() > MAX_DELTA || patch.get(..5) != Some(b"LSFD1") || target_len > MAX_SOURCE {
        return Err("legacy-delta-header");
    }
    let mut cursor = 5;
    let expected_len = take_u32(patch, &mut cursor)?;
    let count = take_u32(patch, &mut cursor)?;
    if expected_len != target_len || count == 0 || count > MAX_OPERATIONS {
        return Err("legacy-delta-bounds");
    }
    let mut output = Vec::with_capacity(target_len);
    for _ in 0..count {
        let tag = *patch.get(cursor).ok_or("legacy-delta-truncated")?;
        cursor += 1;
        let bytes = match tag {
            0 => {
                let offset = take_u32(patch, &mut cursor)?;
                let len = take_u32(patch, &mut cursor)?;
                let end = offset.checked_add(len).ok_or("legacy-delta-overflow")?;
                if len == 0 {
                    return Err("legacy-delta-empty-copy");
                }
                source.get(offset..end).ok_or("legacy-delta-copy-range")?
            }
            1 => {
                let len = take_u32(patch, &mut cursor)?;
                let end = cursor.checked_add(len).ok_or("legacy-delta-overflow")?;
                if len == 0 {
                    return Err("legacy-delta-empty-literal");
                }
                let result = patch.get(cursor..end).ok_or("legacy-delta-literal-range")?;
                cursor = end;
                result
            }
            _ => return Err("legacy-delta-opcode"),
        };
        if output
            .len()
            .checked_add(bytes.len())
            .filter(|size| *size <= target_len)
            .is_none()
        {
            return Err("legacy-delta-output-bound");
        }
        output.extend_from_slice(bytes);
    }
    if cursor != patch.len() || output.len() != target_len {
        return Err("legacy-delta-incomplete-or-trailing");
    }
    Ok(output)
}

fn reconstruct(source: &[u8], patch: &[u8], spec: Spec) -> Result<Vec<u8>, &'static str> {
    if source.len() != spec.source_len
        || source.len() > MAX_SOURCE
        || !sha_matches(source, spec.source_sha)
    {
        return Err("legacy-delta-source-identity");
    }
    if patch.len() != spec.delta_len
        || patch.len() > MAX_DELTA
        || !sha_matches(patch, spec.delta_sha)
    {
        return Err("legacy-delta-identity");
    }
    let output = decode(source, patch, spec.target_len)?;
    if !sha_matches(&output, spec.target_sha) {
        return Err("legacy-delta-output-identity");
    }
    Ok(output)
}

fn checked_input(root: &Path, name: &str, maximum: usize) -> Result<Vec<u8>, &'static str> {
    let path = root.join(name);
    let meta = std::fs::symlink_metadata(&path).map_err(|_| "legacy-delta-input")?;
    if !meta.file_type().is_file() || meta.len() > maximum as u64 {
        return Err("legacy-delta-input");
    }
    let bytes = std::fs::read(path).map_err(|_| "legacy-delta-input")?;
    if bytes.len() > maximum {
        return Err("legacy-delta-input");
    }
    Ok(bytes)
}

#[cfg_attr(test, allow(dead_code))]
pub(crate) fn prepare(root: &Path, output: &Path) -> Result<(), &'static str> {
    // Verify every pair and result before writing any reconstructed file.
    let mut admitted = Vec::with_capacity(SPECS.len());
    for spec in SPECS {
        let source = checked_input(root, spec.source, MAX_SOURCE)?;
        let delta = checked_input(root, spec.delta, MAX_DELTA)?;
        admitted.push((spec.output, reconstruct(&source, &delta, spec)?));
    }
    std::fs::create_dir_all(output.join("rust_catalogue")).map_err(|_| "legacy-delta-output")?;
    for (name, bytes) in admitted {
        std::fs::write(output.join(name), bytes).map_err(|_| "legacy-delta-output")?;
    }
    Ok(())
}

#[cfg(test)]
pub(crate) fn original_pair_for_test() -> (Vec<u8>, Vec<u8>) {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let read = |spec: Spec| {
        let source = checked_input(root, spec.source, MAX_SOURCE).unwrap();
        let delta = checked_input(root, spec.delta, MAX_DELTA).unwrap();
        reconstruct(&source, &delta, spec).unwrap()
    };
    (read(SPECS[2]), read(SPECS[1]))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn bytes(name: &str) -> Vec<u8> {
        std::fs::read(Path::new(env!("CARGO_MANIFEST_DIR")).join(name)).unwrap()
    }
    #[test]
    fn authentic_catalogues_reconstruct_exact_historical_origins() {
        for spec in SPECS {
            let output = reconstruct(&bytes(spec.source), &bytes(spec.delta), spec).unwrap();
            assert_eq!(output.len(), spec.target_len);
            assert!(sha_matches(&output, spec.target_sha));
        }
    }
    #[test]
    fn wrong_origin_tamper_truncation_and_trailing_data_are_refused() {
        for spec in SPECS {
            let source = bytes(spec.source);
            let patch = bytes(spec.delta);
            let mut changed = source.clone();
            changed[0] ^= 1;
            assert!(reconstruct(&changed, &patch, spec).is_err());
            let mut changed = patch.clone();
            let index = changed.len() / 2;
            changed[index] ^= 1;
            assert!(reconstruct(&source, &changed, spec).is_err());
            assert!(reconstruct(&source, &patch[..patch.len() - 1], spec).is_err());
            let mut extended = patch.clone();
            extended.push(0);
            assert!(reconstruct(&source, &extended, spec).is_err());
            let mut wrong = spec;
            wrong.target_sha = "0000000000000000000000000000000000000000000000000000000000000000";
            assert!(reconstruct(&source, &patch, wrong).is_err());
        }
    }
    #[test]
    fn parser_refuses_resealed_copy_range_opcode_and_output_bound() {
        for spec in SPECS {
            let source = bytes(spec.source);
            let patch = bytes(spec.delta);
            assert_eq!(patch[13], 0);
            let mut bad = patch.clone();
            bad[14..18].copy_from_slice(&(source.len() as u32 + 1).to_le_bytes());
            assert!(decode(&source, &bad, spec.target_len).is_err());
            let mut bad = patch.clone();
            bad[13] = 9;
            assert!(decode(&source, &bad, spec.target_len).is_err());
            assert!(decode(&source, &patch, spec.target_len - 1).is_err());
        }
    }
}
