//! Finite Rust sync normal-component proof from host-owned original objects.
//!
//! This first profile admits the exact greeting WIT/import/encoder envelope
//! retained alongside the immutable object catalogue. Every main-core byte is
//! independently recomputed. No embedded hash, JSON, rlib or producer selects
//! a catalogue or enables a runtime. Other WIT/import/encoder shapes refuse.
use crate::{RootReceipt, rust_objects};
use sha2::{Digest, Sha256};
use wasmparser::{BinaryReader, Validator, WasmFeatures};

pub const RUST_PREIMAGE_SECTION: &str = "latent-rust-original-core-v1";
pub const MAX_ORIGINAL_BYTES: usize = 1024 * 1024;
pub const MAX_COMPONENT_BYTES: usize = 2 * 1024 * 1024;
// Admitted BEFORE recomputation. Sixteen2MiB image units cover overlapping
// input/output/reencoder/section/TLS buffers; eightMiB separately covers the
// fixed1222-node/5312-edge graph and bounded scalar signatures; eightMiB covers
// validator state. Original component storage is charged independently.
pub const RUST_VERIFICATION_WORK_BYTES: usize = 48 * 1024 * 1024;
const MAGIC: &[u8; 8] = b"LSFRPR01";
const PUBLIC: &str = "examples:greeting/api@1.0.0#greet";
const POST: &str = "cabi_post_examples:greeting/api@1.0.0#greet";
const SHELL: &[u8] = include_bytes!("rust_catalogue/normal-component-shell.bin");
const ORIGINAL_WIT: &[u8] = include_bytes!("rust_catalogue/original-wit-metadata.bin");
const ADAPTED_WIT: &[u8] = include_bytes!("rust_catalogue/adapted-wit-metadata.bin");
const ORIGINAL_PRODUCERS: &[u8] = include_bytes!("rust_catalogue/original-producers.bin");
const ENCODED_PRODUCERS: &[u8] = include_bytes!("rust_catalogue/encoded-producers.bin");

#[derive(Debug)]
pub struct RustComponentRoutingReceipt {
    pub component_digest: [u8; 32],
    pub original_core_digest: [u8; 32],
    pub main_core_digest: [u8; 32],
    pub catalogue_origin_head: &'static str,
    pub catalogue_origin_recipe: &'static str,
    pub catalogue_body_digest: &'static str,
    pub root: RootReceipt,
    pub actual_component_graph_authenticated: bool,
    pub canonical_creation_enabled: bool,
    pub standard_runtime_qualified: bool,
}

struct Section<'a> {
    kind: u8,
    payload: &'a [u8],
    whole: &'a [u8],
}
fn section<'a>(reader: &mut BinaryReader<'a>) -> Result<Section<'a>, &'static str> {
    let mut snapshot = reader.clone();
    let whole = snapshot
        .read_bytes(snapshot.bytes_remaining())
        .map_err(|_| "rust-component-section-bytes")?;
    let kind = reader
        .read_u8()
        .map_err(|_| "rust-component-section-kind")?;
    let size = reader
        .read_var_u32()
        .map_err(|_| "rust-component-section-size")?;
    let payload = reader
        .read_bytes(size as usize)
        .map_err(|_| "rust-component-section-bytes")?;
    let length = whole.len() - reader.bytes_remaining();
    Ok(Section {
        kind,
        payload,
        whole: &whole[..length],
    })
}
fn custom_name(payload: &[u8]) -> Result<&str, &'static str> {
    let mut reader = BinaryReader::new(payload, 0);
    let size = reader
        .read_var_u32()
        .map_err(|_| "rust-component-custom-name")?;
    if size > 512 {
        return Err("rust-component-custom-name-bound");
    }
    std::str::from_utf8(
        reader
            .read_bytes(size as usize)
            .map_err(|_| "rust-component-custom-name")?,
    )
    .map_err(|_| "rust-component-custom-name")
}
fn header(input: &[u8], component: bool) -> Result<(), &'static str> {
    let magic = if component {
        b"\0asm\x0d\0\x01\0"
    } else {
        b"\0asm\x01\0\0\0"
    };
    if input.get(..8) != Some(magic) {
        return Err("rust-component-framing");
    }
    Ok(())
}

