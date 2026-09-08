use super::{config, invoke};
use crate::{
    args::{ActivationCommand, CancelArgs, Command, IdArgs},
    operation::Operation,
};
use std::fs;

#[test]
fn absent_identity_defaults_and_explicit_lineage_zero_overrides_are_lossless() {
    let directory = tempfile::tempdir().unwrap();
    let payload = directory.path().join("input");
    fs::write(&payload, b"[]").unwrap();
    let args = invoke(payload.clone());
    let Operation::Invoke(request) =
        crate::invocation::prepare(&Command::Invoke(Box::new(args)), &config())
            .ok()
            .unwrap()
    else {
        panic!("invoke operation")
    };
    assert!(
        request.activation_id.is_none()
            && request.parent_activation_id.is_none()
            && request.root_activation_id.is_none()
    );
    let budget = request.budget.unwrap();
    assert_eq!(
        (budget.cpu_fuel, budget.memory_bytes, budget.log_bytes),
        (100_000_000, 67_108_864, 16_384)
    );
    assert_eq!(budget.wall_time_limit_millis, None);

    let document = directory.path().join("budget.json");
    fs::write(
        &document,
        br#"{"cpuFuel":8,"memoryBytes":9,"wallTimeLimitMillis":10,"logBytes":11}"#,
    )
    .unwrap();
    let mut args = invoke(payload);
    args.activation_id = Some("known".to_owned());
    args.root_activation_id = Some("root".to_owned());
    args.parent_activation_id = Some("parent".to_owned());
    args.deadline_unix_millis = Some(u64::MAX);
    args.budget = Some(document);
    args.cpu_fuel = Some(0);
    args.memory_bytes = Some(0);
    args.wall_time_ms = Some(0);
    args.log_bytes = Some(0);
    args.metadata = vec!["key=value=tail".to_owned()];
    let Operation::Invoke(request) =
        crate::invocation::prepare(&Command::Invoke(Box::new(args)), &config())
            .ok()
            .unwrap()
    else {
        panic!("invoke operation")
    };
    assert_eq!(request.activation_id.as_deref(), Some("known"));
    assert_eq!(request.root_activation_id.as_deref(), Some("root"));
    assert_eq!(request.parent_activation_id.as_deref(), Some("parent"));
    assert_eq!(request.deadline_unix_millis, Some(u64::MAX));
    assert_eq!(request.metadata["key"], "value=tail");
    let budget = request.budget.unwrap();
    assert_eq!(
        (budget.cpu_fuel, budget.memory_bytes, budget.log_bytes),
        (0, 0, 0)
    );
    assert_eq!(budget.wall_time_limit_millis, Some(0));
}

#[test]
fn explicit_invalid_claims_metadata_and_multiple_stdin_fail_locally() {
    for kind in 0..5 {
        let mut args = invoke("-".into());
        match kind {
            0 => args.activation_id = Some(String::new()),
            1 => args.parent_activation_id = Some("parent".to_owned()),
            2 => args.metadata = vec!["a=x".to_owned(), "a=y".to_owned()],
            3 => args.metadata = vec!["LATENT.operator=true".to_owned()],
            _ => args.budget = Some("-".into()),
        }
        // No stdin reader may be opened for these independently invalid arguments.
        assert!(crate::invocation::prepare(&Command::Invoke(Box::new(args)), &config()).is_err());
    }
}

#[test]
fn budget_documents_reject_unknown_duplicate_and_later_phase_dimensions() {
    let directory = tempfile::tempdir().unwrap();
    let budget = directory.path().join("budget.json");
    for document in [
        br#"{"unknown":1}"#.as_slice(),
        br#"{"cpuFuel":1,"cpuFuel":2}"#,
        br#"{"childCalls":1}"#,
        br#"{"memoryBytes":1.5}"#,
        br#"{"wallTimeLimitMillis":300001}"#,
    ] {
        fs::write(&budget, document).unwrap();
        let mut args = invoke(directory.path().join("unread-payload"));
        args.budget = Some(budget.clone());
        assert!(super::super::budget::resolve(&args).is_err());
    }
}

#[test]
fn payload_bytes_are_never_interpreted_as_phase0_controls_and_cancel_is_explicit() {
    let directory = tempfile::tempdir().unwrap();
    let payload = directory.path().join("input");
    let bytes = b"spin\0\xff\n";
    fs::write(&payload, bytes).unwrap();
    let mut args = invoke(payload);
    args.media_type = "text/plain".to_owned();
    let Operation::Invoke(value) =
        crate::invocation::prepare(&Command::Invoke(Box::new(args)), &config())
            .ok()
            .unwrap()
    else {
        panic!("invoke operation")
    };
    assert_eq!(value.payload, bytes);
    assert_eq!(value.media_type, "text/plain");
    let command = Command::Activation(ActivationCommand::Cancel(CancelArgs {
        id: "known".to_owned(),
        reason: String::new(),
    }));
    let Operation::Cancel(value) = crate::invocation::prepare(&command, &config())
        .ok()
        .unwrap()
    else {
        panic!("cancel operation")
    };
    assert_eq!(value.activation_id, "known");
    assert_eq!(value.reason, "");
    assert!(crate::invocation::prepare(
        &Command::Activation(ActivationCommand::Get(IdArgs { id: String::new() })),
        &config()
    )
    .is_err());
}
