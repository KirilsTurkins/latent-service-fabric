use super::*;
use crate::args::dispatcher::{
    DispatcherAction, DispatcherCommand, DispatcherControlArgs, DispatcherOperationArgs,
    DispatcherScope, DispatcherTarget,
};
fn control() -> DispatcherControlArgs {
    DispatcherControlArgs {
        target: DispatcherTarget {
            scope: DispatcherScope::Node,
        },
        operation_id: "original".into(),
        expected_owner_epoch: 9_007_199_254_740_993,
        expected_revision: u64::MAX - 1,
    }
}
#[test]
fn dispatcher_cli_requires_explicit_node_scope_action_and_original_precondition() {
    for args in [
        vec!["latent", "dispatcher", "inspect"],
        vec!["latent", "dispatcher", "inspect", "--scope", "tenant"],
        vec!["latent", "dispatcher", "resume", "--scope", "node"],
        vec![
            "latent",
            "dispatcher",
            "operation",
            "--scope",
            "node",
            "--operation-id",
            "old",
            "--expected-owner-epoch",
            "1",
            "--expected-revision",
            "1",
        ],
    ] {
        assert!(Cli::try_parse_from(args).is_err());
    }
    let cli = Cli::try_parse_from([
        "latent",
        "dispatcher",
        "resume",
        "--scope",
        "node",
        "--operation-id",
        "original",
        "--expected-owner-epoch",
        "1",
        "--expected-revision",
        "0",
    ])
    .unwrap();
    assert!(cli.validate().is_err());
}
#[test]
fn dispatcher_recovery_keeps_lossless_original_epoch_revision_action_and_operation() {
    let command = DispatcherCommand::Resume(control());
    let Operation::Phase4(original) = prepare_dispatcher(&command).unwrap() else {
        panic!("phase4")
    };
    let recovery = recovery(&original).unwrap();
    assert_eq!(recovery["operationId"], "original");
    assert_eq!(recovery["automaticRetry"], false);
    assert_eq!(
        recovery["expectedGeneration"]["ownerEpoch"],
        "9007199254740993"
    );
    assert_eq!(
        recovery["expectedGeneration"]["revision"],
        (u64::MAX - 1).to_string()
    );
    let command = DispatcherCommand::Operation(DispatcherOperationArgs {
        original: control(),
        original_action: DispatcherAction::Resume,
    });
    let Operation::Phase4(lookup) = prepare_dispatcher(&command).unwrap() else {
        panic!("phase4")
    };
    let (Request::ControlDispatcher(original), Request::GetDispatcherOperation(lookup)) =
        (*original, *lookup)
    else {
        panic!("types")
    };
    assert_eq!(lookup.original.as_ref(), Some(original.as_ref()));
    assert_eq!(
        projection::dispatcher_generation(&c::DispatcherGeneration {
            owner_epoch: u64::MAX,
            revision: u64::MAX
        }),
        json!({"ownerEpoch":u64::MAX.to_string(),"revision":u64::MAX.to_string()})
    );
}
