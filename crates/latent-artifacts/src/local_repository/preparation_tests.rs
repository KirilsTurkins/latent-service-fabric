use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::mem::{size_of, size_of_val};

use latent_core::{BoxFuture, PlatformError, PublisherId};
use sha2::{Digest, Sha256};

use super::*;
use crate::{
    preparation_metadata_fingerprint, ArtifactPage, ArtifactPreparationIdentity,
    ArtifactPreparationSource, PreparationMetadataFingerprint,
};

fn fingerprint(value: &CapsuleArtifact) -> PreparationMetadataFingerprint {
    preparation_metadata_fingerprint(
        &value.descriptor,
        &value.manifest,
        &value.contracts,
        1024 * 1024,
        32,
    )
    .unwrap()
}

fn identity(
    repo: &DirectoryArtifactRepository,
    release: &ReleaseDigest,
) -> ArtifactPreparationIdentity {
    repo.preparation_source()
        .unwrap()
        .identity(release)
        .unwrap()
        .unwrap()
}

#[test]
fn fingerprint_preserves_the_existing_complete_debug_frame_and_exact_limits() {
    let value = artifact("fingerprint", b"abc");
    let actual = fingerprint(&value);
    let body = format!(
        "{:?}\n{:?}\n{:?}",
        value.descriptor, value.manifest, value.contracts
    );
    let mut expected = Sha256::new();
    expected.update(b"lsf-wasmtime-preparation-metadata-v1\0");
    expected.update(body.as_bytes());
    assert_eq!(*actual.digest(), <[u8; 32]>::from(expected.finalize()));
    assert!(actual.charged_bytes() >= body.len());
    assert_eq!(actual.required_type_depth(), 3);
    assert_eq!(
        preparation_metadata_fingerprint(
            &value.descriptor,
            &value.manifest,
            &value.contracts,
            actual.charged_bytes(),
            actual.required_type_depth()
        )
        .unwrap(),
        actual
    );
    for (bytes, depth) in [(actual.charged_bytes() - 1, 32), (1024 * 1024, 2)] {
        assert_eq!(
            preparation_metadata_fingerprint(
                &value.descriptor,
                &value.manifest,
                &value.contracts,
                bytes,
                depth
            )
            .unwrap_err()
            .code,
            PlatformErrorCode::ResourceExhausted
        );
    }
}

#[test]
fn every_preparation_metadata_family_participates_in_the_stamp() {
    let value = artifact("all-fields", b"abc");
    let expected = fingerprint(&value);
    for change in 0..9 {
        let mut altered = value.clone();
        match change {
            0 => altered.descriptor.reference.0.push_str("-other"),
            1 => altered.descriptor.publisher = Some(PublisherId("publisher".to_owned())),
            2 => altered.descriptor.layers.push(ArtifactLayer {
                media_type: "layer".to_owned(),
                digest: "digest".to_owned(),
                size_bytes: 1,
                annotations: Metadata::from([("key".to_owned(), "value".to_owned())]),
            }),
            3 => altered.manifest.imports[0].optional = !altered.manifest.imports[0].optional,
            4 => altered.manifest.execution.resource_budget_ceiling.cpu_fuel += 1,
            5 => altered.contracts[0]
                .dependencies
                .push(ContractId("other:dependency/api@1.0.0".to_owned())),
            6 => {
                altered.contracts[0].interfaces[0].documentation =
                    Some("different documentation".to_owned())
            }
            7 => {
                altered.contracts[0].interfaces[0].functions[0].parameters[0].value_type =
                    ValueType::U64
            }
            8 => {
                altered.contracts[0].interfaces[0].functions[0]
                    .attributes
                    .insert("other".to_owned(), "value".to_owned());
            }
            _ => unreachable!(),
        }
        assert_ne!(
            fingerprint(&altered).digest(),
            expected.digest(),
            "change {change}"
        );
    }
}

#[test]
fn warm_identity_reads_neither_disk_nor_metadata_and_fresh_fetch_rejects_corruption() {
    let temp = TempRoot::new();
    let value = artifact("warm", b"abc");
    let release = value.descriptor.release_digest.clone();
    let repo = repository(temp.path());
    block_on(repo.publish(value)).unwrap();
    let expected = identity(&repo, &release);
    let before = repo.verification_snapshot();
    fs::remove_file(release_dir(temp.path(), &release).join("component.wasm")).unwrap();
    for _ in 0..8 {
        assert_eq!(identity(&repo, &release), expected);
    }
    assert_eq!(repo.verification_snapshot(), before);
    assert_eq!(
        block_on(repo.preparation_source().unwrap().fetch(&release))
            .unwrap_err()
            .code,
        PlatformErrorCode::CorruptArtifact
    );
    let after = repo.verification_snapshot();
    assert_eq!(after.full_fetch_attempts, before.full_fetch_attempts + 1);
    assert_eq!(
        after.component_verification_attempts,
        before.component_verification_attempts + 1
    );
    assert_eq!(after.component_bytes_hashed, before.component_bytes_hashed);
    assert_eq!(
        after.metadata_fingerprint_attempts,
        before.metadata_fingerprint_attempts
    );
}

