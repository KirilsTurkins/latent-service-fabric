//! Nonqualifying observation of one retained C component and invocation.
//!
//! This module is compiled only by an off-default feature, including explicit
//! all-features builds. Its separate runtime opt-in defaults to false. It does
//! not grant authority or raise limits. I/O may affect the observed result.
use std::io::Write as _;

use latent_activation::ActivationEnvelope;

use crate::component_threading::Authentication;
use crate::development_trap_observer::DevelopmentTrapGuard;

const ORIGINAL_COMPONENT: [u8; 32] = [
    0xc9, 0xd0, 0xfb, 0xa3, 0xa0, 0x1d, 0x87, 0x84, 0xe9, 0xbd, 0x7e, 0xf2, 0x3e, 0x03, 0xa2, 0xab,
    0x85, 0x92, 0x16, 0x22, 0xeb, 0xec, 0xef, 0x59, 0x26, 0x73, 0xea, 0xf4, 0x43, 0x35, 0xe2, 0x05,
];
const PREFIX: &[u8] = b"LSF_C_TIMED_ORIGINAL_TRAP ";
const MAX_EVENT_BYTES: usize = 4096;

fn selected_values(
    enabled: bool,
    activation: &str,
    tenant: &str,
    service: &str,
    contract: &str,
    function: &str,
    authentication: &Authentication,
) -> bool {
    enabled
        && activation == "c-thread-timed-sleep"
        && tenant == "examples"
        && service == "examples/c-thread-runtime"
        && contract == "examples:c-thread-runtime/api@1.0.0"
        && function == "greet"
        && matches!(authentication, Authentication::CVerified(digest) if *digest == ORIGINAL_COMPONENT)
}

pub(crate) fn selected(
    enabled: bool,
    activation: &ActivationEnvelope,
    authentication: &Authentication,
) -> bool {
    selected_values(
        enabled,
        &activation.activation_id.0,
        &activation.target.tenant.0,
        &activation.target.service.0,
        &activation.target.contract.0,
        &activation.target.function.0,
        authentication,
    )
}

/// Report bounded numeric data only; snapshot and output errors are ignored.
pub(crate) fn emit(guard: &DevelopmentTrapGuard<'_>) {
    let Ok(snapshot) = guard.snapshot() else {
        return;
    };
    let Ok(payload) = serde_json::to_vec(&snapshot) else {
        return;
    };
    if PREFIX.len() + payload.len() + 1 > MAX_EVENT_BYTES {
        return;
    }
    let mut event = Vec::with_capacity(PREFIX.len() + payload.len() + 1);
    event.extend_from_slice(PREFIX);
    event.extend_from_slice(&payload);
    event.push(b'\n');
    // A pipe write can perturb timing. This is never a qualification owner.
    let _ = std::io::stderr().lock().write_all(&event);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_selected_authenticated_c_invocation_is_observed() {
        assert!(!crate::WasmtimeConfig::default().development_c_timed_original_trap);
        let valid = Authentication::CVerified(ORIGINAL_COMPONENT);
        let other_component = Authentication::CVerified([0; 32]);
        let other_profile = Authentication::Verified(ORIGINAL_COMPONENT);
        let check = |activation, tenant, service, contract, function, authentication| {
            selected_values(
                true,
                activation,
                tenant,
                service,
                contract,
                function,
                authentication,
            )
        };
        assert!(check(
            "c-thread-timed-sleep",
            "examples",
            "examples/c-thread-runtime",
            "examples:c-thread-runtime/api@1.0.0",
            "greet",
            &valid
        ));
        assert!(!selected_values(
            false,
            "c-thread-timed-sleep",
            "examples",
            "examples/c-thread-runtime",
            "examples:c-thread-runtime/api@1.0.0",
            "greet",
            &valid,
        ));
        for (activation, tenant, service, contract, function, authentication) in [
            (
                "different",
                "examples",
                "examples/c-thread-runtime",
                "examples:c-thread-runtime/api@1.0.0",
                "greet",
                &valid,
            ),
            (
                "c-thread-timed-sleep",
                "other",
                "examples/c-thread-runtime",
                "examples:c-thread-runtime/api@1.0.0",
                "greet",
                &valid,
            ),
            (
                "c-thread-timed-sleep",
                "examples",
                "different",
                "examples:c-thread-runtime/api@1.0.0",
                "greet",
                &valid,
            ),
            (
                "c-thread-timed-sleep",
                "examples",
                "examples/c-thread-runtime",
                "different",
                "greet",
                &valid,
            ),
            (
                "c-thread-timed-sleep",
                "examples",
                "examples/c-thread-runtime",
                "examples:c-thread-runtime/api@1.0.0",
                "different",
                &valid,
            ),
            (
                "c-thread-timed-sleep",
                "examples",
                "examples/c-thread-runtime",
                "examples:c-thread-runtime/api@1.0.0",
                "greet",
                &other_component,
            ),
            (
                "c-thread-timed-sleep",
                "examples",
                "examples/c-thread-runtime",
                "examples:c-thread-runtime/api@1.0.0",
                "greet",
                &other_profile,
            ),
        ] {
            assert!(!check(
                activation,
                tenant,
                service,
                contract,
                function,
                authentication
            ));
        }
    }
}
