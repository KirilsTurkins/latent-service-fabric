use std::collections::BTreeSet;
use std::path::Path;

use crate::error::Failure;
use crate::input::single_stdin;

use super::{
    ActivationCommand, Cli, Command, DeploymentCommand, InvokeArgs, NodeCommand, OutputFormat,
    ReleaseCommand, ServicePageArgs, ValidateCommand,
};

impl Cli {
    pub fn validate(&self) -> Result<(), Failure> {
        if self.quiet && self.output == OutputFormat::Json {
            return Err(Failure::local(
                "conflicting-output-options",
                "Quiet mode cannot be combined with JSON output.",
            ));
        }
        optional(self.profile.as_deref(), 64)?;
        optional(self.endpoint.as_deref(), 256)?;
        optional(self.tenant.as_deref(), 128)?;
        if let Some(path) = &self.config {
            path_argument(path)?;
        }
        match &self.command {
            Command::Validate(
                ValidateCommand::Capsule(args) | ValidateCommand::Deployment(args),
            ) => path_argument(&args.file),
            Command::Release(command) => release(command),
            Command::Deployment(command) => deployment(command),
            Command::Route(_) => Ok(()),
            Command::Invoke(args) => invoke(args),
            Command::Activation(ActivationCommand::Get(args)) => identifier(&args.id, 512),
            Command::Activation(ActivationCommand::Cancel(args)) => {
                identifier(&args.id, 512)?;
                if args.reason.len() > 256 {
                    return Err(invalid());
                }
                Ok(())
            }
            Command::Node(command) => node(command),
        }
    }
}

fn release(command: &ReleaseCommand) -> Result<(), Failure> {
    match command {
        ReleaseCommand::Publish(args) => {
            for path in [&args.manifest, &args.component, &args.contracts] {
                path_argument(path)?;
            }
            single_stdin(&[&args.manifest, &args.component, &args.contracts])
        }
        ReleaseCommand::Get(args) => identifier(&args.digest, 512),
        ReleaseCommand::List(args) => page(args),
    }
}

fn deployment(command: &DeploymentCommand) -> Result<(), Failure> {
    match command {
        DeploymentCommand::Apply(args) => path_argument(&args.file),
        DeploymentCommand::Get(args) => identifier(&args.id, 512),
        DeploymentCommand::Delete(args) => identifier(&args.id, 512),
        DeploymentCommand::List(args) => page(args),
    }
}

fn node(command: &NodeCommand) -> Result<(), Failure> {
    match command {
        NodeCommand::Get(args) => identifier(&args.id, 512),
        NodeCommand::List(args) => {
            optional(args.trust_class.as_deref(), 512)?;
            optional(args.region.as_deref(), 512)?;
            optional(args.zone.as_deref(), 512)?;
            page_token(args.page_token.as_deref(), args.page_size)
        }
    }
}

fn page(args: &ServicePageArgs) -> Result<(), Failure> {
    optional(args.service.as_deref(), 512)?;
    page_token(args.page_token.as_deref(), args.page_size)
}

fn page_token(token: Option<&str>, size: u32) -> Result<(), Failure> {
    if size > 1000 {
        return Err(invalid());
    }
    optional(token, 8192)
}

fn invoke(args: &InvokeArgs) -> Result<(), Failure> {
    for value in [&args.service, &args.contract, &args.function] {
        identifier(value, 512)?;
    }
    for value in [
        &args.route,
        &args.activation_id,
        &args.root_activation_id,
        &args.parent_activation_id,
        &args.idempotency_key,
    ] {
        optional(value.as_deref(), 512)?;
    }
    if args.parent_activation_id.is_some() && args.root_activation_id.is_none() {
        return Err(Failure::local(
            "activation-parent-requires-root",
            "An explicit parent activation requires an explicit root activation.",
        ));
    }
    if args.media_type.is_empty()
        || args.media_type.len() > 512
        || args.media_type.chars().any(char::is_control)
    {
        return Err(invalid());
    }
    path_argument(&args.input)?;
    if let Some(path) = &args.budget {
        path_argument(path)?;
        single_stdin(&[&args.input, path])?;
    }
    if let Some(path) = &args.payload_output {
        path_argument(path)?;
    }
    metadata(&args.metadata)
}

fn metadata(entries: &[String]) -> Result<(), Failure> {
    if entries.len() > 64 {
        return Err(invalid());
    }
    let mut keys = BTreeSet::new();
    let mut bytes = 0_usize;
    for entry in entries {
        let Some((key, value)) = entry.split_once('=') else {
            return Err(invalid());
        };
        if key.is_empty() || key.len() > 4096 || value.len() > 4096 || !keys.insert(key) {
            return Err(invalid());
        }
        bytes = bytes.checked_add(entry.len()).ok_or_else(invalid)?;
        if bytes > 32 * 1024 {
            return Err(invalid());
        }
    }
    Ok(())
}

fn optional(value: Option<&str>, maximum: usize) -> Result<(), Failure> {
    value.map_or(Ok(()), |value| identifier(value, maximum))
}

fn identifier(value: &str, maximum: usize) -> Result<(), Failure> {
    if value.is_empty()
        || value.len() > maximum
        || value
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
    {
        return Err(invalid());
    }
    Ok(())
}

fn path_argument(path: &Path) -> Result<(), Failure> {
    if path.as_os_str().is_empty() || path.as_os_str().len() > 4096 {
        return Err(invalid());
    }
    Ok(())
}

fn invalid() -> Failure {
    Failure::local(
        "invalid-arguments",
        "Command arguments are invalid or exceed their limits.",
    )
}
