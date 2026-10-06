use super::{
    contract::{hex_identity, PATH_PREFIX, WIRE_CONTRACT},
    receipt::{self, VerifiedReceipt},
    AdapterOutcome, AttemptIdentity, AuthorityError, BoxFuture, DispatchGrant, Inner,
    PayloadRecord, MAXIMUM_CREDENTIAL_BYTES, MAXIMUM_EFFECT_RECEIPT_BYTES,
    OPERATION_METADATA_BYTES,
};
use crate::protocol::{ProtocolBody, ProtocolHeader, ProtocolPage, ProtocolRequest, ProtocolScope};
use crate::HttpError;
use latent_capabilities::broker::{
    pools::{ProviderMaintenance, ProviderMetadata},
    secrets::SecretError,
};
use latent_core::{digest::HexDigest, PlatformError, PlatformErrorCode};
use latent_effects::dispatch::{AttemptReceipt, Disposition, RetryProof};
use sha2::{Digest, Sha256};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use zeroize::Zeroizing;

struct Plan {
    grant: DispatchGrant,
    body_sha256: String,
    retain_until: u64,
    send: ProviderMaintenance,
    lookup: ProviderMaintenance,
    _metadata: ProviderMetadata,
}

pub(super) fn accept(
    inner: Arc<Inner>,
    grant: DispatchGrant,
    payload: PayloadRecord,
    attempt: &AttemptIdentity,
) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError> {
    validate(&inner, &grant, &payload, attempt)?;
    // This whole phase is short synchronous reservation under the acceptance
    // fence. No credential resolution, socket, DNS, TLS or HTTP write occurs.
    let metadata = inner
        .pools
        .reserve_protocol_metadata(OPERATION_METADATA_BYTES)
        .map_err(|error| admission_error(&error))?;
    let retain_until = grant
        .committed_at_millis()
        .checked_add(inner.contract.retention_horizon_millis)
        .ok_or(AuthorityError::Invalid)?
        .min(grant.expires_at_millis());
    if attempt
        .retry_horizon_millis()
        .is_some_and(|horizon| horizon != retain_until)
    {
        return Err(AuthorityError::PolicyBlocked);
    }
    let wall = inner.time.observe();
    if !wall.continuity_proven || wall.unix_millis < grant.committed_at_millis() {
        return Err(AuthorityError::PolicyBlocked);
    }
    let remaining = retain_until
        .checked_sub(wall.unix_millis)
        .filter(|remaining| *remaining != 0)
        .ok_or(AuthorityError::Expired)?;
    let now = Instant::now();
    let deadline = now
        .checked_add(Duration::from_millis(remaining))
        .ok_or(AuthorityError::Invalid)?
        .min(grant.deadline());
    let send_deadline = now + deadline.saturating_duration_since(now) / 2;
    let send = inner
        .transport
        .maintenance(send_deadline, 1)
        .map_err(http_admission_error)?;
    let lookup = inner
        .transport
        .maintenance(deadline, 1)
        .map_err(http_admission_error)?;
    let value = payload.value();
    let body_sha256 = format!("{:x}", HexDigest(Sha256::digest(&value.bytes)));
    let body = if value.bytes.is_empty() {
        ProtocolBody::empty(&inner.pools)
    } else {
        let mut page = ProtocolPage::allocate(&inner.pools, value.bytes.len())
            .map_err(http_admission_error)?;
        page.append(&value.bytes).map_err(http_admission_error)?;
        ProtocolBody::from_pages(&inner.pools, &[Arc::new(page)], 0..value.bytes.len())
    }
    .map_err(http_admission_error)?;
    let response = ProtocolPage::allocate(&inner.pools, MAXIMUM_EFFECT_RECEIPT_BYTES)
        .map_err(http_admission_error)?;
    let lookup_response = ProtocolPage::allocate(&inner.pools, MAXIMUM_EFFECT_RECEIPT_BYTES)
        .map_err(http_admission_error)?;
    let plan = Plan {
        grant,
        body_sha256,
        retain_until,
        send,
        lookup,
        _metadata: metadata,
    };
    // The durable payload's original allocation is not retained beyond the
    // store job: the accepted operation owns the separately prepaid exact page.
    drop(payload);
    Ok(Box::pin(async move {
        execute(&inner, plan, body, response, lookup_response).await
    }))
}

