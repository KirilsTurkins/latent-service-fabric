//! Bind only the signed startup descriptor to this original HTTP reservation.
use crate::standalone::state::{InstalledTransactionOperation, StateRequest, StateRuntime};
use latent_artifacts::ReleaseUseEligibility;
use latent_core::{PlatformError, PlatformErrorCode, ResourceBudget};
use latent_ingress::http::{
    self,
    transaction::{RouteMode, TransactionRequest, TransactionRoute},
    Invocation,
};
use latent_manifest::TransactionOperationMode;
use latent_node::{
    transaction_runtime::command_completion::CommandRetry, InboundActivationReservation,
};
use std::sync::Arc;

pub(crate) fn map(
    request: http::Request,
    route: Option<&TransactionRoute>,
) -> Result<(Invocation, Option<TransactionRequest>), u16> {
    match route {
        Some(route) => request
            .into_transaction(route)
            .map(|(invocation, facts)| (invocation, Some(facts))),
        None => request
            .into_invocation()
            .map(|invocation| (invocation, None)),
    }
    .map_err(|error| error.status().unwrap_or(0))
}

pub(crate) fn budget(ceiling: &ResourceBudget, route: Option<&TransactionRoute>) -> ResourceBudget {
    let mut budget = ceiling.clone();
    if let Some(route) = route {
        // A direct transaction cannot acquire authority through a child or an
        // immediate network/blob operation. Every remaining dimension is the
        // original trusted node ceiling, intersected again at normal admission.
        budget.child_calls = 0;
        budget.outbound_requests = 0;
        budget.blob_read_bytes = 0;
        budget.blob_write_bytes = 0;
        if matches!(route.mode(), RouteMode::Query | RouteMode::Result) {
            budget.state_write_bytes = 0;
            budget.effect_count = 0;
        }
    }
    budget
}

pub(crate) fn bind(
    state: &StateRuntime,
    route: &TransactionRoute,
    facts: &TransactionRequest,
    publication: &ReleaseUseEligibility,
    reservation: &mut InboundActivationReservation,
) -> Result<(), PlatformError> {
    let installed = state.installed(&reservation.revision().target, publication)?;
    require_binding(route, &installed)?;
    let codec = Arc::new(super::HttpCommandResultCodec);
    let admission = match route.mode() {
        RouteMode::Command => {
            let retry = facts
                .retry()
                .map(|retry| CommandRetry::new(retry.request_id().into(), retry.fence().clone()))
                .transpose()?;
            let request = StateRequest::command(
                facts.client_key().ok_or_else(denied)?.into(),
                facts.preconditions().to_vec(),
                business_metadata(facts),
                retry,
            )?;
            state.admission(installed, request, codec)?
        }
        RouteMode::Query => state.admission(
            installed,
            StateRequest::query(facts.minimum_view().map(<[u8]>::to_vec))?,
            codec,
        )?,
        RouteMode::Result => state.result_admission(
            installed,
            facts.client_key().ok_or_else(denied)?.into(),
            codec,
        )?,
    };
    reservation.bind_transaction(admission)
}

fn require_binding(
    route: &TransactionRoute,
    installed: &InstalledTransactionOperation,
) -> Result<(), PlatformError> {
    let mode = match route.mode() {
        RouteMode::Command | RouteMode::Result => TransactionOperationMode::StrictCommand,
        RouteMode::Query => TransactionOperationMode::FreshQuery,
    };
    if route.namespace() != installed.namespace()
        || route.incarnation() != installed.incarnation()
        || route.state_schema() != installed.state_schema()
        || route.companion_digest() != installed.companion_digest()
        || route.binding() != installed.binding()
        || route.result_policy() != installed.result_policy()
        || route.entity() != installed.entity()
        || mode != installed.mode()
    {
        return Err(denied());
    }
    Ok(())
}

fn business_metadata(facts: &TransactionRequest) -> Vec<(String, String)> {
    let method = match facts.method() {
        http::Method::Post => "POST",
        http::Method::Put => "PUT",
        http::Method::Patch => "PATCH",
        http::Method::Delete => "DELETE",
        http::Method::Get => "GET",
        http::Method::Head => "HEAD",
        http::Method::Options => "OPTIONS",
    };
    let mut metadata = vec![
        ("http-method".into(), method.into()),
        ("http-path".into(), facts.business_path().into()),
    ];
    if let Some(query) = facts.business_query() {
        metadata.push(("http-query".into(), query.into()));
    }
    metadata
}

fn denied() -> PlatformError {
    crate::standalone::error(
        PlatformErrorCode::PermissionDenied,
        "transaction-http-binding-not-installed",
    )
}