/// Preserve ordinary synchronous Core marshalling while declaring the selected
/// public effect async, so Wasmtime permits its real wait/sleep suspensions.
/// Both complete payloads are immutable host source inputs, never guest facts.
pub fn adapt_original_public_wit(input: &[u8]) -> Result<Vec<u8>, &'static str> {
    use wasm_encoder::{Encode, RawSection};
    if input.len() > MAX_ORIGINAL_BYTES {
        return Err("rust-component-original-byte-bound");
    }
    header(input, false)?;
    let mut reader = BinaryReader::new(&input[8..], 0);
    let mut output = Vec::with_capacity(input.len());
    output.extend_from_slice(&input[..8]);
    let mut count = 0;
    let mut changed = false;
    while !reader.eof() {
        count += 1;
        if count > 512 {
            return Err("rust-component-main-section-bound");
        }
        let current = section(&mut reader)?;
        if current.kind == 0 && custom_name(current.payload)?.starts_with("component-type") {
            if changed || current.payload != ORIGINAL_WIT {
                return Err("rust-component-authentic-original-wit-required");
            }
            output.push(0);
            RawSection {
                id: 0,
                data: ADAPTED_WIT,
            }
            .encode(&mut output);
            changed = true;
        } else {
            output.extend_from_slice(current.whole);
        }
    }
    if !changed {
        return Err("rust-component-authentic-original-wit-required");
    }
    Ok(output)
}

// Raw framing and immutable comparisons happen before any component reader
// could collect an attacker-declared type/start/instance argument vector.
fn main_from_envelope(input: &[u8]) -> Result<&[u8], &'static str> {
    if input.len() > MAX_COMPONENT_BYTES {
        return Err("rust-component-byte-bound");
    }
    header(input, true)?;
    header(SHELL, true)?;
    let mut actual = BinaryReader::new(&input[8..], 0);
    let mut expected = BinaryReader::new(&SHELL[8..], 0);
    let mut main = None;
    let mut count = 0;
    while !expected.eof() {
        count += 1;
        if count > 256 {
            return Err("rust-component-shell-section-bound");
        }
        let reference = section(&mut expected)?;
        let current = section(&mut actual)?;
        if reference.kind == 1 && reference.payload.is_empty() {
            if main.replace(current.payload).is_some()
                || current.kind != 1
                || current.payload.len() > MAX_ORIGINAL_BYTES
            {
                return Err("rust-component-single-recomputed-main");
            }
        } else if current.whole != reference.whole {
            return Err("rust-component-original-normal-envelope-mismatch");
        }
    }
    if !actual.eof() {
        return Err("rust-component-unexpected-envelope-tail");
    }
    main.ok_or("rust-component-recomputed-main-missing")
}

// Only the actual consumed original WIT custom payload and exact producer
// merge differ. Executable/data/custom/name bytes retain their original order.
fn compare_encoded_main(source: &[u8], encoded: &[u8]) -> Result<(), &'static str> {
    header(source, false)?;
    header(encoded, false)?;
    let mut original = BinaryReader::new(&source[8..], 0);
    let mut actual = BinaryReader::new(&encoded[8..], 0);
    let mut metadata = false;
    let mut producers = false;
    let mut count = 0;
    while !original.eof() {
        count += 1;
        if count > 512 {
            return Err("rust-component-main-section-bound");
        }
        let expected = section(&mut original)?;
        let name = if expected.kind == 0 {
            Some(custom_name(expected.payload)?)
        } else {
            None
        };
        if name.is_some_and(|name| name.starts_with("component-type")) {
            if metadata || expected.payload != ADAPTED_WIT {
                return Err("rust-component-authentic-original-wit-required");
            }
            metadata = true;
            continue;
        }
        let current = section(&mut actual)?;
        if name == Some("producers") {
            if producers
                || expected.payload != ORIGINAL_PRODUCERS
                || current.kind != 0
                || current.payload != ENCODED_PRODUCERS
            {
                return Err("rust-component-exact-normal-producer-merge");
            }
            producers = true;
        } else if current.whole != expected.whole {
            return Err("rust-component-recomputed-main-mismatch");
        }
    }
    if !actual.eof() || !metadata || !producers {
        return Err("rust-component-incomplete-normal-main");
    }
    Ok(())
}

