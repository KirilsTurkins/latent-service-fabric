//! Bounded reconstruction of original source material from a component image.
//!
//! This diagnostic codec only reconstructs bytes; it does not authenticate a
//! component, select a runtime, or reserve memory. A caller must reserve all
//! work before decoding and independently verify the reconstructed source and
//! full component. Copy commands refer only to the supplied unwrapped image.

const MAGIC: &[u8; 8] = b"LSFDLT01";
const MAX_ORIGINAL: usize = 1024 * 1024;
const MAX_BASE: usize = 2 * 1024 * 1024;
const MAX_DELTA: usize = 1024 * 1024;
const MAX_COMMANDS: usize = 32_768;

fn read_u32(input: &[u8], cursor: &mut usize) -> Result<usize, &'static str> {
    let end = cursor.checked_add(4).ok_or("rust-delta-overflow")?;
    let value = input.get(*cursor..end).ok_or("rust-delta-truncated")?;
    let bytes: [u8; 4] = value.try_into().map_err(|_| "rust-delta-truncated")?;
    *cursor = end;
    Ok(u32::from_le_bytes(bytes) as usize)
}

/// Reconstruct at most one MiB, using only bounded copies and literals.
/// The caller is responsible for charging this output and for authenticating
/// both it and the original, unwrapped component before any runtime use.
#[allow(dead_code)]
pub(crate) fn reconstruct(base: &[u8], delta: &[u8]) -> Result<Vec<u8>, &'static str> {
    if base.len() > MAX_BASE || delta.len() > MAX_DELTA || delta.get(..8) != Some(MAGIC.as_slice())
    {
        return Err("rust-delta-envelope");
    }
    let mut cursor = 8;
    let output_len = read_u32(delta, &mut cursor)?;
    let count = read_u32(delta, &mut cursor)?;
    if !(8..=MAX_ORIGINAL).contains(&output_len) || !(1..=MAX_COMMANDS).contains(&count) {
        return Err("rust-delta-bounds");
    }
    let mut output = Vec::new();
    output
        .try_reserve_exact(output_len)
        .map_err(|_| "rust-delta-allocation")?;
    for _ in 0..count {
        let tag = *delta.get(cursor).ok_or("rust-delta-truncated")?;
        cursor = cursor.checked_add(1).ok_or("rust-delta-overflow")?;
        let bytes = match tag {
            0 => {
                let offset = read_u32(delta, &mut cursor)?;
                let len = read_u32(delta, &mut cursor)?;
                let end = offset.checked_add(len).ok_or("rust-delta-overflow")?;
                base.get(offset..end).ok_or("rust-delta-copy-range")?
            }
            1 => {
                let len = read_u32(delta, &mut cursor)?;
                let end = cursor.checked_add(len).ok_or("rust-delta-overflow")?;
                let value = delta.get(cursor..end).ok_or("rust-delta-truncated")?;
                cursor = end;
                value
            }
            _ => return Err("rust-delta-command"),
        };
        let new_len = output
            .len()
            .checked_add(bytes.len())
            .ok_or("rust-delta-overflow")?;
        if bytes.is_empty() || new_len > output_len {
            return Err("rust-delta-output-bound");
        }
        output.extend_from_slice(bytes);
    }
    if output.len() != output_len || cursor != delta.len() {
        return Err("rust-delta-incomplete-or-trailing");
    }
    Ok(output)
}

// The custom section is proof material only. Framing and reconstruction never
// enable a runtime; a caller must still authenticate the complete base graph.
const DELTA_SECTION: &str = "latent-rust-original-delta-v1";