fn validate(
    inner: &Inner,
    grant: &DispatchGrant,
    payload: &PayloadRecord,
    attempt: &AttemptIdentity,
) -> Result<(), AuthorityError> {
    if grant.profile() != &inner.profile
        || grant.scope().tenant != inner.contract.tenant.0
        || grant.scope().operation != super::HTTP_EFFECT_OPERATION
        || grant.effect() != payload.effect()
        || grant.effect() != attempt.effect()
        || grant.attempt() != attempt.attempt()
        || !hex_identity(grant.effect())
    {
        return Err(AuthorityError::UnsupportedFormat);
    }
    let value = payload.value();
    if value.media_type != "application/octet-stream" || !value.metadata.is_empty() {
        return Err(AuthorityError::Invalid);
    }
    if value.bytes.len() > inner.contract.maximum_body_bytes
        || value.bytes.len() as u64 > grant.ceiling().maximum_payload_bytes
        || grant.ceiling().maximum_response_bytes < 2 * MAXIMUM_EFFECT_RECEIPT_BYTES as u64
    {
        return Err(AuthorityError::Capacity);
    }
    let credential = inner
        .credentials
        .try_lock()
        .map_err(|_| AuthorityError::Unavailable)?;
    check_credential(grant, &credential)?;
    Ok(())
}

async fn execute(
    inner: &Inner,
    plan: Plan,
    body: ProtocolBody,
    mut response: ProtocolPage,
    lookup_response: ProtocolPage,
) -> AdapterOutcome {
    if let Some(outcome) = checkpoint(inner, &plan) {
        return outcome;
    }
    let Ok(request) = request(inner, &plan, "PUT", body) else {
        return outcome(inner, Disposition::PolicyBlocked, "credential-unavailable");
    };
    let Ok(permit) = plan.send.begin_request() else {
        return outcome(inner, Disposition::KnownFailed, "rejected-before-send");
    };
    let result = inner
        .transport
        .exchange(
            ProtocolScope::Maintenance(&permit),
            request,
            MAXIMUM_EFFECT_RECEIPT_BYTES,
            &mut |bytes| response.append(bytes),
        )
        .await;
    drop(permit);
    match result {
        Ok(reply) => {
            if let Some(receipt) = verified(inner, &plan, &reply, response.bytes()) {
                return receipt_outcome(inner, &plan, receipt);
            }
            if matches!(reply.status, 400 | 401 | 403 | 409) {
                return outcome(inner, Disposition::KnownFailed, "remote-request-rejected");
            }
        }
        Err(failure) if !failure.request_started => {
            return outcome(inner, Disposition::KnownFailed, "rejected-before-send");
        }
        Err(_) => {}
    }
    // Original physical connection has closed before lookup. There is exactly
    // one lookup, under the original deadline; absence never schedules a resend.
    reconcile(inner, &plan, lookup_response).await
}

