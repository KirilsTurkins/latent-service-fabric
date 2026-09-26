use crate::activation_runner::{failure_for_platform_error, outcome_consumption};
use latent_activation::ActivationOutcome;
use latent_core::{Metadata, PlatformErrorCode};

/// Bound retained capacities before moving a child result into parent-owned
/// canonical lowering. This also limits traversal of backend-supplied metadata.
pub(super) fn bounded(outcome: ActivationOutcome, maximum_bytes: usize) -> ActivationOutcome {
    let mut bytes = Bytes(maximum_bytes);
    let valid = bytes.take(512)
        && match &outcome {
            ActivationOutcome::Succeeded(value) => {
                value.committed_state_version.is_none()
                    && value.effect_ids.is_empty()
                    && bytes.take(value.output.capacity())
                    && bytes.text(&value.output_media_type)
                    && bytes.metadata(&value.metadata)
            }
            ActivationOutcome::DeclaredError { error, .. } => {
                bytes.text(&error.code)
                    && bytes.text(&error.message)
                    && bytes.take(error.payload.capacity())
                    && bytes.text(&error.media_type)
                    && bytes.metadata(&error.metadata)
            }
            ActivationOutcome::Failed { error, .. } => {
                bytes.text(&error.message)
                    && error.details.len() <= 16
                    && bytes.take(error.details.capacity().saturating_mul(128))
                    && error
                        .details
                        .iter()
                        .all(|detail| bytes.text(&detail.kind) && bytes.metadata(&detail.fields))
            }
        };
    if valid {
        return outcome;
    }
    let consumption = outcome_consumption(&outcome);
    // Destroy oversized payloads while their original child owner is retained.
    drop(outcome);
    failure_for_platform_error(
        super::error(
            PlatformErrorCode::ResourceExhausted,
            "local service result exceeds retained output capacity",
        ),
        consumption,
    )
}
struct Bytes(usize);
impl Bytes {
    fn take(&mut self, amount: usize) -> bool {
        let Some(left) = self.0.checked_sub(amount) else {
            return false;
        };
        self.0 = left;
        true
    }
    fn text(&mut self, value: &String) -> bool {
        value.len() <= 4096 && self.take(value.capacity().saturating_add(32))
    }
    fn metadata(&mut self, values: &Metadata) -> bool {
        values.len() <= 128
            && self.take(values.len().saturating_mul(96))
            && values
                .iter()
                .all(|(key, value)| self.text(key) && self.text(value))
    }
}

#[cfg(test)]
mod tests {
    use super::bounded;
    use latent_activation::{ActivationOutcome, ActivationSuccess};
    use latent_core::{BudgetConsumption, Metadata, PlatformErrorCode};
    fn output(bytes: Vec<u8>, metadata: Metadata) -> ActivationOutcome {
        ActivationOutcome::Succeeded(ActivationSuccess {
            output: bytes,
            output_media_type: "application/json".into(),
            consumption: BudgetConsumption::default(),
            committed_state_version: None,
            effect_ids: vec![],
            metadata,
        })
    }
    #[test]
    fn result_transfer_counts_unused_capacity_and_bounds_metadata_traversal() {
        assert!(matches!(
            bounded(output(b"true".to_vec(), Metadata::new()), 1024),
            ActivationOutcome::Succeeded(_)
        ));
        for value in [
            output(Vec::with_capacity(2048), Metadata::new()),
            output(
                vec![],
                (0..129).map(|n| (n.to_string(), "value".into())).collect(),
            ),
        ] {
            assert!(
                matches!(bounded(value, 1024), ActivationOutcome::Failed { error, .. }
                if error.code == PlatformErrorCode::ResourceExhausted)
            );
        }
    }
}