fn parts(input: &[u8]) -> Result<Option<(&[u8], &[u8])>, &'static str> {
    use wasmparser::BinaryReader;
    if input.len() > MAX_BASE || input.get(..8) != Some(b"\0asm\x0d\0\x01\0".as_slice()) {
        return Err("rust-delta-component-envelope");
    }
    let mut reader = BinaryReader::new(&input[8..], 0);
    let mut sections = 0usize;
    while !reader.eof() {
        sections += 1;
        if sections > 256 {
            return Err("rust-delta-component-section-bound");
        }
        let start = input.len() - reader.bytes_remaining();
        let kind = reader
            .read_u8()
            .map_err(|_| "rust-delta-component-section")?;
        let len = reader
            .read_var_u32()
            .map_err(|_| "rust-delta-component-section")?;
        let payload = reader
            .read_bytes(len as usize)
            .map_err(|_| "rust-delta-component-section")?;
        if kind == 0 {
            let mut custom = BinaryReader::new(payload, 0);
            let name_len = custom
                .read_var_u32()
                .map_err(|_| "rust-delta-component-name")?;
            if name_len > 512 {
                return Err("rust-delta-component-name");
            }
            let name = custom
                .read_bytes(name_len as usize)
                .map_err(|_| "rust-delta-component-name")?;
            if name == DELTA_SECTION.as_bytes() {
                if !reader.eof() {
                    return Err("rust-delta-single-final-section-required");
                }
                let remaining = custom.bytes_remaining();
                let delta = custom
                    .read_bytes(remaining)
                    .map_err(|_| "rust-delta-truncated")?;
                if delta.len() > MAX_DELTA || delta.get(..8) != Some(MAGIC.as_slice()) {
                    return Err("rust-delta-envelope");
                }
                return Ok(Some((&input[..start], delta)));
            }
        }
    }
    Ok(None)
}

/// Package bounded reconstruction material on an already authenticated graph.
/// Callers must independently perform the source and graph proof first.
#[allow(dead_code)]
pub(crate) fn attach_unverified(base: &[u8], delta: &[u8]) -> Result<Vec<u8>, &'static str> {
    use std::borrow::Cow;
    use wasm_encoder::{CustomSection, Encode, Section};
    if parts(base)?.is_some() {
        return Err("rust-delta-duplicate-section");
    }
    if delta.len() > MAX_DELTA || delta.get(..8) != Some(MAGIC.as_slice()) {
        return Err("rust-delta-envelope");
    }
    let upper = base
        .len()
        .checked_add(delta.len())
        .and_then(|n| n.checked_add(128))
        .ok_or("rust-delta-component-byte-bound")?;
    if upper > MAX_BASE {
        return Err("rust-delta-component-byte-bound");
    }
    let mut result = Vec::new();
    result
        .try_reserve_exact(upper)
        .map_err(|_| "rust-delta-allocation")?;
    result.extend_from_slice(base);
    let section = CustomSection {
        name: Cow::Borrowed(DELTA_SECTION),
        data: Cow::Borrowed(delta),
    };
    result.push(section.id());
    section.encode(&mut result);
    Ok(result)
}

