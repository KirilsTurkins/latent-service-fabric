//! Local preflight, single-call execution, and process exit behavior.
use crate::{
    args::{self, Cli, Command, OutputFormat},
    client::Session,
    config,
    error::Failure,
    invocation, management,
    output::{self, Category, Outcome},
};
use base64::{engine::general_purpose::STANDARD, Engine};
use clap::{error::ErrorKind, Parser};
use serde_json::json;
use std::{ffi::OsString, fs::OpenOptions, io::Write, path::Path, process::ExitCode};

/// Runs one explicit operator command and returns its stable process exit code.
#[must_use]
pub fn main_entry() -> ExitCode {
    let arguments: Vec<OsString> = std::env::args_os().collect();
    let cli = match Cli::try_parse_from(&arguments) {
        Ok(cli) => cli,
        Err(error)
            if matches!(
                error.kind(),
                ErrorKind::DisplayHelp | ErrorKind::DisplayVersion
            ) =>
        {
            return ExitCode::from(if error.print().is_ok() { 0 } else { 2 });
        }
        Err(_) => {
            let format = if arguments.iter().any(|a| a == "--output=json")
                || arguments
                    .windows(2)
                    .any(|a| a[0] == "--output" && a[1] == "json")
            {
                OutputFormat::Json
            } else {
                OutputFormat::Human
            };
            return exit(output::emit(
                Failure::local(
                    "invalid-arguments",
                    "Invalid command arguments; use --help for the supported syntax.",
                )
                .into(),
                "arguments",
                format,
                false,
            ));
        }
    };
    let command = name(&cli.command);
    let result = match cli.validate() {
        Err(failure) => failure.into(),
        Ok(()) => match &cli.command {
            Command::Package(command) => crate::package::execute(&cli, command),
            Command::Validate(command) => management::validate(command).unwrap_or_else(Into::into),
            _ => match tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
            {
                Ok(runtime) => runtime.block_on(remote(&cli)),
                Err(_) => {
                    Failure::local("runtime-unavailable", "The client runtime could not start.")
                        .into()
                }
            },
        },
    };
    exit(output::emit(result, command, cli.output, cli.quiet))
}
fn exit(code: i32) -> ExitCode {
    ExitCode::from(u8::try_from(code).unwrap_or(2))
}

