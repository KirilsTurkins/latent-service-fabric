use std::sync::atomic::{AtomicU8, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use latent_artifacts::{
    ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
};
use latent_core::{
    BoxFuture, ContractId, Metadata, PlatformError, PlatformErrorCode, ReleaseDigest, RevisionId,
    RouteGeneration,
};
use latent_routing::{
    ActivationCatalog, ActivationCatalogSource, InvocationTarget, ResolvedBinding,
    ResolvedRevision, RevisionAdmissionPolicy, RevisionPolicySource, RouteResolver,
};

use super::model;
use super::support::{error, Gate, LiveGuard};

pub struct CatalogSource {
    pub generation: AtomicU8,
    pub global_policy_reads: AtomicUsize,
    pub keys: Arc<Mutex<Vec<String>>>,
}

impl Default for CatalogSource {
    fn default() -> Self {
        Self {
            generation: AtomicU8::new(1),
            global_policy_reads: AtomicUsize::new(0),
            keys: Arc::default(),
        }
    }
}

impl ActivationCatalogSource for CatalogSource {
    fn pin(&self) -> Result<Arc<dyn ActivationCatalog>, PlatformError> {
        Ok(Arc::new(Catalog {
            generation: self.generation.load(Ordering::Acquire),
            keys: Arc::clone(&self.keys),
        }))
    }
}

impl RevisionPolicySource for CatalogSource {
    fn admission_policy(
        &self,
        _revision: &ResolvedRevision,
    ) -> Result<RevisionAdmissionPolicy, PlatformError> {
        self.global_policy_reads.fetch_add(1, Ordering::Relaxed);
        Err(error(
            PlatformErrorCode::RouteUnavailable,
            "manager must use pinned policy",
        ))
    }
}

struct Catalog {
    generation: u8,
    keys: Arc<Mutex<Vec<String>>>,
}

impl RouteResolver for Catalog {
    fn resolve(
        &self,
        target: &InvocationTarget,
        routing_key: Option<&str>,
    ) -> Result<ResolvedRevision, PlatformError> {
        if target.service.0 != "echo" {
            return Err(error(
                PlatformErrorCode::RouteUnavailable,
                "fixture route absent",
            ));
        }
        let key = routing_key.expect("manager supplies a bounded routing key");
        self.keys.lock().expect("keys").push(key.to_owned());
        // Deterministic two-bucket test resolver. Real weighted hashing already
        // has repository tests; this proves the manager supplies varying keys.
        let bucket = key.bytes().fold(0_u8, u8::wrapping_add) % 2;
        Ok(ResolvedRevision {
            target: target.clone(),
            revision: RevisionId(format!("revision-{}-{bucket}", self.generation)),
            release: model::artifact(self.generation, bucket)
                .descriptor
                .release_digest,
            route_generation: RouteGeneration(u64::from(self.generation)),
            attributes: Metadata::new(),
        })
    }

    fn resolve_binding(
        &self,
        _consumer: &ResolvedRevision,
        _contract: &ContractId,
        _key: Option<&str>,
    ) -> Result<ResolvedBinding, PlatformError> {
        Err(error(
            PlatformErrorCode::IncompatibleContract,
            "no child calls in fixture",
        ))
    }

    fn generation(&self) -> RouteGeneration {
        RouteGeneration(u64::from(self.generation))
    }
}

impl RevisionPolicySource for Catalog {
    fn admission_policy(
        &self,
        revision: &ResolvedRevision,
    ) -> Result<RevisionAdmissionPolicy, PlatformError> {
        if revision.route_generation != self.generation() {
            return Err(error(
                PlatformErrorCode::StateConflict,
                "mixed catalog generation",
            ));
        }
        Ok(model::policy())
    }
}

pub struct Artifacts {
    pub gate: Gate,
    pub entered: AtomicUsize,
    pub live: Arc<AtomicUsize>,
    pub fail: AtomicU8,
}

impl Default for Artifacts {
    fn default() -> Self {
        Self {
            gate: Gate::new(true),
            entered: AtomicUsize::new(0),
            live: Arc::default(),
            fail: AtomicU8::new(0),
        }
    }
}

impl ArtifactRepository for Artifacts {
    fn resolve<'a>(
        &'a self,
        _query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        Box::pin(async { Ok(None) })
    }

    fn fetch<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async move {
            let _live = LiveGuard::new(&self.live);
            self.entered.fetch_add(1, Ordering::Relaxed);
            self.gate.wait().await;
            match self.fail.load(Ordering::Acquire) {
                1 => {
                    return Err(error(
                        PlatformErrorCode::Unavailable,
                        "fixture artifact unavailable",
                    ))
                }
                2 => panic!("controlled artifact panic"),
                _ => {}
            }
            for generation in [1, 2] {
                for bucket in [0, 1] {
                    let artifact = model::artifact(generation, bucket);
                    if artifact.descriptor.release_digest == *digest {
                        return Ok(artifact);
                    }
                }
            }
            Err(error(
                PlatformErrorCode::NotFound,
                "unknown fixture release",
            ))
        })
    }

    fn publish(
        &self,
        _artifact: CapsuleArtifact,
    ) -> BoxFuture<'_, Result<ArtifactDescriptor, PlatformError>> {
        Box::pin(async { Err(error(PlatformErrorCode::Internal, "unexpected publish")) })
    }

    fn list<'a>(
        &'a self,
        _after: Option<&'a ReleaseDigest>,
        _limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        Box::pin(async {
            Ok(ArtifactPage {
                entries: Vec::new(),
                next_after: None,
            })
        })
    }
}
