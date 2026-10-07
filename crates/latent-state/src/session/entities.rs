//! Bounded descriptive entity discovery over one borrowed actual snapshot.
//! Caller/policy/cursor authority remains with the protected host adapter.

use super::{codec, validation, version, StateError, StateMode, StateScope};
use crate::{
    embedded::{Family, ReadView},
    namespace::NamespaceRecord,
};
use latent_core::transaction_contract as contract;
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

const SCAN_PAGE_BYTES: usize = 2 * 1024 * 1024;
const SCAN_ROWS: usize = 65536;
const SCAN_BYTES: usize = 128 * 1024 * 1024;
const ENTITY_COUNT: usize = 2048;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntityInspection {
    pub entity: String,
    pub version: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntityPage {
    pub entities: Vec<EntityInspection>,
    pub continuation: Option<[u8; 32]>,
    pub view: version::ViewIdentity,
}

#[derive(Clone, Copy)]
pub struct EntityPageRequest<'a> {
    pub prefix: &'a [u8],
    pub after: Option<[u8; 32]>,
    pub expected_view: Option<version::ViewIdentity>,
    pub maximum: usize,
}

/// Live values and retained tombstones both preserve an entity's identity.
/// Namespace-wide cells and command-only identities are not entity state.
/// The bounded full scan fails on a ceiling; it never reports false exhaustion.
pub fn inspect_entities(
    view: &ReadView,
    namespace: &NamespaceRecord,
    request: EntityPageRequest<'_>,
    mut current: impl FnMut() -> Result<(), StateError>,
) -> Result<EntityPage, StateError> {
    if request.maximum == 0
        || request.maximum > 128
        || request.prefix.len() > contract::IDENTITY_BYTES
    {
        return Err(StateError::Limit);
    }
    if request.after.is_some() != request.expected_view.is_some() {
        return Err(StateError::InvalidCursor);
    }
    let mut scope = StateScope {
        tenant: namespace.tenant.clone(),
        namespace: namespace.id.clone(),
        incarnation: namespace.version.incarnation,
        state_schema: namespace.state_schema.clone(),
        entity: None,
        mode: StateMode::Query,
    };
    current()?;
    let identity = version::capture_view_identity(view, &scope)?;
    if identity.namespace != namespace.version {
        return Err(StateError::Conflict);
    }
    if request
        .expected_view
        .is_some_and(|expected| expected != identity)
    {
        return Err(StateError::InvalidCursor);
    }
    let entities = collect_entities(view, namespace, &request, &scope, &mut current)?;
    let mut passed = request.after.is_none();
    let mut output = Vec::with_capacity(request.maximum);
    let mut more = false;
    for entity in entities {
        let digest: [u8; 32] = Sha256::digest(entity.as_bytes()).into();
        if !passed {
            passed = Some(digest) == request.after;
            continue;
        }
        if output.len() == request.maximum {
            more = true;
            break;
        }
        scope.entity = Some(entity.clone());
        output.push(EntityInspection {
            entity,
            version: identity.token(&scope)?,
        });
    }
    if !passed {
        return Err(StateError::InvalidCursor);
    }
    current()?;
    let continuation = if more {
        Some(Sha256::digest(output.last().ok_or(StateError::Corrupt)?.entity.as_bytes()).into())
    } else {
        None
    };
    Ok(EntityPage {
        entities: output,
        continuation,
        view: identity,
    })
}

fn collect_entities(
    view: &ReadView,
    namespace: &NamespaceRecord,
    request: &EntityPageRequest<'_>,
    scope: &StateScope,
    current: &mut impl FnMut() -> Result<(), StateError>,
) -> Result<BTreeSet<String>, StateError> {
    let mut physical_prefix = codec::key_prefix(scope)?;
    if physical_prefix.pop() != Some(0) {
        return Err(StateError::Corrupt);
    }
    physical_prefix.push(1);
    let mut after = None;
    let mut rows = 0usize;
    let mut bytes = 0usize;
    let mut entities = BTreeSet::new();
    loop {
        current()?;
        let page = view.scan_after(
            Family::State,
            &physical_prefix,
            after.as_deref(),
            128,
            SCAN_PAGE_BYTES,
        )?;
        for (key, value) in page.rows {
            current()?;
            rows = rows.checked_add(1).ok_or(StateError::Limit)?;
            bytes = bytes
                .checked_add(key.key.len() + value.len())
                .ok_or(StateError::Limit)?;
            if rows > SCAN_ROWS || bytes > SCAN_BYTES {
                return Err(StateError::Limit);
            }
            let persisted = validation::cell_identity(&key.key)?;
            if persisted.tenant != namespace.tenant
                || persisted.namespace != namespace.id
                || persisted.incarnation != namespace.version.incarnation
            {
                return Err(StateError::Corrupt);
            }
            let entity = persisted.entity.ok_or(StateError::Corrupt)?;
            // Validate even a filtered row; unknown formats cannot become absence.
            codec::Cell::decode(&value, namespace.version.generation)?;
            if entity.as_bytes().starts_with(request.prefix) {
                if entities.len() == ENTITY_COUNT && !entities.contains(&entity) {
                    return Err(StateError::Limit);
                }
                entities.insert(entity);
            }
        }
        after = page.resume;
        if after.is_none() {
            break;
        }
    }
    Ok(entities)
}
