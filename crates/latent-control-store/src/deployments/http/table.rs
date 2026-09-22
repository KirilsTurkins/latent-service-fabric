use crate::{
    deployment_operations::budget::{Budget, Charge},
    http_routes::{
        codec, corrupt,
        definition::{self, Matcher},
        TriggerOperationAction, TriggerOperationReceipt, TriggerTargetIdentity, VersionedTrigger,
        MAX_DEFINITION_BYTES, MAX_IDENTIFIER_BYTES, MAX_RECORDS, MAX_TABLE_BYTES,
    },
};
use latent_artifacts::{LifecycleScope, PublicationRef};
use latent_core::{ArtifactBlobDigest, PlatformError, ReleaseDigest};
use latent_manifest::{
    __serde::{Deserialize, Serialize},
    JsonManifestCodec, ManifestCodec, TriggerManifest, TriggerTarget,
};
use std::sync::Arc;

pub(in crate::deployments) const RECEIPTS: usize = 64;
#[derive(Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", deny_unknown_fields)]
pub(in crate::deployments) struct StoredRecord {
    pub manifest: String,
    pub generation: u64,
    // Present only in format-v1 application-only state.
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "crate::rollouts::codec::optional"
    )]
    pub component: Option<ReleaseDigest>,
    // Present only in format-v2 state.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target: Option<TriggerTargetIdentity>,
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", deny_unknown_fields)]
pub(in crate::deployments) struct TableData {
    pub format_version: u32,
    pub sequence: u64,
    pub records: Vec<StoredRecord>,
    pub receipts: Vec<TriggerOperationReceipt>,
}
pub(super) struct Row {
    pub manifest: TriggerManifest,
    pub matcher: Matcher,
    pub target: TriggerTargetIdentity,
}
pub(in crate::deployments) struct HttpTable {
    pub data: TableData,
    pub(super) rows: Vec<Row>,
    pub enabled: bool,
    _charge: Charge,
}
impl HttpTable {
    pub fn empty(budget: &Arc<Budget>) -> Result<Arc<Self>, PlatformError> {
        Self::new(
            TableData {
                format_version: 2,
                sequence: 0,
                records: Vec::new(),
                receipts: Vec::new(),
            },
            budget,
            0,
            0,
        )
    }
    pub fn new(
        data: TableData,
        budget: &Arc<Budget>,
        state: u64,
        route: u64,
    ) -> Result<Arc<Self>, PlatformError> {
        let reservation = budget.reserve(MAX_TABLE_BYTES)?;
        Self::from_reserved(data, reservation, state, route)
    }
    #[expect(
        clippy::too_many_lines,
        reason = "bounded recovery validates table order, canonical matchers and cross-record receipt associations under one reservation"
    )]
    pub fn from_reserved(
        data: TableData,
        mut charge: Charge,
        state: u64,
        route: u64,
    ) -> Result<Arc<Self>, PlatformError> {
        if !matches!(data.format_version, 1 | 2)
            || data.records.len() > MAX_RECORDS
            || data.receipts.len() as u64 != data.sequence.min(RECEIPTS as u64)
            || data.sequence > state
            || (data.sequence == 0 && !data.records.is_empty())
        {
            return Err(corrupt());
        }
        let mut retained = 1024usize
            .saturating_add(
                data.records
                    .capacity()
                    .saturating_mul(std::mem::size_of::<StoredRecord>()),
            )
            .saturating_add(
                data.receipts
                    .capacity()
                    .saturating_mul(std::mem::size_of::<TriggerOperationReceipt>()),
            )
            .saturating_add(
                data.records
                    .len()
                    .saturating_mul(std::mem::size_of::<Row>()),
            );
        let mut rows: Vec<Row> = Vec::with_capacity(data.records.len());
        for stored in &data.records {
            if stored.manifest.capacity() > MAX_DEFINITION_BYTES
                || stored.generation == 0
                || stored.generation > state
                || stored.component.0.capacity() > 71
                || stored.component.0.parse::<ArtifactBlobDigest>().is_err()
            {
                return Err(corrupt());
            }
            // Four serialized lengths plus a fixed node allowance cover the
            // retained canonical string, decoded strings/maps, matcher and keys.
            retained = retained.saturating_add(4 * stored.manifest.capacity() + 4096);
            if retained > MAX_TABLE_BYTES {
                return Err(crate::http_routes::capacity());
            }
            let decoded = JsonManifestCodec::default()
                .decode_trigger(stored.manifest.as_bytes())
                .map_err(|_| corrupt())?;
            let (manifest, matcher) = definition::normalize(decoded).map_err(|_| corrupt())?;
            if manifest
                .target
                .deployment_generation
                .is_none_or(|g| g > route)
            {
                return Err(corrupt());
            }
            if codec::manifest(&manifest)? != stored.manifest {
                return Err(corrupt());
            }
            let key = (&manifest.metadata.tenant, &manifest.id);
            if rows
                .last()
                .is_some_and(|last| (&last.manifest.metadata.tenant, &last.manifest.id) >= key)
            {
                return Err(corrupt());
            }
            for old in &rows {
                if old.matcher.authority == matcher.authority
                    && (old.manifest.metadata.tenant != manifest.metadata.tenant
                        || old.matcher == matcher)
                {
                    return Err(corrupt());
                }
            }
            rows.push(Row { manifest, matcher });
        }
        let mut last_state = 0;
        let mut ids = std::collections::BTreeSet::new();
        let floor = data.sequence - data.receipts.len() as u64 + 1;
        for (position, r) in data.receipts.iter().enumerate() {
            validate_receipt(r)?;
            if r.state_version <= last_state
                || floor.saturating_add(position as u64) > r.state_version
                || r.state_version > state
                || r.route_generation > route
                || !ids.insert((&r.tenant, &r.operation_id))
            {
                return Err(corrupt());
            }
            last_state = r.state_version;
            retained = retained.saturating_add(2 * r.canonical_bytes()?.len() + 2048);
        }
        for (i, receipt) in data.receipts.iter().enumerate() {
            if data.receipts[i + 1..].iter().any(|later| {
                later.tenant == receipt.tenant && later.trigger_id == receipt.trigger_id
            }) {
                continue;
            }
            let exists = rows.iter().any(|row| {
                row.manifest.metadata.tenant.as_ref().unwrap().0 == receipt.tenant
                    && row.manifest.id.0 == receipt.trigger_id
            });
            if exists != (receipt.action == TriggerOperationAction::Apply) {
                return Err(corrupt());
            }
        }
        for (row, stored) in rows.iter().zip(&data.records) {
            // If the latest command for a live object remains in the window,
            // its manifest and exact association must agree with current state.
            if let Some(r) = data.receipts.iter().rev().find(|r| {
                r.tenant == row.manifest.metadata.tenant.as_ref().unwrap().0
                    && r.trigger_id == row.manifest.id.0
            }) {
                if r.action != TriggerOperationAction::Apply
                    || r.object_generation != stored.generation
                    || r.manifest_digest != codec::hash(stored.manifest.as_bytes())
                    || r.component != stored.component
                    || Some(&r.publication.id) != row.manifest.target.publication.as_ref()
                    || Some(&r.deployment_id) != row.manifest.target.route.as_ref()
                    || Some(&r.revision) != row.manifest.target.revision.as_ref()
                    || Some(r.deployment_generation) != row.manifest.target.deployment_generation
                {
                    return Err(corrupt());
                }
            }
        }
        if retained > MAX_TABLE_BYTES {
            return Err(crate::http_routes::capacity());
        }
        charge.shrink(retained)?;
        Ok(Arc::new(Self {
            enabled: data.sequence != 0,
            data,
            rows,
            _charge: charge,
        }))
    }
    pub fn find(&self, tenant: &str, id: &str) -> Option<&TriggerOperationReceipt> {
        self.data
            .receipts
            .iter()
            .find(|r| r.tenant == tenant && r.operation_id == id)
    }
    pub(super) fn index(&self, tenant: &str, id: &str) -> Option<usize> {
        self.rows
            .binary_search_by(|row| {
                (
                    row.manifest.metadata.tenant.as_ref().unwrap().0.as_str(),
                    row.manifest.id.0.as_str(),
                )
                    .cmp(&(tenant, id))
            })
            .ok()
    }
    pub(super) fn versioned(&self, index: usize) -> VersionedTrigger {
        VersionedTrigger {
            manifest: self.rows[index].manifest.clone(),
            generation: self.data.records[index].generation,
            component: self.data.records[index].component.clone(),
        }
    }
    pub fn floor(&self) -> u64 {
        self.data
            .sequence
            .saturating_sub(self.data.receipts.len() as u64)
            .saturating_add(1)
    }
}

