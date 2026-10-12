use super::{error, Arc, PlatformError, PlatformErrorCode, TransactionInstallation};
use latent_core::{
    transaction_contract::{ExpectedVersion, Precondition},
    InvocationPrincipal,
};
use latent_manifest::TransactionOperationMode as Mode;
use latent_node::transaction_runtime::TransactionSelection;
use latent_rpc::{invocation::v1 as i, phase4 as contract, transaction::v1 as t};

pub(super) struct Selected {
    pub installation: Arc<TransactionInstallation>,
    pub selection: TransactionSelection,
    pub invocation: i::InvokeRequest,
}
pub(super) fn select(
    installations: &[Arc<TransactionInstallation>],
    message: contract::Request,
    principal: &InvocationPrincipal,
) -> Result<Selected, PlatformError> {
    match message {
        contract::Request::InvokeCommand(request) => command(installations, *request, principal),
        contract::Request::Query(request) => query(installations, *request),
        _ => Err(error(PlatformErrorCode::InvalidArgument)),
    }
}

fn installation(
    rows: &[Arc<TransactionInstallation>],
    invocation: &i::InvokeRequest,
    namespace: &str,
    mode: Mode,
) -> Result<Arc<TransactionInstallation>, PlatformError> {
    let target = invocation
        .target
        .as_ref()
        .ok_or_else(|| error(PlatformErrorCode::InvalidArgument))?;
    let target = latent_routing::InvocationTarget {
        tenant: latent_core::TenantId(target.tenant.clone()),
        service: latent_core::ServiceId(target.service.clone()),
        contract: latent_core::ContractId(target.contract.clone()),
        function: latent_core::FunctionId(target.function.clone()),
        route: target.route.clone(),
    };
    let mut matched = rows
        .iter()
        .filter(|row| row.operation_for(&target, namespace, mode).is_some());
    let row = matched
        .next()
        .ok_or_else(|| error(PlatformErrorCode::IncompatibleContract))?;
    if matched.next().is_some() {
        return Err(error(PlatformErrorCode::IncompatibleContract));
    }
    Ok(Arc::clone(row))
}
fn command(
    rows: &[Arc<TransactionInstallation>],
    request: t::InvokeCommandRequest,
    principal: &InvocationPrincipal,
) -> Result<Selected, PlatformError> {
    let invocation = request
        .invocation
        .ok_or_else(|| error(PlatformErrorCode::InvalidArgument))?;
    let command = request
        .command
        .ok_or_else(|| error(PlatformErrorCode::InvalidArgument))?;
    let namespace = command
        .namespace
        .ok_or_else(|| error(PlatformErrorCode::InvalidArgument))?;
    let installation = installation(rows, &invocation, &namespace.namespace, Mode::StrictCommand)?;
    installation.check_recovery_scope(principal, command.shared_recovery_scope.as_deref())?;
    let retry = request.retry_attempt.map(retry_selection).transpose()?;
    let expected_versions = request
        .expected_versions
        .into_iter()
        .map(|value| {
            let expected = match value.expectation {
                Some(t::expected_version::Expectation::Absent(true)) => ExpectedVersion::Absent,
                Some(t::expected_version::Expectation::Version(bytes)) => {
                    ExpectedVersion::Present(bytes)
                }
                _ => return Err(error(PlatformErrorCode::InvalidArgument)),
            };
            Ok(Precondition {
                key: value.key,
                expected,
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Selected {
        installation,
        invocation,
        selection: TransactionSelection {
            namespace: namespace.namespace,
            incarnation: namespace
                .incarnation
                .parse()
                .map_err(|_| error(PlatformErrorCode::InvalidArgument))?,
            entity: command.entity,
            operation: command.operation,
            mode: Mode::StrictCommand,
            client_key: Some(command.client_key),
            expected_versions,
            minimum_view_version: None,
            input_format: request.input_format,
            retry,
        },
    })
}

fn retry_selection(
    retry: t::RetryAttempt,
) -> Result<latent_node::transaction_runtime::TransactionRetrySelection, PlatformError> {
    use latent_commit::atomic::{Identity, RetryRequest};
    use std::fmt::Write;
    let invalid = || error(PlatformErrorCode::InvalidArgument);
    let fence = retry.expected_abort.ok_or_else(invalid)?;
    let attempt = fence.attempt_id.parse::<u64>().map_err(|_| invalid())?;
    if attempt == 0
        || attempt > 16
        || attempt.to_string() != fence.attempt_id
        || fence.owner_fence.len() != 32
    {
        return Err(invalid());
    }
    let mut proof = String::with_capacity(64);
    for byte in &fence.owner_fence {
        write!(&mut proof, "{byte:02x}").map_err(|_| invalid())?;
    }
    Ok(
        latent_node::transaction_runtime::TransactionRetrySelection {
            request: RetryRequest {
                request_id: retry.request_id,
                expected_abort: Identity::parse_hex(&proof).map_err(|_| invalid())?,
            },
            command: Identity::parse_hex(&fence.command_id).map_err(|_| invalid())?,
            attempt,
            transaction: Identity::parse_hex(&fence.transaction_id).map_err(|_| invalid())?,
        },
    )
}
fn query(
    rows: &[Arc<TransactionInstallation>],
    request: t::QueryRequest,
) -> Result<Selected, PlatformError> {
    let invocation = request
        .invocation
        .ok_or_else(|| error(PlatformErrorCode::InvalidArgument))?;
    let namespace = request
        .namespace
        .ok_or_else(|| error(PlatformErrorCode::InvalidArgument))?;
    let installation = installation(rows, &invocation, &namespace.namespace, Mode::FreshQuery)?;
    // Queries carry no command recovery selector. The installed binding's
    // caller scope is sealed by native acquisition with the actual principal.
    let target = invocation
        .target
        .as_ref()
        .ok_or_else(|| error(PlatformErrorCode::InvalidArgument))?;
    let domain = latent_routing::InvocationTarget {
        tenant: latent_core::TenantId(target.tenant.clone()),
        service: latent_core::ServiceId(target.service.clone()),
        contract: latent_core::ContractId(target.contract.clone()),
        function: latent_core::FunctionId(target.function.clone()),
        route: target.route.clone(),
    };
    let input_format = installation
        .operation_for(&domain, &namespace.namespace, Mode::FreshQuery)
        .ok_or_else(|| error(PlatformErrorCode::IncompatibleContract))?
        .input_format
        .clone();
    let operation = target.function.clone();
    Ok(Selected {
        installation,
        invocation,
        selection: TransactionSelection {
            namespace: namespace.namespace,
            incarnation: namespace
                .incarnation
                .parse()
                .map_err(|_| error(PlatformErrorCode::InvalidArgument))?,
            entity: request.entity,
            operation,
            mode: Mode::FreshQuery,
            client_key: None,
            expected_versions: Vec::new(),
            minimum_view_version: request.minimum_view_version,
            input_format,
            retry: None,
        },
    })
}
