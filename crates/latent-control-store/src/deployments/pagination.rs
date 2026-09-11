//! Bounded management pages over an immutable catalog's tenant-scoped indexes.

use std::collections::hash_map::RandomState;
use std::hash::BuildHasher;
use std::mem::size_of;
use std::sync::Arc;

use super::compiler::{ObjectVersions, RecordIndex, RevisionRecord};
use super::{error, DirectoryDeploymentRepository, DirectoryDeploymentRepositoryConfig};
use crate::VersionedDeployment;
use latent_core::{
    DeploymentId, PlatformError, PlatformErrorCode, RouteGeneration, ServiceId, TenantId,
};

#[cfg(test)]
pub(super) mod instrumentation;

/// The authenticated tenant is supplied by the management adapter, independently of tokens.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeploymentPageRequest {
    pub tenant: TenantId,
    pub service: Option<ServiceId>,
    pub page_size: u32,
    pub page_token: Option<String>,
}

/// All records belong to one immutable catalog generation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeploymentPage {
    pub deployments: Vec<VersionedDeployment>,
    pub next_page_token: Option<String>,
    pub catalog_generation: RouteGeneration,
}

/// Generation-local positions; all identifiers remain in the shared records.
#[derive(Default)]
pub(super) struct DeploymentIndex {
    by_tenant: Box<[RecordIndex]>,
    by_service: Box<[RecordIndex]>,
    encoded_bytes: Box<[usize]>,
    retained_bytes: usize,
}

impl DeploymentIndex {
    pub(super) fn build(
        records: &[Arc<RevisionRecord>],
        versions: &ObjectVersions,
        config: DirectoryDeploymentRepositoryConfig,
        max_retained_bytes: usize,
    ) -> Result<Self, PlatformError> {
        if !valid_page_config(config) {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-catalog-limits",
            ));
        }
        if records.len() != versions.len()
            || records
                .windows(2)
                .any(|pair| pair[0].deployment.id >= pair[1].deployment.id)
        {
            return Err(invalid_versions());
        }
        // The three exact-capacity arrays are charged before their allocation.
        let retained_bytes = records
            .len()
            .checked_mul(2 * size_of::<RecordIndex>() + size_of::<usize>())
            .and_then(|bytes| bytes.checked_add(size_of::<Self>()))
            .filter(|bytes| *bytes <= max_retained_bytes)
            .ok_or_else(|| {
                error(
                    PlatformErrorCode::ResourceExhausted,
                    "catalog-state-byte-limit",
                )
            })?;
        let mut by_tenant = Vec::with_capacity(records.len());
        let mut encoded_bytes = Vec::with_capacity(records.len());
        for (position, record) in records.iter().enumerate() {
            let manifest = &record.deployment;
            manifest
                .metadata
                .tenant
                .as_ref()
                .ok_or_else(invalid_versions)?;
            let version = versions
                .get(&manifest.id)
                .filter(|version| **version != 0)
                .ok_or_else(invalid_versions)?;
            // Compiler-owned canonical bytes are the same codec output used by
            // persistence. Object stamps belong to this generation, not the Arc.
            let encoded = record
                .attributes
                .get("lsf.deployment")
                .ok_or_else(invalid_versions)?;
            let digits = usize::try_from(version.ilog10() + 1).map_err(|_| page_byte_limit())?;
            // Exact compact JSON record accounting, independent of RPC transport framing.
            let bytes = encoded
                .len()
                .checked_add(b"{\"manifest\":,\"generation\":}".len())
                .and_then(|bytes| bytes.checked_add(digits))
                .ok_or_else(page_byte_limit)?;
            by_tenant.push(RecordIndex(position));
            encoded_bytes.push(bytes);
        }
        let mut by_service = by_tenant.clone();
        by_tenant.sort_unstable_by(|left, right| {
            let left = row_key(records, *left);
            let right = row_key(records, *right);
            (left.0, left.2).cmp(&(right.0, right.2))
        });
        by_service.sort_unstable_by_key(|index| row_key(records, *index));
        Ok(Self {
            by_tenant: by_tenant.into_boxed_slice(),
            by_service: by_service.into_boxed_slice(),
            encoded_bytes: encoded_bytes.into_boxed_slice(),
            retained_bytes,
        })
    }

    pub(super) fn retained_bytes(&self) -> usize {
        self.retained_bytes
    }

    pub(super) fn selected<'a>(
        &'a self,
        records: &[Arc<RevisionRecord>],
        tenant: &TenantId,
        service: Option<&ServiceId>,
        after: Option<&DeploymentId>,
    ) -> &'a [RecordIndex] {
        let rows = if service.is_some() {
            &self.by_service
        } else {
            &self.by_tenant
        };
        let scope = |index: &RecordIndex| {
            let key = row_key(records, *index);
            key.0.cmp(tenant.0.as_str()).then_with(|| {
                service.map_or(std::cmp::Ordering::Equal, |service| {
                    key.1.cmp(service.0.as_str())
                })
            })
        };
        let start = rows.partition_point(|index| scope(index).is_lt());
        let end = rows.partition_point(|index| !scope(index).is_gt());
        let selected = &rows[start..end];
        let offset = after.map_or(0, |after| {
            selected.partition_point(|index| records[index.0].deployment.id <= *after)
        });
        &selected[offset..]
    }

    pub(super) fn encoded_row_bytes(&self, index: RecordIndex) -> usize {
        self.encoded_bytes[index.0]
    }
}

