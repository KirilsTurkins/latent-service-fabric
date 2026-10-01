//! Closed state-cell/accounting codecs for coherent startup validation. Reading
//! these descriptive records does not mint a session or namespace authority.

use super::{codec, StateError};
use crate::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::{namespace_record_key, NamespaceRecord, NamespaceStatus},
};
use latent_core::{transaction_contract as contract, StateNamespaceId, TenantId};

pub fn validate_row(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    match key.family {
        Family::State if key.key.starts_with(b"state-v1\0") => {
            let mut input = KeyInput(&key.key[b"state-v1\0".len()..]);
            let tenant = TenantId(input.text()?);
            let namespace = StateNamespaceId(input.text()?);
            let incarnation = input.number()?;
            match input.byte()? {
                0 => {}
                1 => {
                    input.text()?;
                }
                _ => return Err(StoreError::Corrupt),
            }
            if input.0.is_empty() || input.0.len() > contract::KEY_BYTES {
                return Err(StoreError::Corrupt);
            }
            let namespace = namespace_in(view, &tenant, &namespace, incarnation)?;
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