async fn remote(cli: &Cli) -> Outcome {
    let result = Box::pin(remote_inner(cli)).await;
    let mut outcome = result.unwrap_or_else(Into::into);
    if let Command::Invoke(args) = &cli.command {
        if outcome.data.get("activationId").is_none() {
            outcome.data["activationId"] = json!(args.activation_id);
        }
        if outcome.category == Category::Success {
            if let Some(path) = &args.payload_output {
                if let Err(failure) = save_payload(path, &outcome.data) {
                    outcome.category = Category::LocalError;
                    outcome.error = Some(failure.error);
                    outcome.data["remoteCompleted"] = json!(true);
                }
            }
        }
    }
    outcome
}
async fn remote_inner(cli: &Cli) -> Result<Outcome, Failure> {
    let config = config::resolve(cli)?;
    let operation = if matches!(&cli.command, Command::Invoke(_) | Command::Activation(_)) {
        invocation::prepare(&cli.command, &config)?
    } else {
        management::prepare(&cli.command, &config)?
    };
    if operation.encoded_len()
        > config
            .limits
            .maximum_component_bytes
            .saturating_add(3 * 1024 * 1024)
    {
        return Err(Failure::local(
            "request-limit",
            "The encoded request exceeds the configured limit.",
        ));
    }
    let recovery = management::phase2::RecoveryContext::from_operation(&operation, &config.tenant);
    let result = async {
        let absolute = match &cli.command {
            Command::Invoke(args) => args.deadline_unix_millis,
            _ => None,
        };
        let interrupt_signal = tokio::signal::ctrl_c();
        tokio::pin!(interrupt_signal);
        let session = tokio::select! {
            biased;
            signal = &mut interrupt_signal => return Err(interrupt(signal.is_ok(), false)),
            result = Session::connect(&config, absolute) => result?,
        };
        let is_invocation = operation.is_invocation();
        let future = async {
            if is_invocation {
                invocation::execute(operation, &session).await
            } else {
                management::execute(operation, &session).await
            }
        };
        let result = tokio::select! {
            biased;
            signal = &mut interrupt_signal => Err(interrupt(signal.is_ok(), session.dispatched())),
            result = future => result,
        };
        match result {
            Ok(mut outcome) => {
                outcome.request_dispatched = session.dispatched();
                Ok(outcome)
            }
            Err(mut failure) => {
                failure.request_dispatched |= session.dispatched();
                Err(failure)
            }
        }
    }
    .await;
    match result {
        Ok(mut outcome) => {
            recovery.outcome(&mut outcome);
            Ok(outcome)
        }
        Err(mut failure) => {
            recovery.failure(&mut failure);
            Err(failure)
        }
    }
}
fn interrupt(received: bool, dispatched: bool) -> Failure {
    if received {
        Failure::interrupted(dispatched)
    } else {
        let mut failure = Failure::local(
            "signal-unavailable",
            "The client could not observe interruption.",
        );
        failure.request_dispatched = dispatched;
        failure.outcome_known = !dispatched;
        failure
    }
}
fn save_payload(path: &Path, data: &serde_json::Value) -> Result<(), Failure> {
    let encoded = data["payload"]["data"].as_str().ok_or_else(output_failed)?;
    let payload = STANDARD.decode(encoded).map_err(|_| output_failed())?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|_| output_failed())?;
    file.write_all(&payload)
        .and_then(|()| file.sync_all())
        .map_err(|_| output_failed())
}
fn output_failed() -> Failure {
    Failure::local("payload-output-failed", "The invocation completed, but its payload file could not be written; existing files are not overwritten.")
}
fn name(command: &Command) -> &'static str {
    use args::{
        ActivationCommand as A, DeploymentCommand as D, NodeCommand as N, ReleaseCommand as R,
        RouteCommand as Route, ValidateCommand as V,
    };
    match command {
        Command::Package(command) => command.name(),
        Command::Validate(V::Capsule(_)) => "validate capsule",
        Command::Validate(V::Deployment(_)) => "validate deployment",
        Command::Audit(_) => "audit query",
        Command::Rollout(command) => match command {
            args::rollout::RolloutCommand::Start(_) => "rollout start",
            args::rollout::RolloutCommand::Get(_) => "rollout get",
            args::rollout::RolloutCommand::List(_) => "rollout list",
            args::rollout::RolloutCommand::Operation(_) => "rollout operation",
            args::rollout::RolloutCommand::Advance(_) => "rollout advance",
            args::rollout::RolloutCommand::Pause(_) => "rollout pause",
            args::rollout::RolloutCommand::Resume(_) => "rollout resume",
            args::rollout::RolloutCommand::Abort(_) => "rollout abort",
            args::rollout::RolloutCommand::Evaluate(_) => "rollout evaluate",
            args::rollout::RolloutCommand::Promote(_) => "rollout promote",
            args::rollout::RolloutCommand::Rollback(_) => "rollout rollback",
        },
        Command::Release(R::Lifecycle(_)) => "release lifecycle",
        Command::Release(R::Operation(_)) => "release operation",
        Command::Release(R::PublishPackage(_)) => "release publish-package",
        Command::Release(R::Revoke(_)) => "release revoke",
        Command::Release(R::Retire(_)) => "release retire",
        Command::Release(R::RenewEvidence(_)) => "release renew-evidence",
        Command::Deployment(D::Operation(_)) => "deployment operation",
        Command::Release(R::Publish(_)) => "release publish",
        Command::Release(R::Get(_)) => "release get",
        Command::Release(R::List(_)) => "release list",
        Command::Deployment(D::Apply(_)) => "deployment apply",
        Command::Deployment(D::Get(_)) => "deployment get",
        Command::Deployment(D::List(_)) => "deployment list",
        Command::Deployment(D::Delete(_)) => "deployment delete",
        Command::Route(Route::Get(_)) => "route get",
        Command::Invoke(_) => "invoke",
        Command::Activation(A::Get(_)) => "activation get",
        Command::Activation(A::Cancel(_)) => "activation cancel",
        Command::Node(N::Get(_)) => "node get",
        Command::Node(N::List(_)) => "node list",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn payload_output_preserves_existing_files() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("output");
        let data = json!({"payload":{"data":STANDARD.encode(b"actual bytes\0")}});
        save_payload(&path, &data).unwrap();
        assert!(save_payload(
            &path,
            &json!({"payload":{"data":STANDARD.encode(b"overwrite")}})
        )
        .is_err());
        assert_eq!(std::fs::read(path).unwrap(), b"actual bytes\0");
    }
}