#[test]
fn repository_epochs_are_distinct_and_tokens_do_not_retain_root_ownership() {
    let first = TempRoot::new();
    let second = TempRoot::new();
    let value = artifact("epochs", b"abc");
    let release = value.descriptor.release_digest.clone();
    let a = repository(first.path());
    let b = repository(second.path());
    block_on(a.publish(value.clone())).unwrap();
    block_on(b.publish(value)).unwrap();
    let original = identity(&a, &release);
    let foreign = identity(&b, &release);
    assert_eq!(original.metadata(), foreign.metadata());
    assert_ne!(original, foreign);
    assert_ne!(original.cache_digest(), foreign.cache_digest());
    let mut left = DefaultHasher::new();
    let mut right = DefaultHasher::new();
    original.hash(&mut left);
    original.clone().hash(&mut right);
    assert_eq!(left.finish(), right.finish());
    drop(a);
    let reopened = repository(first.path());
    assert_ne!(identity(&reopened, &release), original);
    assert_eq!(
        identity(&reopened, &release).metadata(),
        original.metadata()
    );
}

#[test]
fn verified_stamp_rejects_same_component_with_changed_descriptor_or_contracts() {
    let temp = TempRoot::new();
    let value = artifact("binding", b"abc");
    let repo = repository(temp.path());
    block_on(repo.publish(value.clone())).unwrap();
    let proof = identity(&repo, &value.descriptor.release_digest);
    proof.verify_metadata(&value, 1024 * 1024, 32).unwrap();
    for contract in [false, true] {
        let mut altered = value.clone();
        if contract {
            altered.contracts[0].interfaces[0].functions[0]
                .name
                .push_str("-changed");
        } else {
            altered.descriptor.reference.0.push_str("-changed");
        }
        assert_eq!(
            proof
                .verify_metadata(&altered, 1024 * 1024, 32)
                .unwrap_err()
                .code,
            PlatformErrorCode::CorruptArtifact
        );
    }
    let mut upper = value.descriptor.release_digest;
    upper.0.make_ascii_uppercase();
    assert!(!proof.matches_release(&upper));
}

#[test]
fn normalized_stamp_accepts_equivalent_noncanonical_persisted_metadata() {
    use latent_manifest::__serde_json as json;
    let temp = TempRoot::new();
    let value = artifact("normalized", b"abc");
    let release = value.descriptor.release_digest.clone();
    let repo = repository(temp.path());
    block_on(repo.publish(value.clone())).unwrap();
    let original = identity(&repo, &release);
    let entry = release_dir(temp.path(), &release);
    let encoded = fs::read(entry.join("metadata.json")).unwrap();
    let mut metadata: json::Value = json::from_slice(&encoded).unwrap();
    // Missing optional publisher and different whitespace decode to the same
    // model but have different exact COMPLETE metadata hashes.
    metadata["descriptor"]
        .as_object_mut()
        .unwrap()
        .remove("publisher");
    let changed = json::to_vec_pretty(&metadata).unwrap();
    assert_ne!(changed, encoded);
    fs::write(entry.join("metadata.json"), &changed).unwrap();
    let completion = super::super::integrity::CompletionRecord::from_payloads(
        &value.descriptor,
        &changed,
        &fs::read(entry.join("manifest.json")).unwrap(),
    );
    fs::write(entry.join("COMPLETE"), completion.encode().unwrap()).unwrap();
    let fetched = block_on(repo.preparation_source().unwrap().fetch(&release)).unwrap();
    original.verify_metadata(&fetched, 1024 * 1024, 32).unwrap();
    drop(repo);
    let restored = repository(temp.path());
    assert_eq!(
        identity(&restored, &release).metadata(),
        original.metadata()
    );
}

struct Delegating<'a> {
    source: &'a DirectoryArtifactRepository,
    other: CapsuleArtifact,
    enabled: bool,
}

impl ArtifactRepository for Delegating<'_> {
    fn preparation_source(&self) -> Option<ArtifactPreparationSource<'_>> {
        self.enabled
            .then(|| self.source.preparation_source().unwrap())
    }
    fn fetch<'a>(
        &'a self,
        _: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async { Ok(self.other.clone()) })
    }
    fn resolve<'a>(
        &'a self,
        query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        self.source.resolve(query)
    }
    fn publish(
        &self,
        artifact: CapsuleArtifact,
    ) -> BoxFuture<'_, Result<ArtifactDescriptor, PlatformError>> {
        self.source.publish(artifact)
    }
    fn list<'a>(
        &'a self,
        after: Option<&'a ReleaseDigest>,
        limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        self.source.list(after, limit)
    }
}