fn validate_receipt(r: &TriggerOperationReceipt) -> Result<(), PlatformError> {
    for value in [
        &r.tenant,
        &r.actor.subject,
        &r.operation_id,
        &r.trigger_id,
        &r.deployment_id,
    ] {
        if value.capacity() > MAX_IDENTIFIER_BYTES
            || !definition::token(value, MAX_IDENTIFIER_BYTES)
        {
            return Err(corrupt());
        }
    }
    r.actor.validate().map_err(|_| corrupt())?;
    if r.format_version != 1
        || r.expected_state_version.checked_add(1) != Some(r.state_version)
        || r.route_generation == 0
        || r.route_generation > r.state_version
        || r.deployment_generation == 0
        || r.deployment_generation > r.route_generation
        || r.publication
            .scope
            .tenant()
            .is_none_or(|t| t.0 != r.tenant || t.0.capacity() > MAX_IDENTIFIER_BYTES)
        || r.revision.capacity() > 83
        || r.revision
            .strip_prefix("revision-v1:")
            .is_none_or(|s| s.parse::<ArtifactBlobDigest>().is_err())
        || [
            &r.request_digest,
            &r.manifest_digest,
            &r.receipt_digest,
            &r.component.0,
        ]
        .iter()
        .any(|s| s.capacity() > 71 || s.parse::<ArtifactBlobDigest>().is_err())
        || codec::receipt_hash(r)? != r.receipt_digest
    {
        return Err(corrupt());
    }
    match r.action {
        TriggerOperationAction::Apply
            if r.object_generation == r.state_version
                && r.expected_generation < r.object_generation => {}
        TriggerOperationAction::Delete
            if r.object_generation == r.expected_generation
                && r.object_generation > 0
                && r.object_generation < r.state_version => {}
        _ => return Err(corrupt()),
    }
    r.canonical_bytes()?;
    Ok(())
}
