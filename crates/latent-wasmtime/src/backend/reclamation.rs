//! Final ownership release follows native error destruction, including unwind.

use std::time::Instant;

use crate::timing::Phase0InvocationTiming;

pub(super) fn finish<R, P, O>(
    runtime: R,
    permit: P,
    timing: &mut Phase0InvocationTiming,
    classify: impl FnOnce() -> O,
) -> O {
    // Tuple fields drop in declaration order even when classification unwinds:
    // the native runtime and its charge always precede the active-use permit.
    let owners = (runtime, permit);
    let classification_started = Instant::now();
    let outcome = classify();
    timing.outcome_classification_micros = super::elapsed_micros(classification_started);

    // Backtraces may hold compiled images until classification destroys them.
    // Sum actual drop spans without including the intervening classification.
    let reclamation_started = Instant::now();
    drop(owners);
    timing.activation_resource_reclamation_micros = timing
        .activation_resource_reclamation_micros
        .saturating_add(super::elapsed_micros(reclamation_started));
    outcome
}
