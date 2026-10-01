use super::invalid;
use crate::{
    args::phase4::{
        CommandArgs, EffectArgs, LookupArgs, NamespaceArgs, NamespaceMutationArgs, StateCommand,
        TransactionCommand,
    },
    config::ResolvedConfig,
    error::Failure,
    input,
    operation::Operation,
};
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_rpc::{
    control::v1 as c,
    phase4::{self, Request},
    transaction::v1 as t,
};
use serde::Deserialize;
use std::path::Path;
mod dispatcher;
pub use dispatcher::prepare_dispatcher;

fn target(args: &NamespaceArgs, config: &ResolvedConfig) -> c::InspectNamespaceRequest {
    c::InspectNamespaceRequest {
        profile: Some(phase4::current_profile()),
        namespace: Some(t::NamespaceSelector {
            tenant: config.tenant.clone(),
            namespace: args.namespace.clone(),
            incarnation: args.incarnation.clone(),
        }),
        authorization_publication: Some(c::PublicationRef {
            id: args.authorization_publication.clone(),
            tenant: config.tenant.clone(),
        }),
    }
}
fn command(args: &CommandArgs, config: &ResolvedConfig) -> t::CommandSelector {
    t::CommandSelector {
        namespace: target(&args.target, config).namespace,
        operation: args.operation.clone(),
        entity: args.entity.clone(),
        client_key: args.client_key.clone(),
        shared_recovery_scope: args.shared_recovery_scope.clone(),
    }
}
fn publication(args: &CommandArgs, config: &ResolvedConfig) -> Option<c::PublicationRef> {
    target(&args.target, config).authorization_publication
}
fn lookup(args: &LookupArgs, config: &ResolvedConfig) -> t::LookupCommandRequest {
    t::LookupCommandRequest {
        profile: Some(phase4::current_profile()),
        command: Some(command(&args.command, config)),
        attempt_id: args.attempt_id.clone(),
        authorization_publication: publication(&args.command, config),
    }
}
fn effect(args: &EffectArgs, config: &ResolvedConfig) -> t::GetEffectRequest {
    t::GetEffectRequest {
        profile: Some(phase4::current_profile()),
        command: Some(command(&args.command, config)),
        effect_id: args.effect_id.clone(),
        authorization_publication: publication(&args.command, config),
    }
}
fn finish(request: Request) -> Result<Operation, Failure> {
    request.validate().map_err(|_| invalid())?;
    Ok(Operation::Phase4(Box::new(request)))
}
pub fn prepare_state(
    command: &StateCommand,
    config: &ResolvedConfig,
) -> Result<Operation, Failure> {
    command.validate()?;
    let request = match command {
        StateCommand::Inspect(args) => Request::from(target(args, config)),
        StateCommand::Create(args) => Request::from(mutation(
            &args.mutation,
            c::NamespaceMutationKind::Create,
            Some(configuration(&args.configuration)?),
            config,
        )),
        StateCommand::Recreate(args) => Request::from(mutation(
            &args.mutation,
            c::NamespaceMutationKind::Recreate,
            Some(configuration(&args.configuration)?),
            config,
        )),
        StateCommand::Quiesce(args) => Request::from(mutation(
            args,
            c::NamespaceMutationKind::Quiesce,
            None,
            config,
        )),
        StateCommand::Retire(args) => Request::from(mutation(
            args,
            c::NamespaceMutationKind::Retire,
            None,
            config,
        )),
        StateCommand::Destroy(args) => Request::from(mutation(
            args,
            c::NamespaceMutationKind::Destroy,
            None,
            config,
        )),
        StateCommand::Operation(args) => Request::from(c::GetStateOperationReceiptRequest {
            namespace: Some(target(&args.target, config)),
            operation_id: args.operation_id.clone(),
            original_effect_plan: None,
        }),
        StateCommand::Entities(args) => Request::from(c::SelectEntityRequest {
            namespace: Some(target(&args.target, config)),
            prefix: args.prefix.as_deref().map(decode).transpose()?,
            page: Some(t::PageRequest {
                limit: args.limit,
                cursor: args.cursor.as_deref().map(decode).transpose()?,
            }),
        }),
    };
    finish(request)
}
fn mutation(
    args: &NamespaceMutationArgs,
    kind: c::NamespaceMutationKind,
    configuration: Option<c::NamespaceConfiguration>,
    config: &ResolvedConfig,
) -> c::MutateNamespaceRequest {
    c::MutateNamespaceRequest {
        namespace: Some(target(&args.target, config)),
        operation_id: args.operation_id.clone(),
        mutation: kind as i32,
        expected_generation: Some(args.expected_generation),
        configuration,
    }
}
pub fn prepare_transaction(
    command_args: &TransactionCommand,
    config: &ResolvedConfig,
) -> Result<Operation, Failure> {
    command_args.validate()?;
    let request = match command_args {
        TransactionCommand::Lookup(args) => Request::from(lookup(args, config)),
        TransactionCommand::Commit(args) => Request::from(t::LookupCommitRequest {
            profile: Some(phase4::current_profile()),
            command: Some(command(&args.command, config)),
            receipt_id: args.receipt_id.clone(),
            authorization_publication: publication(&args.command, config),
        }),
        TransactionCommand::Effect(args) => Request::from(effect(args, config)),
        TransactionCommand::EffectHistory(args) => Request::from(t::ListEffectHistoryRequest {
            effect: Some(effect(&args.effect, config)),
            page: Some(t::PageRequest {
                limit: args.limit,
                cursor: args.cursor.as_deref().map(decode).transpose()?,
            }),
        }),
        TransactionCommand::Cancel(args) => Request::from(t::CancelCommandRequest {
            command: Some(lookup(&args.lookup, config)),
            reason: args.reason.clone(),
        }),
    };
    finish(request)
}
fn decode(value: &str) -> Result<Vec<u8>, Failure> {
    if value.len() > 344 {
        return Err(invalid());
    }
    let bytes = STANDARD.decode(value).map_err(|_| invalid())?;
    if STANDARD.encode(&bytes) != value || bytes.len() > 256 {
        return Err(invalid());
    }
    Ok(bytes)
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Configuration {
    state_schema: String,
    quota: Quota,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Quota {
    state_keys: String,
    state_bytes: String,
    result_rows: String,
    result_bytes: String,
    effect_rows: String,
    effect_bytes: String,
    payload_bytes: String,
    recovery_bytes: String,
}
fn decimal(value: &str) -> Result<u64, Failure> {
    let v = value.parse::<u64>().map_err(|_| invalid())?;
    if v.to_string() != value {
        return Err(invalid());
    }
    Ok(v)
}
fn configuration(path: &Path) -> Result<c::NamespaceConfiguration, Failure> {
    let bytes = input::read(path, 16 * 1024, "namespace-configuration")?;
    let value: Configuration = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
    Ok(c::NamespaceConfiguration {
        state_schema: value.state_schema,
        quota: Some(c::NamespaceQuota {
            state_keys: decimal(&value.quota.state_keys)?,
            state_bytes: decimal(&value.quota.state_bytes)?,
            result_rows: decimal(&value.quota.result_rows)?,
            result_bytes: decimal(&value.quota.result_bytes)?,
            effect_rows: decimal(&value.quota.effect_rows)?,
            effect_bytes: decimal(&value.quota.effect_bytes)?,
            payload_bytes: decimal(&value.quota.payload_bytes)?,
            recovery_bytes: decimal(&value.quota.recovery_bytes)?,
        }),
    })
}
