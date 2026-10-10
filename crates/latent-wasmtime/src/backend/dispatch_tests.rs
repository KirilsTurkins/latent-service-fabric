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

#[test]
fn result_codec_limit_keeps_only_the_closed_producer_observation() {
    use latent_core::diagnostic::{ActivationDiagnostic, DiagnosticReason, DiagnosticStage};
    use latent_core::BudgetConsumption;
    use latent_executor::GuestOutcome;
    use wasmtime::component::{Type, Val};

    let encoded = crate::values::encode_result(
        &[Type::String],
        &[Val::String("too-long".into())],
        crate::ValueCodecLimits {
            max_string_bytes: 4,
            ..crate::ValueCodecLimits::default()
        },
    );
    let Err(mut error) = encoded else {
        panic!("the actual output codec must reject this string");
    };
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    let observation = ActivationDiagnostic::new(
        DiagnosticStage::Execution,
        DiagnosticReason::ValueAllocationLimit,
    );
    assert_eq!(
        ActivationDiagnostic::from_error(&error),
        Some(observation.clone())
    );
    error.details.push(latent_core::ErrorDetail {
        kind: "private-host-context".into(),
        fields: [("payload".into(), "private-guest-value".into())].into(),
    });
    let consumption = BudgetConsumption {
        cpu_fuel: 17,
        peak_memory_bytes: 23,
        wall_time_micros: 29,
        ..BudgetConsumption::default()
    };
    let classified = super::classify_call_result(
        Ok(()),
        Some(Err(error)),
        &crate::containment::StopControl::new(None, None),
        false,
        consumption.clone(),
        None,
    )
    .unwrap();
    let GuestOutcome::Trapped {
        trap,
        consumption: actual,
    } = classified
    else {
        panic!("a codec rejection must keep its guest trap disposition");
    };
    assert_eq!(trap.code, "result-limit-exceeded");
    assert_eq!(trap.diagnostic, Some(observation));
    assert_eq!(trap.metadata["result-codec-error"], "ResourceExhausted");
    assert_eq!(trap.metadata.len(), 1);
    assert!(trap.guest_backtrace.is_empty());
    assert_eq!(actual, consumption);
    assert!(!format!("{trap:?}").contains("private"));
}

#[test]
fn result_codec_untyped_and_invalid_details_stay_unclassified() {
    use latent_core::diagnostic::ActivationDiagnostic;
    use latent_core::{ErrorDetail, Metadata, PlatformError};
    use latent_executor::GuestOutcome;

    let mut hostile = crate::containment::platform_error(
        PlatformErrorCode::ResourceExhausted,
        "Execution ValueAllocationLimit reason=2 configured_bound=4096",
        false,
    );
    hostile.details.push(ErrorDetail {
        kind: ActivationDiagnostic::DETAIL_KIND.into(),
        fields: Metadata::from([
            ("stage".into(), "5".into()),
            ("reason".into(), u32::MAX.to_string()),
            ("payload".into(), "private-value".into()),
        ]),
    });
    let errors: [PlatformError; 3] = [
        crate::containment::platform_error(
            PlatformErrorCode::ResourceExhausted,
            "invocation-value-limit",
            false,
        ),
        hostile,
        crate::containment::platform_error(
            PlatformErrorCode::Internal,
            "invalid-component-result",
            false,
        ),
    ];
    for error in errors {
        let resource_limit = error.code == PlatformErrorCode::ResourceExhausted;
        let classified = super::classify_call_result(
            Ok(()),
            Some(Err(error)),
            &crate::containment::StopControl::new(None, None),
            false,
            latent_core::BudgetConsumption::default(),
            None,
        )
        .unwrap();
        let GuestOutcome::Trapped { trap, .. } = classified else {
            panic!("an untyped codec failure must stay a guest trap");
        };
        assert_eq!(
            trap.code,
            if resource_limit {
                "result-limit-exceeded"
            } else {
                "invalid-component-result"
            }
        );
        assert!(trap.diagnostic.is_none());
        assert!(!format!("{trap:?}").contains("private"));
    }
}

#[test]
fn accounting_failure_keeps_the_original_observation_and_consumption() {
    use latent_core::diagnostic::{
        ActivationDiagnostic, DiagnosticProfile, DiagnosticReason, DiagnosticStage,
    };
    use latent_core::BudgetConsumption;
    use latent_executor::GuestOutcome;

    let mut observation = ActivationDiagnostic::new(
        DiagnosticStage::Execution,
        DiagnosticReason::GuestResourceExhausted,
    );
    observation.profile = Some(DiagnosticProfile::WasmtimeServiceValuesV1);
    observation.profile_digest = Some([0xff; 32]);
    observation.configured_bound = Some(0);
    observation.calculated_requirement = Some(u64::MAX);
    let error = observation
        .clone()
        .attach(crate::containment::platform_error(
            PlatformErrorCode::ResourceExhausted,
            "budget-accounting-failed",
            false,
        ));
    let consumption = BudgetConsumption {
        cpu_fuel: 17,
        peak_memory_bytes: 23,
        wall_time_micros: 29,
        ..BudgetConsumption::default()
    };
    let classified = super::classify_call_result(
        Err(wasmtime::Error::msg("superseded-private-backtrace")),
        None,
        &crate::containment::StopControl::new(None, None),
        false,
        consumption.clone(),
        Some(error),
    )
    .unwrap();
    let GuestOutcome::Trapped {
        trap,
        consumption: actual,
    } = classified
    else {
        panic!("accounting failure must preserve its guest trap disposition");
    };
    assert_eq!(trap.code, "budget-accounting-failed");
    assert_eq!(trap.diagnostic, Some(observation));
    assert!(trap.metadata.is_empty());
    assert!(trap.guest_backtrace.is_empty());
    assert_eq!(actual, consumption);
    assert!(!format!("{trap:?}").contains("private"));
}