/// Source proof only. The host must admit the full work allowance first and
/// retain its component/source owners through compilation, execution and drop.
/// Admission/profile and actual signed runtime qualification remain separate.
pub fn verify_rust_component_routing(
    original: &[u8],
    component: &[u8],
) -> Result<RustComponentRoutingReceipt, &'static str> {
    if original.len() > MAX_ORIGINAL_BYTES {
        return Err("rust-component-original-byte-bound");
    }
    let main = main_from_envelope(component)?;
    let (expected, proof) = rust_objects::derive_source_core(original, PUBLIC, POST)?;
    if expected.len() > MAX_ORIGINAL_BYTES {
        return Err("rust-component-derived-byte-bound");
    }
    compare_encoded_main(&expected, main)?;
    // All allocating component structures now equal the fixed host image;
    // every main executable/data byte equals the independently bounded proof.
    Validator::new_with_features(WasmFeatures::all())
        .validate_all(component)
        .map_err(|_| "rust-component-invalid-normal-component")?;
    Ok(RustComponentRoutingReceipt {
        component_digest: Sha256::digest(component).into(),
        original_core_digest: proof.original_digest,
        main_core_digest: Sha256::digest(main).into(),
        catalogue_origin_head: proof.catalogue_origin_head,
        catalogue_origin_recipe: proof.catalogue_origin_recipe,
        catalogue_body_digest: proof.catalogue_body_digest,
        root: proof.root,
        actual_component_graph_authenticated: true,
        canonical_creation_enabled: false,
        standard_runtime_qualified: false,
    })
}

fn preimage(input: &[u8]) -> Result<(&[u8], &[u8]), &'static str> {
    if input.len() > MAX_COMPONENT_BYTES {
        return Err("rust-component-byte-bound");
    }
    header(input, true)?;
    let mut reader = BinaryReader::new(&input[8..], 0);
    let mut count = 0;
    while !reader.eof() {
        count += 1;
        if count > 256 {
            return Err("rust-component-shell-section-bound");
        }
        let start = input.len() - reader.bytes_remaining();
        let current = section(&mut reader)?;
        if current.kind == 0 && custom_name(current.payload)? == RUST_PREIMAGE_SECTION {
            if !reader.eof() {
                return Err("rust-component-single-final-preimage-required");
            }
            let mut payload = BinaryReader::new(current.payload, 0);
            let name_len = payload
                .read_var_u32()
                .map_err(|_| "rust-component-preimage-name")?;
            payload
                .read_bytes(name_len as usize)
                .map_err(|_| "rust-component-preimage-name")?;
            if payload.read_bytes(8).ok() != Some(MAGIC.as_slice()) {
                return Err("rust-component-preimage-version");
            }
            let size = payload
                .read_u32()
                .map_err(|_| "rust-component-preimage-size")? as usize;
            if size > MAX_ORIGINAL_BYTES || size != payload.bytes_remaining() {
                return Err("rust-component-preimage-byte-bound");
            }
            return Ok((
                &input[..start],
                payload
                    .read_bytes(size)
                    .map_err(|_| "rust-component-preimage-bytes")?,
            ));
        }
    }
    Err("rust-component-original-preimage-required")
}

