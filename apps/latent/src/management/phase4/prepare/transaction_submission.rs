//! Fresh execution uses the selected tenant and original input/preconditions.
use super::{decode, decode_bounded, invalid};
use crate::{
    args::phase4::{TransactionCallArgs, TransactionInvokeArgs, TransactionQueryArgs},
    config::ResolvedConfig,
    error::Failure,
    input,
    invocation::budget,
};
use latent_core::transaction_contract::{KEY_BYTES, VALUE_BYTES};
use latent_rpc::{invocation::v1 as i, phase4, transaction::v1 as t};
use serde::Deserialize;
use std::path::Path;

pub(super) fn invoke(
    args: &TransactionInvokeArgs,
    config: &ResolvedConfig,
) -> Result<phase4::Request, Failure> {
    let paths: Vec<_> = [args.call.input.as_path(), args.call.budget.as_path()]
        .into_iter()
        .chain(args.expected_versions.as_deref())
        .chain(args.retry_attempt.as_deref())
        .collect();
    input::single_stdin(&paths)?;
    let expected_versions = args
        .expected_versions
        .as_deref()
        .map(versions)
        .transpose()?
        .unwrap_or_default();
    let retry_attempt = args.retry_attempt.as_deref().map(retry).transpose()?;
    Ok(t::InvokeCommandRequest {
        profile: Some(phase4::current_profile()),
        invocation: Some(invocation(&args.call, config)?),
        command: Some(t::CommandSelector {
            namespace: Some(namespace(&args.call, config)),
            operation: args.call.function.clone(),
            entity: args.call.entity.clone(),
            client_key: args.client_key.clone(),
            shared_recovery_scope: args.shared_recovery_scope.clone(),
        }),
        input_format: "lsf-wit-values-v1".into(),
        expected_versions,
        retry_attempt,
    }
    .into())
}

pub(super) fn query(
    args: &TransactionQueryArgs,
    config: &ResolvedConfig,
) -> Result<phase4::Request, Failure> {
    input::single_stdin(&[&args.call.input, &args.call.budget])?;
    let minimum_view_version = args
        .minimum_view_version
        .as_deref()
        .map(decode)
        .transpose()?;
    let invocation = invocation(&args.call, config)?;
    let budget = invocation
        .budget
        .as_ref()
        .expect("explicit transaction budget");
    if budget.state_write_bytes != 0 || budget.effect_count != 0 {
        return Err(invalid());
    }
    Ok(t::QueryRequest {
        profile: Some(phase4::current_profile()),
        invocation: Some(invocation),
        namespace: Some(namespace(&args.call, config)),
        entity: args.call.entity.clone(),
        minimum_view_version,
    }
    .into())
}

fn invocation(
    call: &TransactionCallArgs,
    config: &ResolvedConfig,
) -> Result<i::InvokeRequest, Failure> {
    let budget = budget::transaction(&call.budget)?;
    let ceiling = config.limits.maximum_payload_bytes.min(VALUE_BYTES);
    let payload = input::read(&call.input, ceiling, "payload")?;
    Ok(i::InvokeRequest {
        target: Some(i::InvocationTarget {
            tenant: config.tenant.clone(),
            service: call.service.clone(),
            contract: call.contract.clone(),
            function: call.function.clone(),
            route: call.route.clone(),
        }),
        payload,
        media_type: "application/vnd.latent.wit-values.v1+json".into(),
        budget: Some(budget),
        ..Default::default()
    })
}

fn namespace(call: &TransactionCallArgs, config: &ResolvedConfig) -> t::NamespaceSelector {
    t::NamespaceSelector {
        tenant: config.tenant.clone(),
        namespace: call.namespace.clone(),
        incarnation: call.incarnation.clone(),
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct StateExpectation {
    key: String,
    version: Option<String>,
    absent: Option<bool>,
}

fn versions(path: &Path) -> Result<Vec<t::ExpectedVersion>, Failure> {
    let bytes = input::read(path, 256 * 1024, "existing state expectations")?;
    let rows: Vec<StateExpectation> = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
    if rows.len() > phase4::MAX_PAGE_ENTRIES {
        return Err(invalid());
    }
    rows.into_iter()
        .map(|row| {
            use t::expected_version::Expectation;
            let expectation = match (row.version, row.absent) {
                (Some(version), None) => Expectation::Version(decode(&version)?),
                (None, Some(true)) => Expectation::Absent(true),
                _ => return Err(invalid()),
            };
            Ok(t::ExpectedVersion {
                key: decode_bounded(&row.key, KEY_BYTES)?,
                expectation: Some(expectation),
            })
        })
        .collect()
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Retry {
    request_id: String,
    expected_abort: Abort,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Abort {
    command_id: String,
    attempt_id: String,
    transaction_id: String,
    owner_fence: String,
}

fn retry(path: &Path) -> Result<t::RetryAttempt, Failure> {
    let bytes = input::read(path, 4096, "original abort proof")?;
    let input: Retry = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
    Ok(t::RetryAttempt {
        request_id: input.request_id,
        expected_abort: Some(t::AbortFence {
            command_id: input.expected_abort.command_id,
            attempt_id: input.expected_abort.attempt_id,
            transaction_id: input.expected_abort.transaction_id,
            owner_fence: decode(&input.expected_abort.owner_fence)?,
        }),
    })
}