fn row_key(records: &[Arc<RevisionRecord>], index: RecordIndex) -> (&str, &str, &str) {
    let manifest = &records[index.0].deployment;
    (
        &manifest
            .metadata
            .tenant
            .as_ref()
            .expect("indexed tenant was checked")
            .0,
        &manifest.service.0,
        &manifest.id.0,
    )
}

pub(super) fn valid_page_config(config: DirectoryDeploymentRepositoryConfig) -> bool {
    config.max_page_size != 0 && config.max_page_bytes != 0 && token_bound(config).is_some()
}

fn token_bound(config: DirectoryDeploymentRepositoryConfig) -> Option<usize> {
    config.max_identifier_bytes.checked_mul(6)?.checked_add(64)
}

impl DirectoryDeploymentRepository {
    /// Selects at most `page_size + 1` indexed rows and clones only accepted records.
    /// Tokens expire on any catalog publication or reopening of the repository.
    pub fn list_deployment_page(
        &self,
        request: &DeploymentPageRequest,
    ) -> Result<DeploymentPage, PlatformError> {
        if request.page_size == 0 || request.page_size > self.config.max_page_size {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-deployment-page-size",
            ));
        }
        if !valid_identifier(&request.tenant.0, self.config.max_identifier_bytes)
            || request.service.as_ref().is_some_and(|service| {
                !valid_identifier(&service.0, self.config.max_identifier_bytes)
            })
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-deployment-page-scope",
            ));
        }
        let cursor = request
            .page_token
            .as_deref()
            .map(|raw| decode_token(raw, request, self.config, &self.pagination_fingerprint))
            .transpose()?;
        let catalog = self.read_catalog();
        let generation = catalog.generation;
        if cursor
            .as_ref()
            .is_some_and(|cursor| cursor.generation != generation)
        {
            return Err(error(
                PlatformErrorCode::StateConflict,
                "expired-deployment-page-token",
            ));
        }
        let mut page = DeploymentPage {
            deployments: Vec::new(),
            next_page_token: None,
            catalog_generation: generation,
        };
        let rows = catalog.paging_index.selected(
            &catalog.records,
            &request.tenant,
            request.service.as_ref(),
            cursor.as_ref().map(|cursor| &cursor.last_id),
        );
        let page_size = usize::try_from(request.page_size).map_err(|_| page_byte_limit())?;
        let mut used_bytes = 0_usize;
        let mut has_more = false;
        for index in rows {
            #[cfg(test)]
            instrumentation::selected();
            let next_bytes = used_bytes.checked_add(catalog.paging_index.encoded_row_bytes(*index));
            if page.deployments.len() == page_size
                || next_bytes.is_none_or(|bytes| bytes > self.config.max_page_bytes)
            {
                if page.deployments.is_empty() {
                    return Err(page_byte_limit());
                }
                has_more = true;
                break;
            }
            let manifest = &catalog.record(*index).deployment;
            let version = *catalog
                .versions
                .get(&manifest.id)
                .ok_or_else(invalid_versions)?;
            #[cfg(test)]
            instrumentation::cloned();
            page.deployments.push(VersionedDeployment {
                manifest: (**manifest).clone(),
                generation: version,
            });
            used_bytes = next_bytes.expect("accepted row fits the page byte budget");
        }
        if has_more {
            let last = &page
                .deployments
                .last()
                .expect("nonempty continued page")
                .manifest
                .id;
            page.next_page_token = Some(encode_token(
                request,
                generation,
                last,
                &self.pagination_fingerprint,
            ));
        }
        Ok(page)
    }
}

struct Cursor {
    generation: RouteGeneration,
    last_id: DeploymentId,
}

