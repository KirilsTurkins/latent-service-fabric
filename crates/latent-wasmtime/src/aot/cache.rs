//! Persistent cache composition; storage names never grant native-code trust.

mod model;
mod observation;
mod paths;
mod persistence;
mod receipts;

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;

pub use model::{NativeAotCacheConfig, NativeAotSettings, NativeAotSnapshot};
pub use receipts::{AotReceiptCacheLimits, AotReceiptCacheSnapshot};

use super::{
    image_budget::NativeImageBudget,
    loader::{self, LoadedNative},
    supervisor::AotPreparedInput,
    AotCompilationJob, IsolatedAotCompiler, ValidatedAotProfile,
};
use crate::WasmtimeConfig;
use latent_artifacts::{
    ArtifactRepository, DirectoryArtifactRepository, RawArtifactCache, RawArtifactKey,
};
use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};
use wasmtime::Engine;

/// This owner has no compiler pool/join owner and is safe in a blocking task.
pub(crate) struct NativeAotService {
    compiler: IsolatedAotCompiler,
    catalog: Arc<DirectoryArtifactRepository>,
    raw: Arc<RawArtifactCache>,
    receipts: Arc<receipts::ReceiptCache>,
    images: Arc<NativeImageBudget>,
    hits: AtomicU64,
    misses: AtomicU64,
    rejected: AtomicU64,
    compilations: AtomicU64,
    persistence_failures: AtomicU64,
    audit: Option<latent_audit::AuditHandle>,
}

impl NativeAotService {
    pub(crate) fn new(
        config: &WasmtimeConfig,
        engine: &Engine,
        catalog: Arc<DirectoryArtifactRepository>,
        settings: NativeAotSettings,
    ) -> Result<Arc<Self>, PlatformError> {
        settings.validate()?;
        let (blob_root, receipt_root) = paths::roots(
            &settings.cache.blob_root,
            &settings.cache.receipt_root,
            catalog.root(),
        )?;
        let profile = ValidatedAotProfile::from_config(config, settings.process.compiler)?;
        profile.check_engine(engine)?;
        let images = NativeImageBudget::new(settings.images)?;
        // Platform/approved binary checks precede all cache-root mutations.
        let compiler = IsolatedAotCompiler::new(
            &settings.executable,
            settings.approved_digest,
            profile,
            settings.authority,
            settings.process,
        )?;
        let raw = RawArtifactCache::open(blob_root, settings.cache.raw)?;
        let receipts = receipts::ReceiptCache::open(&receipt_root, settings.cache.receipts)?;
        Ok(Arc::new(Self {
            compiler,
            catalog,
            raw,
            receipts,
            images,
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
            rejected: AtomicU64::new(0),
            compilations: AtomicU64::new(0),
            persistence_failures: AtomicU64::new(0),
            audit: settings.audit,
        }))
    }

    pub(crate) fn catalog(&self) -> Arc<dyn ArtifactRepository> {
        self.catalog.clone()
    }

    pub(crate) fn reserve(
        &self,
        release: &ReleaseDigest,
    ) -> Result<AotCompilationJob, PlatformError> {
        let source = Arc::clone(&self.catalog)
            .owned_preparation_source()
            .ok_or_else(super::mismatch)?;
        self.compiler.reserve(source, release)
    }

    pub(crate) fn snapshot(&self) -> Result<NativeAotSnapshot, PlatformError> {
        Ok(NativeAotSnapshot {
            producer: self.compiler.snapshot(),
            raw: self.raw.snapshot()?,
            receipts: self.receipts.snapshot(),
            images: self.images.snapshot(),
            cache_hits: self.hits.load(Ordering::Relaxed),
            cache_misses: self.misses.load(Ordering::Relaxed),
            cache_rejections: self.rejected.load(Ordering::Relaxed),
            isolated_compilations: self.compilations.load(Ordering::Relaxed),
            persistence_failures: self.persistence_failures.load(Ordering::Relaxed),
        })
    }

    pub(crate) fn load(
        &self,
        input: &mut AotPreparedInput,
        engine: &Engine,
    ) -> Result<LoadedNative, PlatformError> {
        input.check()?;
        input.check_engine(engine)?;
        let key = input.key().digest();
        match self.lookup(input, engine) {
            Ok(Some(native)) => {
                add(&self.hits);
                observation::capture(self.audit.as_ref(), input.key(), observation::Event::Hit);
                return Ok(native);
            }
            Ok(None) => {
                input.check()?;
                add(&self.misses);
                observation::capture(self.audit.as_ref(), input.key(), observation::Event::Miss);
            }
            Err(error) => {
                // Revocation/deadline/closure is checked independently of cache
                // errors; none can be reinterpreted as a portable fallback.
                input.check()?;
                input.check_engine(engine)?;
                if !corrupt_cache(&error) {
                    return Err(error);
                }
                add(&self.rejected);
                observation::capture(
                    self.audit.as_ref(),
                    input.key(),
                    observation::Event::Corrupt,
                );
                // A failed cleanup remains charged by the receipt owner. It
                // cannot authorize bytes or cause repeated compilation attempts.
                let _ = self.receipts.invalidate(&key);
            }
        }
        input.check()?;
        add(&self.compilations);
        let output = input.compile()?;
        input.check()?;
        if self.persist(&output).is_err() {
            // Persistence is optional for this already owned trusted output.
            // The next preparation will authenticate storage afresh.
            add(&self.persistence_failures);
        }
        input.check()?;
        let proof = input.authenticate_output(&output)?;
        loader::load(input, proof, engine, &self.images)
    }

    fn lookup(
        &self,
        input: &AotPreparedInput,
        engine: &Engine,
    ) -> Result<Option<LoadedNative>, PlatformError> {
        let Some(receipt) = self.receipts.lookup(&input.key().digest())? else {
            return Ok(None);
        };
        input.check()?;
        let proof = input.authenticate_receipt(receipt.as_bytes())?;
        drop(receipt);
        let Some(bytes) = read_cached_blob(&self.raw, &proof)? else {
            return Ok(None);
        };
        input.check()?;
        let proof = proof.authenticate_bytes(&bytes)?;
        loader::load(input, proof, engine, &self.images).map(Some)
    }
}

fn read_cached_blob(
    raw: &Arc<RawArtifactCache>,
    proof: &super::seal::AuthenticatedAotReceipt<'_>,
) -> Result<Option<latent_artifacts::RawArtifactBytes>, PlatformError> {
    let Some(pin) = raw.try_pin(&RawArtifactKey::Blob(proof.output_digest().clone()))? else {
        return Ok(None);
    };
    if pin.size_bytes() != proof.output_size() as u64 {
        return Err(super::error(
            PlatformErrorCode::CorruptArtifact,
            "native-cache-size-mismatch",
        ));
    }
    let read = pin.reserve_read(proof.output_size() as u64)?;
    let bytes = read.read_verified().map_err(|error| {
        if error.code == PlatformErrorCode::NotFound {
            // Only this replaceable-cache file read can become a refill. A
            // missing authoritative catalog source must retain its own failure.
            super::error(
                PlatformErrorCode::CorruptArtifact,
                "native-cache-blob-missing",
            )
        } else {
            error
        }
    })?;
    Ok(Some(bytes))
}

fn corrupt_cache(error: &PlatformError) -> bool {
    error.code == PlatformErrorCode::CorruptArtifact
        || (error.code == PlatformErrorCode::PermissionDenied
            && error.message == "aot-output-authority-mismatch")
}

fn add(counter: &AtomicU64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
        Some(value.saturating_add(1))
    });
}
