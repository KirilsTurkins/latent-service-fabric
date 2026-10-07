//! RPC continuation data binds the authenticated caller, current publication,
//! prefix and canonical durable view. It supplies neither a grant nor a session.
use super::{invalid, Access, PlatformError};
use latent_rpc::control::v1 as c;
use latent_state::session::{
    version::{ViewIdentity, VIEW_TOKEN_BYTES},
    StateMode, StateScope,
};
use prost::Message;
use sha2::{Digest, Sha256};

const MAGIC: &[u8] = b"EC\x01";
const LENGTH: usize = 3 + 32 + VIEW_TOKEN_BYTES + 32;

fn scope(access: &Access) -> StateScope {
    StateScope {
        tenant: access
            .binding
            .publication
            .scope
            .tenant()
            .expect("admitted tenant")
            .clone(),
        namespace: access.binding.namespace.clone(),
        incarnation: access.binding.incarnation,
        state_schema: access.binding.state_schema.clone(),
        entity: None,
        mode: StateMode::Query,
    }
}
fn binding(request: &c::SelectEntityRequest, access: &Access) -> [u8; 32] {
    let mut hash = Sha256::new();
    hash.update(b"lsf-entity-rpc-cursor-v1\0");
    let target = request
        .namespace
        .as_ref()
        .expect("validated namespace")
        .encode_to_vec();
    hash.update((target.len() as u64).to_le_bytes());
    hash.update(target);
    let prefix = request.prefix.as_deref().unwrap_or_default();
    hash.update((prefix.len() as u64).to_le_bytes());
    hash.update(prefix);
    for text in [
        &access.caller.owner_kind,
        &access.caller.scope,
        &access.binding.result_policy,
        &access.binding.state_schema,
        &access.binding.component.0,
        &access.binding.state.configuration_digest,
    ] {
        hash.update((text.len() as u64).to_le_bytes());
        hash.update(text.as_bytes());
    }
    hash.update(access.binding.state.configuration_epoch.to_le_bytes());
    hash.finalize().into()
}
pub(super) fn decode(
    request: &c::SelectEntityRequest,
    access: &Access,
) -> Result<(Option<[u8; 32]>, Option<ViewIdentity>), PlatformError> {
    let Some(cursor) = request
        .page
        .as_ref()
        .expect("validated page")
        .cursor
        .as_deref()
    else {
        return Ok((None, None));
    };
    if cursor.len() != LENGTH
        || !cursor.starts_with(MAGIC)
        || cursor[3..35] != binding(request, access)
    {
        return Err(invalid());
    }
    let view = ViewIdentity::from_token(&scope(access), &cursor[35..35 + VIEW_TOKEN_BYTES])
        .map_err(|_| invalid())?;
    let after = cursor[35 + VIEW_TOKEN_BYTES..]
        .try_into()
        .map_err(|_| invalid())?;
    Ok((Some(after), Some(view)))
}
pub(super) fn encode(
    request: &c::SelectEntityRequest,
    access: &Access,
    view: ViewIdentity,
    after: [u8; 32],
) -> Result<Vec<u8>, PlatformError> {
    let mut cursor = Vec::with_capacity(LENGTH);
    cursor.extend_from_slice(MAGIC);
    cursor.extend_from_slice(&binding(request, access));
    cursor.extend_from_slice(&view.token(&scope(access)).map_err(|_| invalid())?);
    cursor.extend_from_slice(&after);
    Ok(cursor)
}
