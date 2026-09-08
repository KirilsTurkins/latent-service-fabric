use clap::{CommandFactory, Parser};

use super::{ActivationCommand, Cli, Command, DeploymentCommand, OutputFormat};

fn parse(arguments: &[&str]) -> Cli {
    Cli::try_parse_from(arguments).unwrap_or_else(|_| panic!("valid test command"))
}

#[test]
fn grammar_has_consistent_leaf_help_and_local_validation_needs_no_profile() {
    Cli::command().debug_assert();
    for command in [
        vec!["latent", "--help"],
        vec!["latent", "release", "publish", "--help"],
        vec!["latent", "activation", "cancel", "--help"],
    ] {
        let error = Cli::try_parse_from(command).err().expect("help response");
        assert_eq!(error.kind(), clap::error::ErrorKind::DisplayHelp);
    }
    let cli = parse(&["latent", "validate", "capsule", "capsule.json"]);
    assert!(cli.config.is_none());
    assert!(cli.validate().is_ok());
}

#[test]
fn generation_and_invocation_identity_preserve_absence_and_explicit_zero() {
    let absent = parse(&["latent", "deployment", "apply", "deployment.json"]);
    let Command::Deployment(DeploymentCommand::Apply(args)) = absent.command else {
        panic!("apply command");
    };
    assert_eq!(args.expected_generation, None);
    let zero = parse(&[
        "latent",
        "deployment",
        "apply",
        "deployment.json",
        "--expected-generation",
        "0",
    ]);
    let Command::Deployment(DeploymentCommand::Apply(args)) = zero.command else {
        panic!("apply command");
    };
    assert_eq!(args.expected_generation, Some(0));
    let cli = invocation(&["--cpu-fuel", "0", "--wall-time-ms", "0"]);
    let Command::Invoke(args) = cli.command else {
        panic!("invoke command");
    };
    assert_eq!(args.activation_id, None);
    assert_eq!(args.root_activation_id, None);
    assert_eq!(args.parent_activation_id, None);
    assert_eq!(args.cpu_fuel, Some(0));
    assert_eq!(args.wall_time_ms, Some(0));
}

fn invocation(extra: &[&str]) -> Cli {
    let mut arguments = vec![
        "latent",
        "invoke",
        "--service",
        "echo",
        "--contract",
        "examples:echo/api@0.1.0",
        "--function",
        "echo",
        "--input",
        "payload.json",
    ];
    arguments.extend_from_slice(extra);
    parse(&arguments)
}

#[test]
fn identity_and_metadata_rejection_precede_any_input_read() {
    for extra in [
        vec!["--activation-id", ""],
        vec!["--root-activation-id", ""],
        vec!["--parent-activation-id", "parent"],
        vec!["--metadata", "key=one", "--metadata", "key=two"],
        vec!["--metadata", "missing-delimiter"],
    ] {
        assert!(invocation(&extra).validate().is_err());
    }
    assert!(invocation(&[
        "--activation-id",
        "caller",
        "--root-activation-id",
        "opaque-root",
        "--parent-activation-id",
        "opaque-parent",
        "--metadata",
        "guest.key=a=b",
    ])
    .validate()
    .is_ok());
}

#[test]
fn ambiguous_output_and_multiple_stdin_are_rejected() {
    let json = parse(&[
        "latent",
        "--output",
        "json",
        "--quiet",
        "activation",
        "get",
        "a",
    ]);
    assert!(json.validate().is_err());
    assert_eq!(json.output, OutputFormat::Json);
    assert!(parse(&[
        "latent",
        "--output",
        "human",
        "--quiet",
        "activation",
        "get",
        "a"
    ])
    .validate()
    .is_ok());
    let multiple = parse(&[
        "latent",
        "release",
        "publish",
        "--manifest",
        "-",
        "--component",
        "-",
        "--contracts",
        "contracts.json",
    ]);
    assert!(multiple.validate().is_err());
}

#[test]
fn cancellation_and_paging_limits_are_enforced_locally() {
    let cli = parse(&["latent", "activation", "cancel", "known-id"]);
    let Command::Activation(ActivationCommand::Cancel(args)) = cli.command else {
        panic!("cancel command");
    };
    assert_eq!(args.reason, "operator cancellation");
    assert!(Cli::try_parse_from(["latent", "deployment", "list", "--page-size", "1001"]).is_err());
    assert!(Cli::try_parse_from(["latent", "--rpc-timeout-ms", "0", "node", "list"]).is_err());
    assert!(Cli::try_parse_from(["latent", "invoke", "--retry"]).is_err());
    let oversized = "x".repeat(513);
    assert!(parse(&["latent", "activation", "get", &oversized])
        .validate()
        .is_err());
}