#[test]
fn delegated_source_binds_its_fetch_even_when_outer_repository_fetch_disagrees() {
    for eligible in [false, true] {
        let temp = TempRoot::new();
        let original = artifact("authoritative", b"abc");
        let release = original.descriptor.release_digest.clone();
        let mut repo = repository(temp.path());
        if !eligible {
            repo.stamp_byte_limit = 1;
        }
        block_on(repo.publish(original.clone())).unwrap();
        let wrapper = Delegating {
            source: &repo,
            other: artifact("unrelated", b"abc"),
            enabled: true,
        };
        assert_ne!(block_on(wrapper.fetch(&release)).unwrap(), original);
        let capability = wrapper.preparation_source().unwrap();
        assert_eq!(capability.identity(&release).unwrap().is_some(), eligible);
        assert_eq!(block_on(capability.fetch(&release)).unwrap(), original);
        if let Some(token) = capability.identity(&release).unwrap() {
            assert!(token
                .verify_metadata(&wrapper.other, 1024 * 1024, 32)
                .is_err());
        }
        let fallback = Delegating {
            enabled: false,
            ..wrapper
        };
        assert!(fallback.preparation_source().is_none());
        assert_eq!(block_on(fallback.fetch(&release)).unwrap(), fallback.other);
    }
}

#[test]
fn pending_publication_never_issues_an_identity_before_durable_adoption() {
    let temp = TempRoot::new();
    let value = artifact("pending", b"abc");
    let release = value.descriptor.release_digest.clone();
    let repo = repository(temp.path());
    repo.inject_parent_sync_failure_once();
    assert_eq!(
        block_on(repo.publish(value.clone())).unwrap_err().code,
        PlatformErrorCode::Internal
    );
    assert_eq!(
        repo.preparation_source()
            .unwrap()
            .identity(&release)
            .unwrap_err()
            .code,
        PlatformErrorCode::NotFound
    );
    block_on(repo.publish(value)).unwrap();
    assert!(repo
        .preparation_source()
        .unwrap()
        .identity(&release)
        .unwrap()
        .is_some());
}

#[test]
fn optional_stamp_bound_does_not_reject_valid_publication_or_full_fetch() {
    let temp = TempRoot::new();
    let value = artifact("ineligible", b"abc");
    let release = value.descriptor.release_digest.clone();
    let mut repo = repository(temp.path());
    repo.stamp_byte_limit = 1;
    block_on(repo.publish(value.clone())).unwrap();
    assert!(repo
        .preparation_source()
        .unwrap()
        .identity(&release)
        .unwrap()
        .is_none());
    assert_eq!(block_on(repo.fetch(&release)).unwrap(), value);
    repo.rebuild_index().unwrap();
    assert!(repo
        .preparation_source()
        .unwrap()
        .identity(&release)
        .unwrap()
        .is_none());
}

#[test]
fn preparation_storage_charge_is_fixed_and_precedes_adoption() {
    let temp = TempRoot::new();
    let value = artifact("charged", b"abc");
    let release = value.descriptor.release_digest.clone();
    let mut larger = value.clone();
    larger.contracts[0].interfaces[0].documentation = Some("extra contract information".repeat(8));
    let defaults = DirectoryArtifactRepositoryConfig::default();
    let entry_cost = super::super::index::entry_cost(&value, defaults);
    assert_eq!(
        entry_cost,
        super::super::index::entry_cost(&larger, defaults)
    );
    let baseline = super::super::index::REPOSITORY_ACCOUNTED_BYTES;
    let repo = DirectoryArtifactRepository::open(
        temp.path(),
        DirectoryArtifactRepositoryConfig {
            max_index_bytes: baseline + entry_cost,
            ..defaults
        },
    )
    .unwrap();
    assert_eq!(repo.index.read().unwrap().accounted_bytes, baseline);
    block_on(repo.publish(larger)).unwrap();
    assert_eq!(
        repo.index.read().unwrap().accounted_bytes,
        baseline + entry_cost
    );
    let proof = identity(&repo, &release);
    assert_eq!(
        size_of::<PreparationMetadataFingerprint>(),
        size_of_val(proof.metadata())
    );
    assert_eq!(
        size_of::<PreparationMetadataFingerprint>(),
        32 + 2 * size_of::<usize>()
    );
    assert!(proof.retained_bytes() >= size_of::<ArtifactPreparationIdentity>());
    assert_eq!(
        block_on(repo.publish(artifact("too-many", b"other")))
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
}