fn encode_token(
    request: &DeploymentPageRequest,
    generation: RouteGeneration,
    last_id: &DeploymentId,
    fingerprint: &RandomState,
) -> String {
    let tag = token_tag(
        fingerprint,
        generation,
        &request.tenant.0,
        request.service.as_ref().map(|service| service.0.as_str()),
        &last_id.0,
    );
    format!(
        "d1:{:016x}:{}:{}:{}:{tag:016x}",
        generation.0,
        encode_hex(request.tenant.0.as_bytes()),
        request.service.as_ref().map_or_else(
            || "-".to_owned(),
            |service| encode_hex(service.0.as_bytes())
        ),
        encode_hex(last_id.0.as_bytes())
    )
}

fn decode_token(
    raw: &str,
    request: &DeploymentPageRequest,
    config: DirectoryDeploymentRepositoryConfig,
    fingerprint: &RandomState,
) -> Result<Cursor, PlatformError> {
    if raw.len() > token_bound(config).ok_or_else(invalid_token)? {
        return Err(invalid_token());
    }
    let mut fields = raw.split(':');
    if fields.next() != Some("d1") {
        return Err(invalid_token());
    }
    let generation = RouteGeneration(decode_number(fields.next().ok_or_else(invalid_token)?)?);
    let tenant = decode_identifier(
        fields.next().ok_or_else(invalid_token)?,
        config.max_identifier_bytes,
    )?;
    let service = match fields.next().ok_or_else(invalid_token)? {
        "-" => None,
        encoded => Some(decode_identifier(encoded, config.max_identifier_bytes)?),
    };
    let last_id = decode_identifier(
        fields.next().ok_or_else(invalid_token)?,
        config.max_identifier_bytes,
    )?;
    let tag = decode_number(fields.next().ok_or_else(invalid_token)?)?;
    if fields.next().is_some()
        || tenant != request.tenant.0
        || service.as_deref() != request.service.as_ref().map(|service| service.0.as_str())
        || tag
            != token_tag(
                fingerprint,
                generation,
                &tenant,
                service.as_deref(),
                &last_id,
            )
    {
        return Err(invalid_token());
    }
    Ok(Cursor {
        generation,
        last_id: DeploymentId(last_id),
    })
}

fn token_tag(
    fingerprint: &RandomState,
    generation: RouteGeneration,
    tenant: &str,
    service: Option<&str>,
    last_id: &str,
) -> u64 {
    // A per-open opaque-token fingerprint, not an authorization decision or crypto MAC.
    fingerprint.hash_one((
        "lsf-deployment-page-v1",
        generation.0,
        tenant,
        service,
        last_id,
    ))
}

fn encode_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        encoded.push(char::from(HEX[usize::from(byte >> 4)]));
        encoded.push(char::from(HEX[usize::from(byte & 15)]));
    }
    encoded
}

fn decode_identifier(encoded: &str, maximum: usize) -> Result<String, PlatformError> {
    if !encoded.len().is_multiple_of(2) || encoded.len() / 2 > maximum {
        return Err(invalid_token());
    }
    let mut bytes = Vec::with_capacity(encoded.len() / 2);
    for pair in encoded.as_bytes().chunks_exact(2) {
        bytes.push((hex_digit(pair[0])? << 4) | hex_digit(pair[1])?);
    }
    let decoded = String::from_utf8(bytes).map_err(|_| invalid_token())?;
    if !valid_identifier(&decoded, maximum) {
        return Err(invalid_token());
    }
    Ok(decoded)
}

fn decode_number(encoded: &str) -> Result<u64, PlatformError> {
    if encoded.len() != 16 || encoded.bytes().any(|byte| hex_digit(byte).is_err()) {
        return Err(invalid_token());
    }
    u64::from_str_radix(encoded, 16).map_err(|_| invalid_token())
}

fn hex_digit(byte: u8) -> Result<u8, PlatformError> {
    match byte {
        b'0'..=b'9' => Ok(byte - b'0'),
        b'a'..=b'f' => Ok(byte - b'a' + 10),
        _ => Err(invalid_token()),
    }
}

fn valid_identifier(value: &str, maximum: usize) -> bool {
    !value.is_empty() && value.len() <= maximum && !value.chars().any(char::is_control)
}

fn invalid_token() -> PlatformError {
    error(
        PlatformErrorCode::InvalidArgument,
        "invalid-deployment-page-token",
    )
}

fn invalid_versions() -> PlatformError {
    error(
        PlatformErrorCode::CorruptArtifact,
        "invalid-deployment-object-generations",
    )
}

fn page_byte_limit() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "deployment-page-byte-limit",
    )
}