/// Package only an already source-authenticated ordinary normal component.
/// The original core is untrusted proof material, not an enablement marker.
pub fn attach_rust_original_core(
    original: &[u8],
    component: &[u8],
) -> Result<Vec<u8>, &'static str> {
    use std::borrow::Cow;
    use wasm_encoder::{CustomSection, Section};
    verify_rust_component_routing(original, component)?;
    let total = component
        .len()
        .checked_add(original.len())
        .and_then(|n| n.checked_add(128))
        .ok_or("rust-component-byte-bound")?;
    if total > MAX_COMPONENT_BYTES {
        return Err("rust-component-byte-bound");
    }
    let mut payload = Vec::with_capacity(original.len() + 12);
    payload.extend_from_slice(MAGIC);
    payload.extend_from_slice(&(original.len() as u32).to_le_bytes());
    payload.extend_from_slice(original);
    let custom = CustomSection {
        name: Cow::Borrowed(RUST_PREIMAGE_SECTION),
        data: Cow::Borrowed(&payload),
    };
    let mut output = Vec::with_capacity(total);
    output.extend_from_slice(component);
    output.push(custom.id());
    wasm_encoder::Encode::encode(&custom, &mut output);
    Ok(output)
}

/// Recompute against the compiled original catalogue and normal envelope.
/// Caller-owned preparation accounting must precede this allocating proof.
pub fn verify_embedded_rust_original_core(
    component: &[u8],
) -> Result<RustComponentRoutingReceipt, &'static str> {
    let (normal, original) = preimage(component)?;
    let mut receipt = verify_rust_component_routing(original, normal)?;
    receipt.component_digest = Sha256::digest(component).into();
    Ok(receipt)
}

#[cfg(test)]
mod tests {
    use super::*;
    const ORIGINAL: &[u8] = include_bytes!("rust_catalogue/catalogue-original-core.wasm");
    const COMPONENT: &[u8] = include_bytes!("rust_catalogue/catalogue-normal-component.wasm");

    #[test]
    fn rust_normal_component_recomputes_original_graph_and_rejects_envelope_or_main_changes() {
        let adapted = adapt_original_public_wit(ORIGINAL).unwrap();
        assert_eq!(adapted.len(), ORIGINAL.len());
        let changes: Vec<_> = ORIGINAL
            .iter()
            .zip(&adapted)
            .filter(|(a, b)| a != b)
            .collect();
        assert_eq!(changes, vec![(&0x40, &0x43)]);
        assert_eq!(
            adapt_original_public_wit(&adapted).unwrap_err(),
            "rust-component-authentic-original-wit-required"
        );
        let proof = verify_rust_component_routing(ORIGINAL, COMPONENT).unwrap();
        assert_eq!(
            proof.catalogue_origin_head,
            "a9809cab6aa3021b29014bd8b80dd15922c93265"
        );
        assert!(proof.actual_component_graph_authenticated);
        assert!(!proof.canonical_creation_enabled && !proof.standard_runtime_qualified);
        let mut changed = COMPONENT.to_vec();
        let tail = changed.len() - 1;
        changed[tail] ^= 1;
        assert_eq!(
            verify_rust_component_routing(ORIGINAL, &changed).unwrap_err(),
            "rust-component-original-normal-envelope-mismatch"
        );
        let main = main_from_envelope(COMPONENT).unwrap();
        let start = main.as_ptr() as usize - COMPONENT.as_ptr() as usize;
        let mut changed = COMPONENT.to_vec();
        changed[start + 8] ^= 1;
        assert!(verify_rust_component_routing(ORIGINAL, &changed).is_err());
    }

    #[test]
    fn rust_normal_preimage_never_authorizes_forged_or_duplicate_original_material() {
        let wrapped = attach_rust_original_core(ORIGINAL, COMPONENT).unwrap();
        assert_eq!(
            verify_embedded_rust_original_core(&wrapped)
                .unwrap()
                .component_digest,
            <[u8; 32]>::from(Sha256::digest(&wrapped))
        );
        let mut changed = wrapped.clone();
        *changed.last_mut().unwrap() ^= 1;
        assert!(verify_embedded_rust_original_core(&changed).is_err());
        let mut duplicate = wrapped.clone();
        duplicate.extend_from_slice(&wrapped[COMPONENT.len()..]);
        assert_eq!(
            verify_embedded_rust_original_core(&duplicate).unwrap_err(),
            "rust-component-single-final-preimage-required"
        );
        assert_eq!(
            verify_embedded_rust_original_core(COMPONENT).unwrap_err(),
            "rust-component-original-preimage-required"
        );
    }
}
