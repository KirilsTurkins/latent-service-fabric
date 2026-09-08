use std::collections::HashMap;

use crate::{
    args::{ActivationCommand, Command, InvokeArgs},
    config::ResolvedConfig,
    error::Failure,
    input,
    operation::Operation,
};

use super::{bounds, budget, invalid, proto};

pub(super) fn operation(command: &Command, config: &ResolvedConfig) -> Result<Operation, Failure> {
    match command {
        Command::Invoke(args) => invoke(args, config).map(Operation::Invoke),
        Command::Activation(ActivationCommand::Get(args)) => {
            valid_identifier(&args.id)?;
            Ok(Operation::GetActivation(proto::GetActivationRequest {
                activation_id: args.id.clone(),
            }))
        }
        Command::Activation(ActivationCommand::Cancel(args)) => {
            valid_identifier(&args.id)?;
            if args.reason.len() > 256 || args.reason.chars().any(char::is_control) {
                return Err(invalid());
            }
            Ok(Operation::Cancel(proto::CancelRequest {
                activation_id: args.id.clone(),
                reason: args.reason.clone(),
            }))
        }
        _ => Err(invalid()),
    }
}

fn invoke(args: &InvokeArgs, config: &ResolvedConfig) -> Result<proto::InvokeRequest, Failure> {
    for value in [
        &config.tenant,
        &args.service,
        &args.contract,
        &args.function,
    ]
    .into_iter()
    .chain(
        [
            args.route.as_ref(),
            args.activation_id.as_ref(),
            args.root_activation_id.as_ref(),
            args.parent_activation_id.as_ref(),
            args.idempotency_key.as_ref(),
        ]
        .into_iter()
        .flatten(),
    ) {
        valid_identifier(value)?;
    }
    if !bounds::media(&args.media_type)
        || (args.parent_activation_id.is_some() && args.root_activation_id.is_none())
    {
        return Err(invalid());
    }
    let metadata = metadata(&args.metadata)?;
    let paths: Vec<_> = std::iter::once(args.input.as_path())
        .chain(args.budget.as_deref())
        .collect();
    input::single_stdin(&paths)?;
    let budget = budget::resolve(args)?;
    let payload = input::read(&args.input, config.limits.maximum_payload_bytes, "payload")?;
    Ok(proto::InvokeRequest {
        activation_id: args.activation_id.clone(),
        parent_activation_id: args.parent_activation_id.clone(),
        root_activation_id: args.root_activation_id.clone(),
        target: Some(proto::InvocationTarget {
            tenant: config.tenant.clone(),
            service: args.service.clone(),
            contract: args.contract.clone(),
            function: args.function.clone(),
            route: args.route.clone(),
        }),
        payload,
        media_type: args.media_type.clone(),
        deadline_unix_millis: args.deadline_unix_millis,
        priority: u32::from(args.priority),
        idempotency_key: args.idempotency_key.clone(),
        budget: Some(budget),
        metadata,
    })
}

fn valid_identifier(value: &str) -> Result<(), Failure> {
    if bounds::identifier(value, 512) {
        Ok(())
    } else {
        Err(invalid())
    }
}

fn metadata(entries: &[String]) -> Result<HashMap<String, String>, Failure> {
    if entries.len() > 64 {
        return Err(invalid());
    }
    let mut bytes = 0_usize;
    for entry in entries {
        bytes = bytes.checked_add(entry.len()).ok_or_else(invalid)?;
        if bytes > 32 * 1024 {
            return Err(invalid());
        }
        let (key, value) = entry.split_once('=').ok_or_else(invalid)?;
        if !bounds::identifier(key, 512)
            || value.len() > 4096
            || key.to_ascii_lowercase().starts_with("latent.")
        {
            return Err(invalid());
        }
    }
    let mut metadata = HashMap::with_capacity(entries.len());
    for entry in entries {
        let (key, value) = entry.split_once('=').ok_or_else(invalid)?;
        if metadata.insert(key.to_owned(), value.to_owned()).is_some() {
            return Err(invalid());
        }
    }
    Ok(metadata)
}