/// Split the sole final delta section from the exact remaining component.
/// The result and reconstructed original remain untrusted until verified.
#[allow(dead_code)]
pub(crate) fn split_unverified(input: &[u8]) -> Result<(&[u8], &[u8]), &'static str> {
    parts(input)?.ok_or("rust-delta-final-section-required")
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::Digest;
    const BASE: &[u8] = include_bytes!("rust_catalogue/combined-final-component.wasm");
    const ORIGINAL: &[u8] = include_bytes!("rust_catalogue/combined-original-core.wasm");
    const PREVIEW: &[u8] = include_bytes!("rust_catalogue/combined-preview-component.wasm");
    const DELTA: &[u8] = include_bytes!("rust_catalogue/combined-original-delta.bin");

    fn delta(len: u32, count: u32, body: &[u8]) -> Vec<u8> {
        let mut result = MAGIC.to_vec();
        result.extend_from_slice(&len.to_le_bytes());
        result.extend_from_slice(&count.to_le_bytes());
        result.extend_from_slice(body);
        result
    }

    #[test]
    fn fixed_real_delta_reconstructs_and_still_requires_full_source_proof() {
        let original = reconstruct(BASE, DELTA).unwrap();
        assert_eq!(original.as_slice(), ORIGINAL);
        assert!(BASE.len() + DELTA.len() + 128 <= MAX_BASE);
        let proof =
            crate::rust_component::verify_combined_composition(&original, PREVIEW, BASE).unwrap();
        assert!(proof.final_composition_authenticated);
        assert!(!proof.runtime_qualified);
        let mut wrong = original;
        wrong[0] ^= 1;
        assert!(crate::rust_component::verify_combined_composition(&wrong, PREVIEW, BASE).is_err());
    }

    #[test]
    fn fixed_graph_roundtrips_final_section_and_rejects_nonfinal_or_forged_material() {
        let wrapped = attach_unverified(BASE, DELTA).unwrap();
        assert!(wrapped.len() <= MAX_BASE);
        let (base, delta) = split_unverified(&wrapped).unwrap();
        assert_eq!(base, BASE);
        assert_eq!(delta, DELTA);
        let original = reconstruct(base, delta).unwrap();
        assert_eq!(original.as_slice(), ORIGINAL);
        assert!(
            crate::rust_component::verify_combined_composition(&original, PREVIEW, base).is_ok()
        );
        let proof = crate::rust_component::verify_embedded_combined_diagnostic(&wrapped).unwrap();
        assert!(proof.final_graph_authenticated && !proof.runtime_qualified);
        assert_eq!(
            proof.original_digest,
            <[u8; 32]>::from(sha2::Sha256::digest(ORIGINAL))
        );

        assert!(attach_unverified(&wrapped, DELTA).is_err());
        assert!(split_unverified(BASE).is_err());
        assert!(split_unverified(&wrapped[..wrapped.len() - 1]).is_err());
        let mut nonfinal = wrapped;
        nonfinal.extend_from_slice(&[0, 1, 0]);
        assert!(split_unverified(&nonfinal).is_err());
        let mut forged = DELTA.to_vec();
        forged[21] ^= 1; // fixed first literal byte, not a command or size
        let forged_wrapped = attach_unverified(BASE, &forged).unwrap();
        assert!(
            crate::rust_component::verify_embedded_combined_diagnostic(&forged_wrapped).is_err()
        );
        let forged_original = reconstruct(BASE, &forged).unwrap();
        assert!(
            crate::rust_component::verify_combined_composition(&forged_original, PREVIEW, BASE)
                .is_err()
        );
    }

    #[test]
    fn malformed_ranges_lengths_commands_and_trailing_data_fail_closed() {
        let base = b"0123456789abcdef";
        let mut copy = vec![0];
        copy.extend_from_slice(&3u32.to_le_bytes());
        copy.extend_from_slice(&8u32.to_le_bytes());
        assert_eq!(
            reconstruct(base, &delta(8, 1, &copy)).unwrap().as_slice(),
            b"3456789a"
        );
        assert!(reconstruct(base, &delta(8, 1, &copy[..8])).is_err());
        let mut invalid_range = vec![0];
        invalid_range.extend_from_slice(&u32::MAX.to_le_bytes());
        invalid_range.extend_from_slice(&8u32.to_le_bytes());
        assert!(reconstruct(base, &delta(8, 1, &invalid_range)).is_err());
        let mut zero_copy = vec![0];
        zero_copy.extend_from_slice(&0u32.to_le_bytes());
        zero_copy.extend_from_slice(&0u32.to_le_bytes());
        assert!(reconstruct(base, &delta(8, 1, &zero_copy)).is_err());
        assert!(reconstruct(base, &delta(8, 1, &[2])).is_err());
        assert!(reconstruct(base, &delta(8, 32_769, &[])).is_err());
        assert!(reconstruct(base, &delta(1_048_577, 1, &copy)).is_err());
        assert!(reconstruct(base, &delta(9, 1, &copy)).is_err());
        assert!(reconstruct(base, &delta(8, 2, &copy)).is_err());
        let mut trailing = delta(8, 1, &copy);
        trailing.push(0);
        assert!(reconstruct(base, &trailing).is_err());
        let mut literal = vec![1];
        literal.extend_from_slice(&8u32.to_le_bytes());
        literal.extend_from_slice(b"original");
        assert_eq!(
            reconstruct(base, &delta(8, 1, &literal))
                .unwrap()
                .as_slice(),
            b"original"
        );
        literal.pop();
        assert!(reconstruct(base, &delta(8, 1, &literal)).is_err());
    }
}
