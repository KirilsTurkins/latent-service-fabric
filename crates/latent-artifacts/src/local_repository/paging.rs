use std::hash::BuildHasher;
use std::ops::Bound::{Excluded, Unbounded};

use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};

use super::{error, lock_error, DirectoryArtifactRepository};
use crate::{ArtifactCatalogEntry, ArtifactCatalogPage, ArtifactCatalogPageRequest};

/// Scope is fingerprinted rather than embedded, so arbitrary accepted scope lengths
/// do not enlarge tokens. a1, generation, SHA-256 hex, and per-open fingerprint.
const TOKEN_BYTES: usize = 101;

impl DirectoryArtifactRepository {
    pub(super) fn catalog_entry(
        &self,
        tenant: &TenantId,
        digest: &ReleaseDigest,
    ) -> Result<Option<ArtifactCatalogEntry>, PlatformError> {
        self.validate_scope(&tenant.0)?;
        super::digest_hex(digest).map_err(|_| {
            error(
                PlatformErrorCode::InvalidArgument,
                "invalid-artifact-catalog-digest",
            )
        })?;
        let index = self.index.read().map_err(lock_error)?;
        let Some(entry) = index
            .by_digest
            .get(digest)
            .filter(|entry| entry.value.tenant.as_ref() == Some(tenant))
        else {
            return Ok(None);
        };
        if entry.page_bytes > self.config.max_page_bytes {
            return Err(page_limit());
        }
        Ok(Some(entry.value.clone()))
    }

    pub(super) fn catalog_page(
        &self,
        request: &ArtifactCatalogPageRequest,
    ) -> Result<ArtifactCatalogPage, PlatformError> {
        self.validate_scope(&request.tenant.0)?;
        if let Some(service) = &request.service {
            self.validate_scope(&service.0)?;
        }
        let page_size = usize::try_from(request.page_size).map_err(|_| invalid_size())?;
        if page_size == 0 || page_size > self.config.max_page_size {
            return Err(invalid_size());
        }
        let cursor = request
            .page_token
            .as_deref()
            .map(|raw| self.decode_token(raw, request))
            .transpose()?;
        let index = self.index.read().map_err(lock_error)?;
        if cursor
            .as_ref()
            .is_some_and(|cursor| cursor.0 != index.generation)
        {
            return Err(error(
                PlatformErrorCode::StateConflict,
                "expired-artifact-page-token",
            ));
        }
        let mut page = ArtifactCatalogPage {
            entries: Vec::new(),
            next_page_token: None,
            catalog_generation: index.generation,
        };
        let Some(rows) = index.rows(&request.tenant, request.service.as_ref()) else {
            return Ok(page);
        };
        let start = cursor
            .as_ref()
            .map_or(Unbounded, |cursor| Excluded(&cursor.1));
        let mut used = 0_usize;
        for digest in rows.range((start, Unbounded)) {
            #[cfg(test)]
            instrumentation::selected();
            let entry = index
                .by_digest
                .get(digest)
                .expect("scoped index and immutable entries install together");
            let next = used.checked_add(entry.page_bytes);
            if page.entries.len() == page_size
                || next.is_none_or(|bytes| bytes > self.config.max_page_bytes)
            {
                let Some(last) = page.entries.last() else {
                    return Err(page_limit());
                };
                page.next_page_token = Some(self.encode_token(
                    request,
                    index.generation,
                    &last.descriptor.release_digest,
                ));
                break;
            }
            // The row charge includes its owned DTO slot. Exact growth avoids an
            // uncharged geometric-capacity tail on short byte-limited pages.
            page.entries
                .try_reserve_exact(1)
                .map_err(|_| page_limit())?;
            #[cfg(test)]
            instrumentation::cloned();
            page.entries.push(entry.value.clone());
            used = next.expect("accepted bounded row");
        }
        Ok(page)
    }

    fn validate_scope(&self, value: &str) -> Result<(), PlatformError> {
        // Reuse the persisted manifest string ceiling; adding a narrower catalog
        // identifier limit would make previously valid immutable releases unqueryable.
        if value.is_empty()
            || value.len() > self.codec.limits().max_string_bytes
            || value.chars().any(char::is_control)
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-artifact-page-scope",
            ));
        }
        Ok(())
    }

    fn tag(&self, request: &ArtifactCatalogPageRequest, generation: u64, hex: &str) -> u64 {
        // Opaque-token fingerprint, not a cryptographic MAC or authorization grant.
        self.pagination_fingerprint.hash_one((
            "artifact-page-v1",
            generation,
            &request.tenant,
            &request.service,
            hex,
        ))
    }

    fn encode_token(
        &self,
        request: &ArtifactCatalogPageRequest,
        generation: u64,
        digest: &ReleaseDigest,
    ) -> String {
        let hex = &digest.0[7..]; // Only verified canonical digests enter this index.
        format!(
            "a1:{generation:016x}:{hex}:{:016x}",
            self.tag(request, generation, hex)
        )
    }

    fn decode_token(
        &self,
        raw: &str,
        request: &ArtifactCatalogPageRequest,
    ) -> Result<(u64, ReleaseDigest), PlatformError> {
        if raw.len() != TOKEN_BYTES {
            return Err(invalid_token());
        }
        let mut fields = raw.split(':');
        if fields.next() != Some("a1") {
            return Err(invalid_token());
        }
        let generation = number(fields.next().ok_or_else(invalid_token)?)?;
        let hex = fields.next().ok_or_else(invalid_token)?;
        if hex.len() != 64 || !hex.bytes().all(is_hex) {
            return Err(invalid_token());
        }
        let tag = number(fields.next().ok_or_else(invalid_token)?)?;
        if fields.next().is_some() || tag != self.tag(request, generation, hex) {
            return Err(invalid_token());
        }
        Ok((generation, ReleaseDigest(format!("sha256:{hex}"))))
    }
}

fn is_hex(byte: u8) -> bool {
    byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)
}
fn number(raw: &str) -> Result<u64, PlatformError> {
    if raw.len() != 16 || !raw.bytes().all(is_hex) {
        return Err(invalid_token());
    }
    u64::from_str_radix(raw, 16).map_err(|_| invalid_token())
}
fn invalid_token() -> PlatformError {
    error(
        PlatformErrorCode::InvalidArgument,
        "invalid-artifact-page-token",
    )
}
fn invalid_size() -> PlatformError {
    error(
        PlatformErrorCode::InvalidArgument,
        "invalid-artifact-page-size",
    )
}
fn page_limit() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "artifact-page-byte-limit",
    )
}

#[cfg(test)]
pub(super) mod instrumentation {
    use std::cell::Cell;
    thread_local! { static COUNTS: Cell<(usize, usize)> = const { Cell::new((0, 0)) }; }
    pub(super) fn selected() {
        COUNTS.with(|counts| {
            let (s, c) = counts.get();
            counts.set((s + 1, c));
        });
    }
    pub(super) fn cloned() {
        COUNTS.with(|counts| {
            let (s, c) = counts.get();
            counts.set((s, c + 1));
        });
    }
    pub(in super::super) fn reset() {
        COUNTS.with(|counts| counts.set((0, 0)));
    }
    pub(in super::super) fn counts() -> (usize, usize) {
        COUNTS.with(Cell::get)
    }
}
