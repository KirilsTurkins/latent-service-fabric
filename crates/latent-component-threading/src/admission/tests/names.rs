use super::*;
use wasm_encoder::{IndirectNameMap, NameMap, NameSection};

fn with_names(names: &NameSection) -> Vec<u8> {
    let mut input = fixture(true, true);
    let mut extra = Module::new();
    extra.section(names);
    input.extend_from_slice(&extra.finish()[8..]);
    input
}

fn named(kind: u8, outer: &[u32], inner: &[u32]) -> NameSection {
    let mut names = NameSection::new();
    let mut direct = NameMap::new();
    let mut indirect = IndirectNameMap::new();
    for &index in outer {
        direct.append(index, "original-function");
        let mut locals = NameMap::new();
        for &local in inner {
            locals.append(local, "original-local");
        }
        indirect.append(index, &locals);
    }
    match kind {
        1 => { names.functions(&direct); }
        2 => { names.locals(&indirect); }
        3 => { names.labels(&indirect); }
        4 => { names.types(&direct); }
        _ => unreachable!(),
    }
    names
}

fn payload(input: &[u8]) -> Vec<u8> {
    Parser::new(0).parse_all(input).find_map(|p| match p.unwrap() {
        Payload::CustomSection(section) if section.name() == "name" => {
            Some(section.data().to_vec())
        }
        _ => None,
    }).unwrap()
}

#[test]
fn internal_name_remap_preserves_frozen_row_order_and_original_referents() {
    for kind in [1, 2, 3] {
        let input = with_names(&named(kind, &[3, 1, 0, 2], &[0, 1]));
        let original = input.clone();
        // An ordinary linked-core caller cannot opt into the private path.
        assert_eq!(
            transform_owned_thread_admission(&input, hash(&input)).unwrap_err(),
            "rust-child-admission-reencode-failed"
        );
        let (output, receipt) = transform_derived_thread_admission(&input, hash(&input)).unwrap();
        // The appended admission function replaces only raw creation's index.
        let expected = with_names(&named(kind, &[3, 4, 0, 2], &[0, 1]));
        assert_eq!(payload(&output), payload(&expected));
        assert_eq!(input, original);
        assert_eq!(receipt.original_digest, hash(&input));
        assert_eq!(receipt.derived_digest, hash(&output));
        assert!(!receipt.component_routing_authenticated);
        assert!(!receipt.canonical_creation_enabled);
        Validator::new().validate_all(&output).unwrap();
        verify(&output, inspect(&input).unwrap()).unwrap();
    }
}

#[test]
fn sorted_names_have_identical_public_and_private_derivation_bytes_and_receipts() {
    for kind in [1, 2, 3, 4] {
        let input = with_names(&named(kind, &[0, 1, 2], &[0, 1]));
        assert_eq!(
            transform_owned_thread_admission(&input, hash(&input)).unwrap(),
            transform_derived_thread_admission(&input, hash(&input)).unwrap()
        );
    }
}

#[test]
fn internal_name_rows_reject_duplicates_and_indices_outside_the_original_domain() {
    for kind in [1, 2, 3] {
        for indices in [&[2, 1, 2][..], &[0, 0], &[4], &[u32::MAX]] {
            let input = with_names(&named(kind, indices, &[0]));
            assert_eq!(
                transform_derived_thread_admission(&input, hash(&input)).unwrap_err(),
                "rust-child-admission-reencode-failed"
            );
        }
    }
}

#[test]
fn compatibility_does_not_relax_inner_names_or_other_index_spaces() {
    for kind in [2, 3] {
        for inner in [&[1, 0][..], &[0, 0]] {
            let input = with_names(&named(kind, &[3, 0], inner));
            assert_eq!(
                transform_derived_thread_admission(&input, hash(&input)).unwrap_err(),
                "rust-child-admission-reencode-failed"
            );
        }
    }
    let input = with_names(&named(4, &[1, 0], &[]));
    assert_eq!(
        transform_derived_thread_admission(&input, hash(&input)).unwrap_err(),
        "rust-child-admission-reencode-failed"
    );
}

#[test]
fn raw_rows_still_require_complete_bounded_syntax() {
    for kind in [1, 2, 3] {
        // A declared row with no index; an overflowing index; an incomplete
        // string/inner map; and a complete empty map with trailing data.
        for malformed in [&[1][..], &[1, 0xff, 0xff, 0xff, 0xff, 0x10], &[1, 0], &[0, 0]] {
            let mut names = NameSection::new();
            names.raw(kind, malformed);
            let input = with_names(&names);
            assert_eq!(
                transform_derived_thread_admission(&input, hash(&input)).unwrap_err(),
                "rust-child-admission-reencode-failed"
            );
        }
    }
}

#[test]
fn internal_name_compatibility_never_bypasses_preimage_or_executable_shape_checks() {
    let input = with_names(&named(1, &[3, 1], &[]));
    assert_eq!(
        transform_derived_thread_admission(&input, [0; 32]).unwrap_err(),
        "rust-stack-input-preimage-mismatch"
    );
    for (native, correct, expected) in [
        (false, true, "rust-child-admission-native-import-missing"),
        (true, false, "rust-child-admission-native-signature-or-duplicate"),
    ] {
        let input = fixture(native, correct);
        assert_eq!(
            transform_derived_thread_admission(&input, hash(&input)).unwrap_err(),
            expected
        );
    }
}
