//! Closed state-cell/accounting codecs for coherent startup validation. Reading
//! these descriptive records does not mint a session or namespace authority.

use super::{codec, usage_key, StateError, StateMode, StateScope};
use crate::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::{namespace_record_key, NamespaceRecord, NamespaceStatus},
};
use latent_core::{transaction_contract as contract, StateNamespaceId, TenantId};

/// Coherent persisted namespace usage. This descriptor allocates no session,
/// refreshes no grant and cannot edit state. Tombstones remain charged.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StateUsage {
    pub keys: u64,
    pub encoded_bytes: u64,
    pub tombstones: u64,
}

/// Descriptive data from one borrowed engine view and the original cell codec.
/// This does not acquire a query session, bypass a paused namespace, or grant
/// result access. Native recovery must retain its own current read authority.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObservedCell {
    pub scope: StateScope,
    pub key: Vec<u8>,
    pub generation: u64,
    pub value: Option<contract::Value>,
}

pub fn inspect_cell(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<ObservedCell, StoreError> {
    if key.family != Family::State || !key.key.starts_with(b"state-v1\0") {
        return Err(StoreError::UnsupportedFormat);
    }
    let (identity, business_key) = cell_identity_and_key(&key.key)?;
    let namespace = namespace_in(
        view,
        &identity.tenant,
        &identity.namespace,
        identity.incarnation,
    )?;
    let cell = codec::Cell::decode(bytes, namespace.version.generation).map_err(storage)?;
    Ok(ObservedCell {
        scope: StateScope {
            tenant: identity.tenant,
            namespace: identity.namespace,
            incarnation: identity.incarnation,
            state_schema: namespace.state_schema,
            entity: identity.entity,
            mode: StateMode::Query,
        },
        key: business_key.to_vec(),
        generation: cell.generation,
        value: cell.value,
    })
}
pub fn inspect_usage(
    view: &ReadView,
    namespace: &NamespaceRecord,
) -> Result<StateUsage, StateError> {
    let scope = StateScope {
        tenant: namespace.tenant.clone(),
        namespace: namespace.id.clone(),
        incarnation: namespace.version.incarnation,
        state_schema: namespace.state_schema.clone(),
        entity: None,
        mode: StateMode::Query,
    };
    let usage = view
        .get(&usage_key(&scope)?)?
        .map_or(Ok(codec::Usage::default()), |bytes| {
            codec::Usage::decode(&bytes)
        })?;
    if usage.keys > namespace.quota.state_keys
        || usage.bytes > namespace.quota.state_bytes
        || usage.tombstones > namespace.quota.state_keys
        || usage.tombstone_bytes > namespace.quota.state_bytes
    {
        return Err(StateError::Corrupt);
    }
    Ok(StateUsage {
        keys: usage.keys,
        encoded_bytes: usage
            .bytes
            .checked_add(usage.tombstone_bytes)
            .ok_or(StateError::Corrupt)?,
        tombstones: usage.tombstones,
    })
}

pub fn validate_row(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    match key.family {
        Family::State if key.key.starts_with(b"state-v1\0") => {
            let identity = cell_identity(&key.key)?;
            let namespace = namespace_in(
                view,
                &identity.tenant,
                &identity.namespace,
                identity.incarnation,
            )?;
            codec::Cell::decode(bytes, namespace.version.generation).map_err(storage)?;
        }
        Family::Maintenance if key.key.starts_with(b"state-usage-v1\0") => {
            let rest = &key.key[b"state-usage-v1\0".len()..];
            let mut input = KeyInput(rest.strip_prefix(b"ns-v1\0").ok_or(StoreError::Corrupt)?);
            let tenant = TenantId(input.text()?);
            let namespace = StateNamespaceId(input.text()?);
            let incarnation = input.number()?;
            if !input.0.is_empty() {
                return Err(StoreError::Corrupt);
            }
            let namespace = namespace_in(view, &tenant, &namespace, incarnation)?;
            let usage = codec::Usage::decode(bytes).map_err(storage)?;
            if usage.keys > namespace.quota.state_keys
                || usage.bytes > namespace.quota.state_bytes
                || usage.tombstones > namespace.quota.state_keys
                || usage.tombstone_bytes > namespace.quota.state_bytes
            {
                return Err(StoreError::Corrupt);
            }
        }
        _ => return Err(StoreError::UnsupportedFormat),
    }
    Ok(())
}

/// The same closed physical key decoder serves startup and host inspection.
/// These values describe persisted scope and cannot supply a grant or session.
pub(super) struct CellIdentity {
    pub tenant: TenantId,
    pub namespace: StateNamespaceId,
    pub incarnation: u64,
    pub entity: Option<String>,
}

pub(super) fn cell_identity(key: &[u8]) -> Result<CellIdentity, StoreError> {
    cell_identity_and_key(key).map(|(identity, _)| identity)
}

fn cell_identity_and_key(key: &[u8]) -> Result<(CellIdentity, &[u8]), StoreError> {
    let mut input = KeyInput(
        key.strip_prefix(b"state-v1\0")
            .ok_or(StoreError::UnsupportedFormat)?,
    );
    let tenant = TenantId(input.text()?);
    let namespace = StateNamespaceId(input.text()?);
    let incarnation = input.number()?;
    let entity = match input.byte()? {
        0 => None,
        1 => Some(input.text()?),
        _ => return Err(StoreError::Corrupt),
    };
    if incarnation == 0 || input.0.is_empty() || input.0.len() > contract::KEY_BYTES {
        return Err(StoreError::Corrupt);
    }
    Ok((
        CellIdentity {
            tenant,
            namespace,
            incarnation,
            entity,
        },
        input.0,
    ))
}

/// The existing full state/usage validator owns the tenant association. This
/// descriptor neither opens a session nor substitutes the per-namespace view.
pub fn tenant_for_row(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<TenantId, StoreError> {
    validate_row(view, key, bytes)?;
    let rest = if key.family == Family::State {
        key.key.strip_prefix(b"state-v1\0")
    } else {
        key.key
            .strip_prefix(b"state-usage-v1\0")
            .and_then(|rest| rest.strip_prefix(b"ns-v1\0"))
    }
    .ok_or(StoreError::UnsupportedFormat)?;
    Ok(TenantId(KeyInput(rest).text()?))
}

fn namespace_in(
    view: &ReadView,
    tenant: &TenantId,
    id: &StateNamespaceId,
    incarnation: u64,
) -> Result<NamespaceRecord, StoreError> {
    let key = RowKey {
        family: Family::Namespace,
        key: namespace_record_key(tenant, id).map_err(|_| StoreError::Corrupt)?,
    };
    let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
    let record = NamespaceRecord::decode(&bytes).map_err(|_| StoreError::Corrupt)?;
    if record.tenant != *tenant
        || record.id != *id
        || incarnation == 0
        || record.version.incarnation != incarnation
        || record.status == NamespaceStatus::Tombstone
    {
        return Err(StoreError::Corrupt);
    }
    Ok(record)
}

struct KeyInput<'a>(&'a [u8]);
impl KeyInput<'_> {
    fn take(&mut self, count: usize) -> Result<&[u8], StoreError> {
        let value = self.0.get(..count).ok_or(StoreError::Corrupt)?;
        self.0 = &self.0[count..];
        Ok(value)
    }
    fn text(&mut self) -> Result<String, StoreError> {
        let length = usize::from(u16::from_le_bytes(
            self.take(2)?.try_into().map_err(|_| StoreError::Corrupt)?,
        ));
        if !(1..=contract::IDENTITY_BYTES).contains(&length) {
            return Err(StoreError::Corrupt);
        }
        let value = std::str::from_utf8(self.take(length)?).map_err(|_| StoreError::Corrupt)?;
        contract::identity(value).map_err(|_| StoreError::Corrupt)?;
        if value.chars().any(char::is_control) {
            return Err(StoreError::Corrupt);
        }
        Ok(value.to_owned())
    }
    fn number(&mut self) -> Result<u64, StoreError> {
        Ok(u64::from_le_bytes(
            self.take(8)?.try_into().map_err(|_| StoreError::Corrupt)?,
        ))
    }
    fn byte(&mut self) -> Result<u8, StoreError> {
        Ok(self.take(1)?[0])
    }
}
fn storage(error: StateError) -> StoreError {
    match error {
        StateError::UnsupportedFormat => StoreError::UnsupportedFormat,
        _ => StoreError::Corrupt,
    }
}