async fn reconcile(inner: &Inner, plan: &Plan, mut response: ProtocolPage) -> AdapterOutcome {
    if let Some(outcome) = checkpoint(inner, plan) {
        return AdapterOutcome {
            receipt: AttemptReceipt {
                disposition: Disposition::Uncertain,
                ..outcome.receipt
            },
            retry: None,
        };
    }
    let Ok(body) = ProtocolBody::empty(&inner.pools) else {
        return outcome(inner, Disposition::Uncertain, "remote-status-unavailable");
    };
    let Ok(request) = request(inner, plan, "GET", body) else {
        return outcome(inner, Disposition::Uncertain, "current-credential-denied");
    };
    let Ok(permit) = plan.lookup.begin_request() else {
        return outcome(inner, Disposition::Uncertain, "remote-status-unavailable");
    };
    let result = inner
        .transport
        .exchange(
            ProtocolScope::Maintenance(&permit),
            request,
            MAXIMUM_EFFECT_RECEIPT_BYTES,
            &mut |bytes| response.append(bytes),
        )
        .await;
    drop(permit);
    match result {
        Ok(reply) => {
            if let Some(receipt) = verified(inner, plan, &reply, response.bytes()) {
                return receipt_outcome(inner, plan, receipt);
            }
            outcome(
                inner,
                Disposition::Uncertain,
                match reply.status {
                    404 => "remote-status-absent",
                    410 => "remote-retention-expired",
                    300..=399 => "remote-redirect-rejected",
                    _ => "remote-status-unrepresentable",
                },
            )
        }
        Err(_) => outcome(inner, Disposition::Uncertain, "remote-status-unavailable"),
    }
}

fn verified(
    inner: &Inner,
    plan: &Plan,
    reply: &crate::protocol::ProtocolResponse,
    bytes: &[u8],
) -> Option<VerifiedReceipt> {
    receipt::verify(
        reply,
        bytes,
        plan.grant.effect(),
        &plan.body_sha256,
        &inner.contract.provider_incarnation,
        plan.retain_until,
    )
}

fn receipt_outcome(inner: &Inner, plan: &Plan, receipt: VerifiedReceipt) -> AdapterOutcome {
    match receipt {
        VerifiedReceipt::Applied(receipt) => AdapterOutcome {
            receipt: AttemptReceipt {
                disposition: Disposition::ProviderAcknowledged,
                reason: "qualified-remote-receipt".into(),
                provider_receipt: Some(receipt),
                observed_at_millis: inner.time.observe().unix_millis,
            },
            retry: None,
        },
        VerifiedReceipt::Reserved => {
            if let Some(outcome) = checkpoint(inner, plan) {
                return outcome;
            }
            let now = inner.time.observe();
            if now
                .unix_millis
                .checked_add(inner.contract.retry_delay_millis)
                .is_none_or(|next| next >= plan.retain_until)
            {
                return outcome(inner, Disposition::Uncertain, "remote-retention-expired");
            }
            AdapterOutcome {
                receipt: AttemptReceipt {
                    disposition: Disposition::KnownFailed,
                    reason: "qualified-reservation-retryable".into(),
                    provider_receipt: None,
                    observed_at_millis: now.unix_millis,
                },
                retry: Some((
                    RetryProof::QualifiedDeduplication {
                        valid_until_millis: plan.retain_until,
                        same_payload: true,
                        same_provider_incarnation: true,
                    },
                    inner.contract.retry_delay_millis,
                )),
            }
        }
    }
}

fn checkpoint(inner: &Inner, plan: &Plan) -> Option<AdapterOutcome> {
    let now = inner.time.observe();
    if !now.continuity_proven || now.unix_millis < plan.grant.committed_at_millis() {
        Some(outcome(
            inner,
            Disposition::PolicyBlocked,
            "clock-discontinuity",
        ))
    } else if now.unix_millis >= plan.grant.expires_at_millis()
        || Instant::now() >= plan.grant.deadline()
    {
        Some(outcome(inner, Disposition::Expired, "effect-expired"))
    } else if now.unix_millis >= plan.retain_until {
        Some(outcome(
            inner,
            Disposition::PolicyBlocked,
            "remote-retention-expired",
        ))
    } else {
        None
    }
}

