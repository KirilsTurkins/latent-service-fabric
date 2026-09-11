use std::collections::BTreeSet;

use latent_core::{CapabilityId, PlatformErrorCode};
use latent_executor::BoundImport;

use super::WasmtimeBackend;
use crate::surface::{CONTEXT_IMPORT, LOG_IMPORT, MONOTONIC_CLOCK_IMPORT, WALL_CLOCK_IMPORT};

fn binding(contract: &str) -> BoundImport {
    BoundImport {
        capability: CapabilityId("activation-capability".to_owned()),
        contract: contract.to_owned(),
        opaque_handle: "fresh-handle".to_owned(),
    }
}

#[test]
fn every_order_of_the_four_actual_imports_is_accepted_without_an_order_contract() {
    let names = [
        CONTEXT_IMPORT,
        LOG_IMPORT,
        MONOTONIC_CLOCK_IMPORT,
        WALL_CLOCK_IMPORT,
    ];
    let required: BTreeSet<_> = names.into_iter().map(str::to_owned).collect();
    let mut checked = 0;
    for a in 0..4 {
        for b in 0..4 {
            for c in 0..4 {
                for d in 0..4 {
                    if a == b || a == c || a == d || b == c || b == d || c == d {
                        continue;
                    }
                    let imports = [a, b, c, d].map(|index| binding(names[index]));
                    WasmtimeBackend::validate_bound_imports(&imports, &required).unwrap();
                    checked += 1;
                }
            }
        }
    }
    assert_eq!(checked, 24);
    WasmtimeBackend::validate_bound_imports(&[], &BTreeSet::new()).unwrap();
    WasmtimeBackend::validate_bound_imports(
        &[binding(CONTEXT_IMPORT)],
        &[CONTEXT_IMPORT.to_owned()].into(),
    )
    .unwrap();
}

#[test]
fn duplicate_missing_extra_foreign_and_empty_bindings_keep_the_same_error() {
    let required = [CONTEXT_IMPORT.to_owned(), LOG_IMPORT.to_owned()].into();
    let mut empty = binding(LOG_IMPORT);
    empty.opaque_handle.clear();
    let invalid = [
        vec![binding(CONTEXT_IMPORT), binding(CONTEXT_IMPORT)],
        vec![binding(CONTEXT_IMPORT)],
        vec![
            binding(CONTEXT_IMPORT),
            binding(LOG_IMPORT),
            binding(WALL_CLOCK_IMPORT),
        ],
        vec![binding(CONTEXT_IMPORT), binding(WALL_CLOCK_IMPORT)],
        vec![binding(CONTEXT_IMPORT), empty],
        Vec::new(),
    ];
    for imports in invalid {
        let error = WasmtimeBackend::validate_bound_imports(&imports, &required).unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
        assert_eq!(
            error.message,
            "execution request does not bind the prepared component's imports"
        );
        assert!(!error.retryable);
        assert!(error.details.is_empty());
    }
    assert!(
        WasmtimeBackend::validate_bound_imports(&[binding(CONTEXT_IMPORT)], &BTreeSet::new())
            .is_err()
    );
}
