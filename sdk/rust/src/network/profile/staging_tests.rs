use super::{control, staging};

fn original() -> control::ActivationTreeNode {
    control::ActivationTreeNode {
        received_at_unix_millis: 1000,
        granted_budget: Some(control::ResourceBudget {
            effect_count: 2,
            state_write_bytes: u64::MAX,
            ..control::ResourceBudget::default()
        }),
        transaction_staging: Some(control::TransactionStagingWitness {
            schema_version: 1,
            activation_serial: u64::MAX,
            command_id: "1".repeat(64),
            attempt_id: "2".repeat(64),
            transaction_id: "3".repeat(64),
            publication_id: format!("publication:sha256:{}", "4".repeat(64)),
            staged_mutations: 2,
            captured_intents: 2,
            state_write_bytes: u64::MAX,
            observed_at_unix_millis: u64::MAX,
        }),
        ..control::ActivationTreeNode::default()
    }
}

#[test]
fn staging_projection_preserves_absence_and_maximum_unsigned_original_progress() {
    assert!(staging(&control::ActivationTreeNode::default()).is_ok());
    assert!(staging(&original()).is_ok());
}

#[test]
fn staging_projection_refuses_malformed_identity_versions_bounds_and_missing_original_grant() {
    for field in 0..12 {
        let mut node = original();
        let value = node.transaction_staging.as_mut().unwrap();
        match field {
            0 => value.schema_version = 2,
            1 => value.activation_serial = 0,
            2 => value.command_id = "A".repeat(64),
            3 => value.attempt_id.push('0'),
            4 => value.transaction_id = "secret\nmetadata".into(),
            5 => value.publication_id = format!("sha256:{}", "4".repeat(64)),
            6 => value.staged_mutations = 129,
            7 => value.captured_intents = 0,
            8 => value.captured_intents = 3,
            9 => value.state_write_bytes = 0,
            10 => value.observed_at_unix_millis = 999,
            _ => node.granted_budget = None,
        }
        assert!(staging(&node).is_err(), "field {field}");
    }
    let mut node = original();
    node.granted_budget.as_mut().unwrap().state_write_bytes = 1;
    assert!(staging(&node).is_err());
}