fn request(
    inner: &Inner,
    plan: &Plan,
    method: &str,
    body: ProtocolBody,
) -> Result<ProtocolRequest, AuthorityError> {
    let current = inner
        .credentials
        .try_lock()
        .map_err(|_| AuthorityError::Unavailable)?;
    check_credential(&plan.grant, &current)?;
    let binding = Arc::clone(&current.binding);
    drop(current);
    let mut authorization = Zeroizing::new(String::with_capacity(MAXIMUM_CREDENTIAL_BYTES + 7));
    let mut repeated_value = false;
    binding
        .with_current_value(&mut |value| {
            if !authorization.is_empty() {
                repeated_value = true;
                return Err(SecretError::PermissionDenied);
            }
            if value.is_empty()
                || value.len() > MAXIMUM_CREDENTIAL_BYTES
                || !value
                    .iter()
                    .all(|byte| byte.is_ascii_alphanumeric() || b"-._~+/=".contains(byte))
            {
                return Err(SecretError::PermissionDenied);
            }
            authorization.push_str("Bearer ");
            authorization
                .push_str(std::str::from_utf8(value).map_err(|_| SecretError::PermissionDenied)?);
            Ok(())
        })
        .map_err(|_| AuthorityError::PolicyBlocked)?;
    if repeated_value || authorization.is_empty() {
        return Err(AuthorityError::PolicyBlocked);
    }
    let origin = &inner.contract.origin;
    let host = if origin.host.contains(':') {
        format!("[{}]:{}", origin.host, origin.port)
    } else {
        format!("{}:{}", origin.host, origin.port)
    };
    let mut headers = vec![
        header("host", host),
        ProtocolHeader {
            name: "authorization".into(),
            value: authorization,
            sensitive: true,
        },
        header("accept", "application/json"),
        header("cache-control", "no-store"),
        header("idempotency-key", plan.grant.effect()),
        header("x-lsf-effect-contract", WIRE_CONTRACT),
        header("x-lsf-effect-body-sha256", &plan.body_sha256),
        header(
            "x-lsf-effect-provider-incarnation",
            &inner.contract.provider_incarnation,
        ),
        header("x-lsf-effect-retain-until", plan.retain_until.to_string()),
    ];
    if method == "PUT" {
        headers.push(header("content-type", "application/octet-stream"));
    }
    Ok(ProtocolRequest {
        method: method.into(),
        path_and_query: format!("{PATH_PREFIX}{}", plan.grant.effect()),
        headers,
        body,
    })
}

fn check_credential(
    grant: &DispatchGrant,
    current: &super::Credential,
) -> Result<(), AuthorityError> {
    if current.epoch != grant.credential_epoch()
        || current.binding.reference() != grant.protected_credential_reference()
    {
        return Err(AuthorityError::PolicyBlocked);
    }
    Ok(())
}

fn header(name: &str, value: impl Into<String>) -> ProtocolHeader {
    ProtocolHeader {
        name: name.into(),
        value: Zeroizing::new(value.into()),
        sensitive: false,
    }
}

fn outcome(inner: &Inner, disposition: Disposition, reason: &str) -> AdapterOutcome {
    AdapterOutcome {
        receipt: AttemptReceipt {
            disposition,
            reason: reason.into(),
            provider_receipt: None,
            observed_at_millis: inner.time.observe().unix_millis,
        },
        retry: None,
    }
}

pub(super) fn admission_error(error: &PlatformError) -> AuthorityError {
    match error.code {
        PlatformErrorCode::ResourceExhausted => AuthorityError::Capacity,
        PlatformErrorCode::PermissionDenied | PlatformErrorCode::Unauthenticated => {
            AuthorityError::PolicyBlocked
        }
        _ => AuthorityError::Unavailable,
    }
}

pub(super) fn http_admission_error(error: HttpError) -> AuthorityError {
    match error {
        HttpError::PermissionDenied => AuthorityError::PolicyBlocked,
        HttpError::RequestTooLarge | HttpError::ResponseTooLarge => AuthorityError::Capacity,
        HttpError::InvalidRequest | HttpError::InvalidUrl => AuthorityError::Invalid,
        _ => AuthorityError::Unavailable,
    }
}
