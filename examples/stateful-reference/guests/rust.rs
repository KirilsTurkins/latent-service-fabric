// lsf-example-begin: order-draft
#![cfg_attr(not(target_arch = "wasm32"), allow(dead_code))]
#[cfg(target_arch = "wasm32")]
wit_bindgen::generate!({
    path: "wit", world: "service",
    with: {
        "latent:state/key-value@0.2.0": latent_guest::bindings::state,
        "latent:intents/staging@0.1.0": latent_guest::bindings::intents,
    },
});
#[cfg(target_arch = "wasm32")]
use exports::examples::order_draft::api::{BusinessError, Draft, EditRequest, Guest};
#[cfg(target_arch = "wasm32")]
use latent_guest::{
    intents::Intent,
    state::{Command, Query, Value, VersionedValue},
};

#[cfg(target_arch = "wasm32")]
const MEDIA: &str = "application/vnd.lsf.order-draft-v1";

#[cfg(target_arch = "wasm32")]
fn keys(id: &str) -> Result<(Vec<u8>, Vec<u8>), BusinessError> {
    let bytes = id.as_bytes();
    if bytes.is_empty()
        || bytes.len() > 32
        || !bytes[0].is_ascii_lowercase() && !bytes[0].is_ascii_digit()
        || bytes
            .iter()
            .any(|byte| !byte.is_ascii_lowercase() && !byte.is_ascii_digit() && *byte != b'-')
    {
        return Err(BusinessError::InvalidDraft);
    }
    Ok((
        format!("drafts/{id}/draft").into_bytes(),
        format!("drafts/{id}/summary").into_bytes(),
    ))
}

#[cfg(target_arch = "wasm32")]
fn decode(
    primary: Option<&VersionedValue>,
    summary: Option<&VersionedValue>,
) -> Result<(u64, u32), BusinessError> {
    match (primary, summary) {
        (None, None) => Ok((0, 0)),
        (Some(primary), Some(summary)) => {
            for value in [&primary.value, &summary.value] {
                if value.media_type != MEDIA
                    || !value.metadata.is_empty()
                    || value.bytes.len() != 12
                {
                    return Err(BusinessError::MalformedState);
                }
            }
            if primary.value.bytes != summary.value.bytes {
                return Err(BusinessError::MalformedState);
            }
            let bytes = &primary.value.bytes;
            let revision = u64::from_le_bytes(
                bytes[..8]
                    .try_into()
                    .map_err(|_| BusinessError::MalformedState)?,
            );
            let units = u32::from_le_bytes(
                bytes[8..]
                    .try_into()
                    .map_err(|_| BusinessError::MalformedState)?,
            );
            if revision == 0 || units > 10000 {
                return Err(BusinessError::MalformedState);
            }
            Ok((revision, units))
        }
        _ => Err(BusinessError::MalformedState),
    }
}

#[cfg(target_arch = "wasm32")]
struct Capsule;
#[cfg(target_arch = "wasm32")]
impl Guest for Capsule {
    async fn edit(request: EditRequest) -> Result<Draft, BusinessError> {
        let (primary_key, summary_key) = keys(&request.draft_id)?;
        if request.units > 10000 {
            return Err(BusinessError::InvalidUnits);
        }
        let mut command = Command::acquire().expect("admitted command");
        if command
            .info()
            .expect("sealed command namespace")
            .view
            .namespace
            != format!("order-drafts-{}", request.draft_id)
        {
            return Err(BusinessError::InvalidDraft);
        }
        let primary = command.get(primary_key.clone()).await.expect("state read");
        let summary = command.get(summary_key.clone()).await.expect("state read");
        let (old_revision, _) = decode(primary.as_ref(), summary.as_ref())?;
        if old_revision != request.expected_revision {
            return Err(BusinessError::StaleEdit);
        }
        let revision = old_revision
            .checked_add(1)
            .ok_or(BusinessError::RevisionOverflow)?;
        let mut bytes = Vec::with_capacity(12);
        bytes.extend_from_slice(&revision.to_le_bytes());
        bytes.extend_from_slice(&request.units.to_le_bytes());
        let value = Value {
            bytes: bytes.clone(),
            media_type: MEDIA.into(),
            metadata: vec![],
        };
        command
            .put(primary_key, value.clone())
            .await
            .expect("stage primary");
        command
            .put(summary_key, value)
            .await
            .expect("stage summary");
        let mut event = Vec::with_capacity(request.draft_id.len() + 13);
        event.extend_from_slice(request.draft_id.as_bytes());
        event.push(0);
        event.extend_from_slice(&bytes);
        let payload = Value {
            bytes: event,
            media_type: MEDIA.into(),
            metadata: vec![],
        };
        Intent::new("draft-change".into(), "event".into(), payload.clone())
            .stage(&mut command)
            .await
            .expect("stage event");
        Intent::new("draft-http".into(), "put-once".into(), payload)
            .stage(&mut command)
            .await
            .expect("stage HTTP intent");
        if request.reject {
            return Err(BusinessError::Rejected);
        }
        Ok(Draft {
            draft_id: request.draft_id,
            revision,
            units: request.units,
            namespace_view: command.info().expect("original command view").view.version,
            key_version: primary.map(|value| value.version),
        })
    }

    async fn query(draft_id: String) -> Result<Draft, BusinessError> {
        let (primary_key, summary_key) = keys(&draft_id)?;
        let mut query = Query::acquire().expect("admitted fresh query");
        if query.info().expect("sealed query namespace").namespace
            != format!("order-drafts-{draft_id}")
        {
            return Err(BusinessError::InvalidDraft);
        }
        let primary = query.get(primary_key).await.expect("fresh primary read");
        let summary = query.get(summary_key).await.expect("fresh summary read");
        let (revision, units) = decode(primary.as_ref(), summary.as_ref())?;
        Ok(Draft {
            draft_id,
            revision,
            units,
            namespace_view: query.info().expect("fresh query view").version,
            key_version: primary.map(|value| value.version),
        })
    }
}
#[cfg(target_arch = "wasm32")]
export!(Capsule);
// lsf-example-end: order-draft
