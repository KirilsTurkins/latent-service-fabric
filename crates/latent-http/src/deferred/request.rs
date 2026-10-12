use super::{attempt::AcceptedOperation, qualification::ENDPOINT_CONTRACT};
use crate::protocol::{ProtocolBody, ProtocolHeader, ProtocolPage, ProtocolRequest};
use crate::{headers, HttpError};
use latent_capabilities::broker::secrets::SecretError;
use sha2::{Digest, Sha256};
use std::sync::Arc;
use zeroize::Zeroizing;

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Operation {
    Profile,
    Send,
    Lookup,
}

pub(super) struct RequestData {
    pub request: ProtocolRequest,
    pub credential_stamp: Zeroizing<[u8; 32]>,
}

pub(super) fn build(
    owner: &AcceptedOperation,
    operation: Operation,
) -> Result<RequestData, HttpError> {
    let endpoint = &owner.endpoint;
    let inner = &owner.provider.inner;
    let key = format!("lsf-effect-{}", owner.request.grant().effect());
    let path = if operation == Operation::Lookup {
        format!("{}{key}", endpoint.lookup_prefix)
    } else {
        endpoint.operation_path.clone()
    };
    let body = if operation == Operation::Send && !owner.value.bytes.is_empty() {
        let mut page = ProtocolPage::allocate(&inner.pools, owner.value.bytes.len())?;
        page.append(&owner.value.bytes)?;
        ProtocolBody::from_pages(&inner.pools, &[Arc::new(page)], 0..owner.value.bytes.len())?
    } else {
        ProtocolBody::empty(&inner.pools)?
    };
    let mut values = Vec::with_capacity(10);
    for (name, value) in [
        (
            "host",
            format!("{}:{}", endpoint.origin.host, endpoint.origin.port),
        ),
        ("content-type", endpoint.media_type.clone()),
        ("accept", "application/json".into()),
        ("accept-encoding", "identity".into()),
        ("idempotency-key", key),
        ("lsf-endpoint-contract", ENDPOINT_CONTRACT.into()),
        (
            "lsf-endpoint-incarnation",
            endpoint.endpoint_incarnation.clone(),
        ),
        (
            "lsf-idempotency-retention-millis",
            endpoint.retention_millis.to_string(),
        ),
        ("lsf-body-sha256", owner.body_digest.clone()),
    ] {
        values.push(ProtocolHeader {
            name: name.into(),
            value: Zeroizing::new(value),
            sensitive: false,
        });
    }
    let mut credential_stamp = Zeroizing::new([0; 32]);
    inner.credential_references[0]
        .binding
        .with_current_value(&mut |bytes| {
            let value = credential(bytes)?;
            *credential_stamp = Sha256::digest(bytes).into();
            values.push(ProtocolHeader {
                name: "authorization".into(),
                value: Zeroizing::new(value.into()),
                sensitive: true,
            });
            Ok(())
        })
        .map_err(|_| HttpError::PermissionDenied)?;
    Ok(RequestData {
        request: ProtocolRequest {
            method: if operation == Operation::Send {
                "POST"
            } else {
                "GET"
            }
            .into(),
            path_and_query: path,
            headers: values,
            body,
        },
        credential_stamp,
    })
}

pub(super) fn check_credential(
    owner: &AcceptedOperation,
    original: &[u8; 32],
) -> Result<(), HttpError> {
    owner.provider.inner.credential_references[0]
        .binding
        .with_current_value(&mut |bytes| {
            credential(bytes)?;
            let current = Zeroizing::new(<[u8; 32]>::from(Sha256::digest(bytes)));
            if &*current != original {
                return Err(SecretError::PermissionDenied);
            }
            Ok(())
        })
        .map_err(|_| HttpError::PermissionDenied)
}

fn credential(bytes: &[u8]) -> Result<&str, SecretError> {
    if bytes.is_empty() || bytes.len() > 4096 {
        return Err(SecretError::PermissionDenied);
    }
    let value = std::str::from_utf8(bytes).map_err(|_| SecretError::PermissionDenied)?;
    if !headers::valid_value(value) {
        return Err(SecretError::PermissionDenied);
    }
    Ok(value)
}
