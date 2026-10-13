use super::{HttpResultValidator, Services};
use latent_core::{PlatformError, PlatformErrorCode, ResourceBudget};
use latent_ingress::http::{
    self,
    transaction::{RouteMode, TransactionRequest, TransactionRoute},
    Invocation,
};
use latent_manifest::TransactionOperationMode;
use latent_node::{
    transaction_runtime::{
        NativeTransactionAdmission, TransactionInstallation, TransactionRetrySelection,
        TransactionSelection,
    },
    InboundActivationReservation,
};
use latent_rpc::{control::v1 as c, transaction::v1 as t};
use std::sync::Arc;

pub(in crate::standalone::http) fn map(
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
    .map_err(|e| e.status().unwrap_or(0))
}

pub(in crate::standalone::http) fn budget(
    ceiling: &ResourceBudget,
    route: Option<&TransactionRoute>,
) -> ResourceBudget {
    let mut budget = ceiling.clone();
    if let Some(route) = route {
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

fn selected(
    services: &Services,
    route: &TransactionRoute,
    revision: &latent_routing::ResolvedRevision,
) -> Result<Arc<TransactionInstallation>, PlatformError> {
    let mode = if route.mode() == RouteMode::Query {
        TransactionOperationMode::FreshQuery
    } else {
        TransactionOperationMode::StrictCommand
    };
    let mut rows = services.installations.iter().filter(|i| {
        i.operation_for(&revision.target, route.namespace(), mode)
            .is_some()
    });
    let row = rows.next().ok_or_else(denied)?;
    if rows.next().is_some() {
        return Err(denied());
    }
    if route.mode() != RouteMode::Result {
        row.source_for_resolved(revision)?;
    }
    let mut configs = services.operations.iter().filter(|c| {
        c.tenant == revision.target.tenant
            && c.component == revision.release
            && Some(&c.publication) == revision.publication.as_ref()
            && c.contract == revision.target.contract.0
            && c.function == revision.target.function.0
            && c.route == revision.target.route
    });
    let config = configs.next().ok_or_else(denied)?;
    if configs.next().is_some()
        || config.binding != route.binding()
        || config.companion_digest != route.companion_digest()
        || config.incarnation != route.incarnation()
        || config.result_policy != route.result_policy()
        || config.entity.as_deref() != route.entity()
        || row.state_schema() != route.state_schema()
    {
        return Err(denied());
    }
    Ok(Arc::clone(row))
}

pub(in crate::standalone::http) fn bind(
    services: &Services,
    route: &TransactionRoute,
    facts: &TransactionRequest,
    reservation: &mut InboundActivationReservation,
    input_bytes: usize,
) -> Result<
    (
        Arc<NativeTransactionAdmission>,
        Arc<TransactionInstallation>,
    ),
    PlatformError,
> {
    let installation = selected(services, route, reservation.revision())?;
    let mode = if route.mode() == RouteMode::Query {
        TransactionOperationMode::FreshQuery
    } else {
        TransactionOperationMode::StrictCommand
    };
    if route.mode() == RouteMode::Result {
        return Err(denied());
    }
    let operation = installation
        .operation_for(&reservation.revision().target, route.namespace(), mode)
        .ok_or_else(denied)?;
    let retry = facts
        .retry()
        .map(|r| {
            use latent_commit::atomic::{Identity, RetryRequest};
            let f = r.fence();
            let proof = format!("{:x}", latent_core::digest::HexDigest(&f.owner_fence));
            Ok::<_, PlatformError>(TransactionRetrySelection {
                request: RetryRequest {
                    request_id: r.request_id().into(),
                    expected_abort: Identity::parse_hex(&proof).map_err(|_| denied())?,
                },
                command: Identity::parse_hex(&f.command_id).map_err(|_| denied())?,
                attempt: f.attempt_id.parse().map_err(|_| denied())?,
                transaction: Identity::parse_hex(&f.transaction_id).map_err(|_| denied())?,
            })
        })
        .transpose()?;
    let selection = TransactionSelection {
        namespace: route.namespace().into(),
        incarnation: route.incarnation(),
        entity: route.entity().map(str::to_owned),
        operation: operation.operation.clone(),
        mode,
        client_key: facts.client_key().map(str::to_owned),
        expected_versions: facts.preconditions().to_vec(),
        minimum_view_version: facts.minimum_view().map(<[u8]>::to_vec),
        input_format: operation.input_format.clone(),
        retry,
    };
    let native = services.owners.reserve_ingress(
        input_bytes.saturating_add(16 * 1024),
        reservation.deadline(),
    )?;
    let admission = Arc::new(
        NativeTransactionAdmission::with_ingress_reservation(
            Arc::clone(&services.owners),
            Arc::clone(&installation),
            selection,
            native,
        )?
        .with_prepared_input(Arc::new(HttpResultValidator)),
    );
    reservation.bind_transaction(admission.clone())?;
    Ok((admission, installation))
}

pub(in crate::standalone::http) fn business_metadata(
    facts: &TransactionRequest,
) -> latent_core::Metadata {
    let method = match facts.method() {
        http::Method::Post => "POST",
        http::Method::Put => "PUT",
        http::Method::Patch => "PATCH",
        http::Method::Delete => "DELETE",
        http::Method::Get => "GET",
        http::Method::Head => "HEAD",
        http::Method::Options => "OPTIONS",
    };
    latent_core::Metadata::from([
        ("http-method".into(), method.into()),
        ("http-path".into(), facts.business_path().into()),
    ])
}

pub(in crate::standalone::http) fn recover(
    services: &Services,
    route: &TransactionRoute,
    facts: &TransactionRequest,
    invocation: Invocation,
    revision: latent_routing::ResolvedRevision,
    lease: latent_control_store::http_routes::TriggerReadLease,
    clock: &dyn latent_core::ActivationClock,
) -> Result<latent_core::BoxFuture<'static, Result<http::Delivery, u16>>, u16> {
    let installation =
        selected(services, route, &revision).map_err(super::super::dispatch::status)?;
    let principal = invocation.context().principal().clone();
    let deadline = invocation.deadline();
    let sample = clock.sample();
    let (unix, expiry) =
        result_read_deadline(deadline.unix_millis(), deadline.monotonic(), sample)?;
    let context = latent_wire::invocation::AuthenticatedInvocationContext::new(principal)
        .with_transport_deadline_at(unix, expiry);
    let request = t::LookupCommandRequest {
        profile: Some(latent_rpc::phase4::current_profile()),
        command: Some(t::CommandSelector {
            namespace: Some(t::NamespaceSelector {
                tenant: revision.target.tenant.0.clone(),
                namespace: route.namespace().into(),
                incarnation: route.incarnation().to_string(),
            }),
            operation: revision.target.function.0,
            entity: route.entity().map(str::to_owned),
            client_key: facts.client_key().ok_or(400u16)?.into(),
            shared_recovery_scope: None,
        }),
        attempt_id: None,
        authorization_publication: Some(c::PublicationRef {
            tenant: revision.target.tenant.0,
            id: revision.publication.ok_or(403u16)?.as_str().into(),
        }),
    };
    let response = services.management.execute_state(context, request.into());
    Ok(Box::pin(async move {
        let _installation = installation;
        let response = response.await.map_err(super::super::dispatch::status)?;
        let delivery = super::deliver(invocation, response);
        drop(lease);
        delivery
    }))
}

fn result_read_deadline(
    original_unix: u64,
    original: std::time::Instant,
    sample: latent_core::ClockSample,
) -> Result<(u64, std::time::Instant), u16> {
    let maximum = sample.monotonic() + std::time::Duration::from_secs(30);
    let expiry = original.min(maximum);
    let millis = u64::try_from(
        expiry
            .saturating_duration_since(sample.monotonic())
            .as_millis(),
    )
    .map_err(|_| 400u16)?;
    Ok((
        original_unix.min(sample.unix_millis().saturating_add(millis)),
        expiry,
    ))
}

#[cfg(test)]
mod result_deadline_tests {
    use super::*;

    #[test]
    fn retained_result_read_narrows_long_http_deadline_and_preserves_earlier_originals() {
        let now = std::time::Instant::now();
        let sample = latent_core::ClockSample::new(1000, now);
        let seconds = |n| std::time::Duration::from_secs(n);
        assert_eq!(
            result_read_deadline(121_000, now + seconds(120), sample).unwrap(),
            (31_000, now + seconds(30))
        );
        assert_eq!(
            result_read_deadline(2000, now + seconds(1), sample).unwrap(),
            (2000, now + seconds(1))
        );
        assert_eq!(
            result_read_deadline(999, now - seconds(1), sample).unwrap(),
            (999, now - seconds(1))
        );
    }
}

fn denied() -> PlatformError {
    crate::standalone::error(
        PlatformErrorCode::PermissionDenied,
        "transaction-http-binding-not-installed",
    )
}
