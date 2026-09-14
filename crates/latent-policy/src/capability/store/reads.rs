use super::super::{capacity, error, identifier, invalid};
use super::{
    codec, mutation::check_deadline, OperationReceipt, PolicyRead, PolicyStore, RecordKind,
    RecordView,
};
use latent_core::{PlatformError, PlatformErrorCode};
use serde::Serialize;
use std::time::Instant;

pub struct PolicyPageRequest<'a> {
    pub tenant: &'a str,
    pub kind: RecordKind,
    pub cursor: Option<&'a str>,
    pub limit: usize,
    pub maximum_bytes: usize,
    pub deadline: Instant,
}
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PolicyPage {
    pub generation: u64,
    pub records: Vec<RecordView>,
    pub next_cursor: Option<String>,
}
impl PolicyStore {
    pub fn get(
        &self,
        tenant: &str,
        kind: RecordKind,
        id: &str,
        maximum_bytes: usize,
        deadline: Instant,
    ) -> Result<PolicyRead<Option<RecordView>>, PlatformError> {
        bounds(tenant, id, maximum_bytes, deadline)?;
        let lease = self.owner.lease()?;
        let state = self.lock()?;
        let value = state
            .image
            .records
            .iter()
            .find(|row| row.matches(tenant, kind, id));
        if value.is_some_and(|value| cost(value) > maximum_bytes) {
            return Err(capacity());
        }
        check_deadline(deadline)?;
        Ok(PolicyRead {
            value: value.cloned(),
            lease,
        })
    }
    pub fn outcome(
        &self,
        tenant: &str,
        operation_id: &str,
        deadline: Instant,
    ) -> Result<PolicyRead<Option<OperationReceipt>>, PlatformError> {
        bounds(tenant, operation_id, 4096, deadline)?;
        let lease = self.owner.lease()?;
        let state = self.lock()?;
        let value = state
            .image
            .outcomes
            .iter()
            .find(|value| {
                value.receipt.tenant == tenant && value.receipt.operation_id == operation_id
            })
            .map(|value| value.receipt.clone());
        check_deadline(deadline)?;
        Ok(PolicyRead { value, lease })
    }
    pub fn list(
        &self,
        request: &PolicyPageRequest<'_>,
    ) -> Result<PolicyRead<PolicyPage>, PlatformError> {
        bounds(
            request.tenant,
            "list",
            request.maximum_bytes,
            request.deadline,
        )?;
        if request.limit == 0 || request.limit > self.limits.maximum_page_records {
            return Err(invalid());
        }
        let lease = self.owner.lease()?;
        let state = self.lock()?;
        let generation = state.image.generation;
        let now = self.started.elapsed().as_secs();
        let (mut offset, expires) = match request.cursor {
            Some(cursor) => {
                decode_cursor(cursor, request, generation, now, &state.ledger.cursor_key)?
            }
            None => (0, now.checked_add(300).ok_or_else(capacity)?),
        };
        if offset > state.image.records.len() {
            return Err(invalid());
        }
        let mut page = PolicyPage {
            generation,
            records: Vec::new(),
            next_cursor: None,
        };
        let mut used = 1024;
        while let Some(row) = state.image.records.get(offset) {
            check_deadline(request.deadline)?;
            if row.tenant == request.tenant && row.kind == request.kind {
                if page.records.len() == request.limit {
                    break;
                }
                let cost = cost(row);
                if cost > request.maximum_bytes - used {
                    if page.records.is_empty() {
                        return Err(capacity());
                    }
                    break;
                }
                used += cost;
                page.records.push(row.clone());
            }
            offset += 1;
        }
        if offset < state.image.records.len() {
            page.next_cursor = Some(cursor(
                request,
                generation,
                offset,
                expires,
                &state.ledger.cursor_key,
            )?);
        }
        check_deadline(request.deadline)?;
        Ok(PolicyRead { value: page, lease })
    }
}
fn bounds(
    tenant: &str,
    id: &str,
    maximum_bytes: usize,
    deadline: Instant,
) -> Result<(), PlatformError> {
    if !identifier(tenant) || !identifier(id) || !(4096..=1024 * 1024).contains(&maximum_bytes) {
        return Err(invalid());
    }
    check_deadline(deadline)
}
fn cost(row: &RecordView) -> usize {
    2048 + row.document.as_ref().map_or(0, |v| v.len() * 2)
}
fn cursor(
    request: &PolicyPageRequest<'_>,
    generation: u64,
    offset: usize,
    expires: u64,
    key: &[u8; 32],
) -> Result<String, PlatformError> {
    let fields = codec::encode(
        &(
            "lsf-policy-cursor-v1",
            request.tenant,
            request.kind,
            generation,
            offset,
            expires,
        ),
        512,
    )?;
    Ok(format!(
        "1:{generation:016x}:{offset:016x}:{expires:016x}:{}",
        blake3::keyed_hash(key, &fields).to_hex()
    ))
}
fn decode_cursor(
    value: &str,
    request: &PolicyPageRequest<'_>,
    generation: u64,
    now: u64,
    key: &[u8; 32],
) -> Result<(usize, u64), PlatformError> {
    if value.len() != 117 || !value.is_ascii() {
        return Err(invalid());
    }
    let parts: Vec<_> = value.split(':').collect();
    if parts.len() != 5 || parts[0] != "1" {
        return Err(invalid());
    }
    let token_generation = u64::from_str_radix(parts[1], 16).map_err(|_| invalid())?;
    let offset = usize::from_str_radix(parts[2], 16).map_err(|_| invalid())?;
    let expires = u64::from_str_radix(parts[3], 16).map_err(|_| invalid())?;
    // Check the public canonical prefix separately, and authenticate the MAC
    // using Hash's constant-time equality rather than comparing hex strings.
    let expected = cursor(request, token_generation, offset, expires, key)?;
    let supplied_mac = blake3::Hash::from_hex(parts[4]).map_err(|_| invalid())?;
    let expected_mac = blake3::Hash::from_hex(&expected[53..]).map_err(|_| invalid())?;
    if expected[..53] != value[..53]
        || parts[4].bytes().any(|byte| byte.is_ascii_uppercase())
        || supplied_mac != expected_mac
    {
        return Err(invalid());
    }
    if token_generation != generation || now >= expires {
        return Err(error(
            PlatformErrorCode::StateConflict,
            "capability-policy-cursor-stale",
        ));
    }
    Ok((offset, expires))
}
