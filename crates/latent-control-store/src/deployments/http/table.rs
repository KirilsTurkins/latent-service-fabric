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
            {
                return Err(corrupt());
            }
            // Four serialized lengths plus a fixed node allowance cover the
            // retained canonical string, decoded strings/maps, matcher and keys.
            retained = retained.saturating_add(4 * stored.manifest.capacity() + 6144);
            if retained > MAX_TABLE_BYTES {
                return Err(crate::http_routes::capacity());
            }
            let decoded = JsonManifestCodec::default()
                .decode_trigger(stored.manifest.as_bytes())
                .map_err(|_| corrupt())?;
            let (manifest, matcher) = definition::normalize(decoded).map_err(|_| corrupt())?;
            if codec::manifest(&manifest)? != stored.manifest {
                return Err(corrupt());
            }
            let target = match data.format_version {
                1 => {
                    if stored.target.is_some() {
                        return Err(corrupt());
                    }
                    legacy_target(&manifest, stored.component.as_ref().ok_or_else(corrupt)?)?
                }
                2 => {
                    if stored.component.is_some() {
                        return Err(corrupt());
                    }
                    stored.target.clone().ok_or_else(corrupt)?
                }
                _ => return Err(corrupt()),
            };
            validate_target(&manifest, &target, route)?;
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
            rows.push(Row {
                manifest,
                matcher,
                target,
            });
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
                    || r.target_identity().as_ref() != Some(&row.target)
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
            component: self.rows[index].target.component().cloned(),
        }
    }
    pub fn floor(&self) -> u64 {
        self.data
            .sequence
            .saturating_sub(self.data.receipts.len() as u64)
            .saturating_add(1)
    }
}

fn legacy_target(
    manifest: &TriggerManifest,
    component: &ReleaseDigest,
) -> Result<TriggerTargetIdentity, PlatformError> {
    let tenant = manifest.metadata.tenant.clone().ok_or_else(corrupt)?;
    let TriggerTarget::Application(target) = &manifest.target else {
        return Err(corrupt());
    };
    Ok(TriggerTargetIdentity::Application {
        publication: PublicationRef {
            id: target.publication.clone().ok_or_else(corrupt)?,
            scope: LifecycleScope::Tenant(tenant),
        },
        component: component.clone(),
        deployment_id: target.route.clone().ok_or_else(corrupt)?,
        deployment_generation: target.deployment_generation.ok_or_else(corrupt)?,
        revision: target.revision.clone().ok_or_else(corrupt)?,
    })
}

fn validate_target(
    manifest: &TriggerManifest,
    target: &TriggerTargetIdentity,
    route_generation: u64,
) -> Result<(), PlatformError> {
    let tenant = manifest.metadata.tenant.as_ref().ok_or_else(corrupt)?;
    if target
        .publication()
        .scope
        .tenant()
        .is_none_or(|scope| scope != tenant)
    {
        return Err(corrupt());
    }
    match (target, &manifest.target) {
        (
            TriggerTargetIdentity::Application {
                publication,
                component,
                deployment_id,
                deployment_generation,
                revision,
            },
            TriggerTarget::Application(manifest_target),
        ) => {
            if component.0.capacity() > 71
                || component.0.parse::<ArtifactBlobDigest>().is_err()
                || deployment_id.capacity() > MAX_IDENTIFIER_BYTES
                || !definition::token(deployment_id, MAX_IDENTIFIER_BYTES)
                || *deployment_generation == 0
                || *deployment_generation > route_generation
                || revision.capacity() > 83
                || revision
                    .strip_prefix("revision-v1:")
                    .is_none_or(|digest| digest.parse::<ArtifactBlobDigest>().is_err())
                || manifest_target.publication.as_ref() != Some(&publication.id)
                || manifest_target.route.as_ref() != Some(deployment_id)
                || manifest_target.deployment_generation != Some(*deployment_generation)
                || manifest_target.revision.as_ref() != Some(revision)
            {
                return Err(corrupt());
            }
        }
        (
            TriggerTargetIdentity::StaticWeb {
                publication,
                web_manifest_digest,
                assets_digest,
                web_generation,
            },
            TriggerTarget::StaticWeb(manifest_target),
        ) => {
            if manifest_target.publication != publication.id
                || *web_generation == 0
                || [web_manifest_digest, assets_digest].iter().any(|digest| {
                    digest.capacity() > 71 || digest.parse::<ArtifactBlobDigest>().is_err()
                })
            {
                return Err(corrupt());
            }
        }
        _ => return Err(corrupt()),
    }
    Ok(())
}

fn validate_receipt(r: &TriggerOperationReceipt) -> Result<(), PlatformError> {
    for value in [&r.tenant, &r.actor.subject, &r.operation_id, &r.trigger_id] {
        if value.capacity() > MAX_IDENTIFIER_BYTES
            || !definition::token(value, MAX_IDENTIFIER_BYTES)
        {
            return Err(corrupt());
        }
    }
    r.actor.validate().map_err(|_| corrupt())?;
    let target = r.target_identity().ok_or_else(corrupt)?;
    let version_valid = match r.format_version {
        1 => {
            r.target.is_none()
                && r.publication.is_some()
                && r.component.is_some()
                && r.deployment_id.is_some()
                && r.deployment_generation.is_some()
                && r.revision.is_some()
                && matches!(target, TriggerTargetIdentity::Application { .. })
        }
        2 => {
            r.target.is_some()
                && r.publication.is_none()
                && r.component.is_none()
                && r.deployment_id.is_none()
                && r.deployment_generation.is_none()
                && r.revision.is_none()
        }
        _ => false,
    };
    if !version_valid
        || r.expected_state_version.checked_add(1) != Some(r.state_version)
        || r.route_generation > r.state_version
        || target
            .publication()
            .scope
            .tenant()
            .is_none_or(|tenant| tenant.0 != r.tenant || tenant.0.capacity() > MAX_IDENTIFIER_BYTES)
        || [&r.request_digest, &r.manifest_digest, &r.receipt_digest]
            .iter()
            .any(|digest| digest.capacity() > 71 || digest.parse::<ArtifactBlobDigest>().is_err())
        || codec::receipt_hash(r)? != r.receipt_digest
    {
        return Err(corrupt());
    }
    match &target {
        TriggerTargetIdentity::Application {
            component,
            deployment_id,
            deployment_generation,
            revision,
            ..
        } => {
            if component.0.capacity() > 71
                || component.0.parse::<ArtifactBlobDigest>().is_err()
                || deployment_id.capacity() > MAX_IDENTIFIER_BYTES
                || !definition::token(deployment_id, MAX_IDENTIFIER_BYTES)
                || *deployment_generation == 0
                || *deployment_generation > r.route_generation
                || revision.capacity() > 83
                || revision
                    .strip_prefix("revision-v1:")
                    .is_none_or(|digest| digest.parse::<ArtifactBlobDigest>().is_err())
            {
                return Err(corrupt());
            }
        }
        TriggerTargetIdentity::StaticWeb {
            web_manifest_digest,
            assets_digest,
            web_generation,
            ..
        } => {
            if *web_generation == 0
                || [web_manifest_digest, assets_digest].iter().any(|digest| {
                    digest.capacity() > 71 || digest.parse::<ArtifactBlobDigest>().is_err()
                })
            {
                return Err(corrupt());
            }
        }
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
