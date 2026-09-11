use latent_core::{ServiceId, TenantId};

use super::*;
use crate::local_repository::{index, paging::instrumentation};
use crate::ArtifactCatalogPageRequest;

fn scoped(name: &str, tenant: Option<&str>, service: &str) -> CapsuleArtifact {
    let mut value = artifact(name, name.as_bytes());
    value.manifest.metadata.tenant = tenant.map(|value| TenantId(value.to_owned()));
    value.manifest.metadata.name = service.to_owned();
    if let Some(tenant) = tenant {
        value.manifest.world.0 = value
            .manifest
            .world
            .0
            .replace("examples:", &format!("{tenant}:"));
        for export in &mut value.manifest.exports {
            export.contract.0 = export
                .contract
                .0
                .replace("examples:", &format!("{tenant}:"));
        }
    }
    Phase1ManifestValidator::new()
        .validate_capsule(&value.manifest)
        .expect("scoped fixture must preserve capsule namespace rules");
    value
}

fn query(tenant: &str, service: Option<&str>, page_size: u32) -> ArtifactCatalogPageRequest {
    ArtifactCatalogPageRequest {
        tenant: TenantId(tenant.to_owned()),
        service: service.map(|s| ServiceId(s.to_owned())),
        page_size,
        page_token: None,
    }
}

#[test]
fn scoped_pages_select_only_matching_rows_and_hide_neutral_releases() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let values = [
        scoped("a1", Some("tenant-a"), "echo"),
        scoped("a2", Some("tenant-a"), "echo"),
        scoped("a3", Some("tenant-a"), "other"),
        scoped("b1", Some("tenant-b"), "echo"),
        scoped("b2", Some("tenant-b"), "echo"),
        scoped("neutral", None, "echo"),
    ];
    for value in &values {
        block_on(repo.publish(value.clone())).expect("publish");
    }
    let mut request = query("tenant-a", Some("echo"), 1);
    instrumentation::reset();
    let first = block_on(repo.list_catalog_entries(&request)).expect("first page");
    assert_eq!(instrumentation::counts(), (2, 1));
    assert_eq!(first.catalog_generation, 6);
    request.page_token = first.next_page_token;
    let second = block_on(repo.list_catalog_entries(&request)).expect("second page");
    assert!(second.next_page_token.is_none());
    let mut expected = values[..2]
        .iter()
        .map(|value| value.descriptor.release_digest.clone())
        .collect::<Vec<_>>();
    expected.sort();
    assert_eq!(
        [
            first.entries[0].descriptor.release_digest.clone(),
            second.entries[0].descriptor.release_digest.clone()
        ],
        expected.as_slice()
    );
    let tenant = TenantId("tenant-a".to_owned());
    for value in &values[3..] {
        assert!(
            block_on(repo.get_catalog_entry(&tenant, &value.descriptor.release_digest))
                .expect("scoped get")
                .is_none()
        );
    }
    assert_eq!(
        block_on(repo.list_catalog_entries(&query("tenant-a", None, 10)))
            .expect("tenant page")
            .entries
            .len(),
        3
    );
    assert_eq!(
        block_on(repo.list(None, 10))
            .expect("trusted global page")
            .entries
            .len(),
        6
    );
}

#[test]
fn summary_reads_do_not_touch_component_or_metadata_files() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let value = scoped("no-fetch", Some("tenant-a"), "echo");
    block_on(repo.publish(value.clone())).expect("publish");
    let directory = release_dir(temp.path(), &value.descriptor.release_digest);
    let held = temp.path().join("temporarily-unavailable");
    fs::rename(&directory, &held).expect("temporarily make all artifact files unavailable");
    let entry = block_on(repo.get_catalog_entry(
        &TenantId("tenant-a".to_owned()),
        &value.descriptor.release_digest,
    ))
    .expect("indexed get")
    .expect("summary");
    assert_eq!(entry.service.0, value.manifest.metadata.name);
    assert_eq!(entry.semantic_version, value.manifest.semantic_version);
    assert_eq!(entry.world, value.manifest.world);
    assert_eq!(
        block_on(repo.list_catalog_entries(&query("tenant-a", None, 1)))
            .expect("indexed page")
            .entries,
        vec![entry]
    );
    assert!(block_on(repo.fetch(&value.descriptor.release_digest)).is_err());
    fs::rename(held, directory).expect("restore files");
}

#[test]
fn scoped_tokens_bind_query_generation_and_open_epoch_without_scope_length_growth() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let tenant = "a".repeat(128);
    let first = scoped("token-one", Some(&tenant), "echo");
    block_on(repo.publish(first.clone())).expect("first");
    block_on(repo.publish(scoped("token-two", Some(&tenant), "echo"))).expect("second");
    let request = query(&tenant, None, 1);
    let token = block_on(repo.list_catalog_entries(&request))
        .expect("page")
        .next_page_token
        .expect("continuation");
    assert_eq!(token.len(), 101);
    let mut next = request.clone();
    next.page_token = Some(token.clone());
    block_on(repo.publish(first)).expect("idempotent retry");
    block_on(repo.list_catalog_entries(&next)).expect("retry keeps generation");
    let mut other = next.clone();
    other.tenant = TenantId("different".to_owned());
    instrumentation::reset();
    assert_eq!(
        block_on(repo.list_catalog_entries(&other))
            .expect_err("foreign token")
            .message,
        "invalid-artifact-page-token"
    );
    other = next.clone();
    other.service = Some(ServiceId("echo".to_owned()));
    assert_eq!(
        block_on(repo.list_catalog_entries(&other))
            .expect_err("service scope")
            .code,
        PlatformErrorCode::InvalidArgument
    );
    other = next.clone();
    other
        .page_token
        .as_mut()
        .expect("token")
        .replace_range(100..101, "z");
    assert_eq!(
        block_on(repo.list_catalog_entries(&other))
            .expect_err("tamper")
            .code,
        PlatformErrorCode::InvalidArgument
    );
    assert_eq!(instrumentation::counts(), (0, 0));
    block_on(repo.publish(scoped("token-three", Some("other-tenant"), "echo")))
        .expect("new visibility generation");
    assert_eq!(
        block_on(repo.list_catalog_entries(&next))
            .expect_err("expired")
            .message,
        "expired-artifact-page-token"
    );
    drop(repo);
    let reopened = repository(temp.path());
    assert_eq!(
        block_on(reopened.list_catalog_entries(&next))
            .expect_err("old open epoch")
            .message,
        "invalid-artifact-page-token"
    );
}

#[test]
fn pending_publication_is_invisible_to_all_scope_indexes_until_durable_retry() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let value = scoped("pending-scope", Some("tenant-a"), "echo");
    let tenant = TenantId("tenant-a".to_owned());
    repo.inject_parent_sync_failure_once();
    assert!(block_on(repo.publish(value.clone())).is_err());
    assert!(
        block_on(repo.get_catalog_entry(&tenant, &value.descriptor.release_digest))
            .expect("get")
            .is_none()
    );
    for service in [None, Some("echo")] {
        let page = block_on(repo.list_catalog_entries(&query("tenant-a", service, 10)))
            .expect("pending not indexed");
        assert!(page.entries.is_empty());
        assert_eq!(page.catalog_generation, 0);
    }
    block_on(repo.publish(value.clone())).expect("durable retry");
    let page =
        block_on(repo.list_catalog_entries(&query("tenant-a", Some("echo"), 10))).expect("adopted");
    assert_eq!(page.entries.len(), 1);
    assert_eq!(page.catalog_generation, 1);
    drop(repo);
    let reopened = repository(temp.path());
    assert_eq!(
        block_on(reopened.list_catalog_entries(&query("tenant-a", Some("echo"), 10)))
            .expect("rebuilt"),
        page
    );
}

#[test]
fn first_summary_too_large_fails_without_clones_or_empty_continuation_loop() {
    let temp = TempRoot::new();
    let config = DirectoryArtifactRepositoryConfig {
        max_descriptor_bytes: 512,
        max_page_bytes: 512,
        ..DirectoryArtifactRepositoryConfig::default()
    };
    let repo = DirectoryArtifactRepository::open(temp.path(), config).expect("open");
    block_on(repo.publish(scoped("large-summary", Some("tenant-a"), "echo")))
        .expect("publish independent of page size");
    instrumentation::reset();
    assert_eq!(
        block_on(repo.list_catalog_entries(&query("tenant-a", None, 1)))
            .expect_err("first row")
            .message,
        "artifact-page-byte-limit"
    );
    assert_eq!(instrumentation::counts(), (1, 0));
    for size in [0, 1001] {
        assert_eq!(
            block_on(repo.list_catalog_entries(&query("tenant-a", None, size)))
                .expect_err("page size")
                .message,
            "invalid-artifact-page-size"
        );
    }
}

#[test]
fn global_digest_cannot_acquire_a_second_tenant_summary() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let value = scoped("one-owner", Some("tenant-a"), "echo");
    block_on(repo.publish(value.clone())).expect("publish");
    let foreign = scoped("one-owner", Some("tenant-b"), "echo");
    assert_eq!(
        block_on(repo.publish(foreign))
            .expect_err("global identity conflict")
            .code,
        PlatformErrorCode::AlreadyExists
    );
    assert!(block_on(repo.get_catalog_entry(
        &TenantId("tenant-b".to_owned()),
        &value.descriptor.release_digest
    ))
    .expect("foreign scope")
    .is_none());
    assert_eq!(
        block_on(repo.list_catalog_entries(&query("tenant-a", None, 10)))
            .expect("owner")
            .catalog_generation,
        1
    );
}

#[test]
fn eight_index_adoptions_precharge_capacity_and_preserve_every_scope_path() {
    let temp = TempRoot::new();
    let template = scoped("small-index", Some("tenant-a"), "echo");
    let cost = index::entry_cost(&template, DirectoryArtifactRepositoryConfig::default());
    let config = DirectoryArtifactRepositoryConfig {
        max_index_entries: 8,
        max_index_bytes: cost * 8 + index::REPOSITORY_ACCOUNTED_BYTES,
        ..DirectoryArtifactRepositoryConfig::default()
    };
    let repo = DirectoryArtifactRepository::open(temp.path(), config).expect("open");
    for n in 0_u32..8 {
        let mut value = template.clone();
        value.descriptor.reference = ArtifactReference(format!("local://tests/index-{n}"));
        value.descriptor.release_digest = ReleaseDigest(format!("sha256:{n:064x}"));
        repo.preflight_adoption(&value).expect("preflight");
        repo.finalize_adoption(value, None).expect("adopt");
    }
    assert_eq!(
        block_on(repo.list_catalog_entries(&query("tenant-a", Some("echo"), 10)))
            .expect("scoped index")
            .entries
            .len(),
        8
    );
    let mut rejected = template;
    rejected.descriptor.release_digest = ReleaseDigest(format!("sha256:{:064x}", 9));
    assert_eq!(
        repo.preflight_adoption(&rejected).expect_err("bound").code,
        PlatformErrorCode::ResourceExhausted
    );
    let index = repo.index.read().expect("index");
    assert_eq!(index.by_digest.len(), 8);
    assert!(index.accounted_bytes <= config.max_index_bytes);
}

#[test]
fn descriptor_sizing_matches_storage_json_without_materializing_it() {
    let mut value = artifact("descriptor-size", b"descriptor-size");
    value
        .descriptor
        .annotations
        .insert("quoted\"key".to_owned(), "line\n\t\u{0}ü".to_owned());
    let encoded = latent_manifest::__serde_json::to_vec(
        &super::super::metadata::StoredArtifactDescriptor::from(&value.descriptor),
    )
    .expect("storage encoding");
    assert_eq!(
        index::descriptor_bytes(&value.descriptor, encoded.len()).expect("exact count"),
        encoded.len()
    );
    assert!(index::descriptor_bytes(&value.descriptor, encoded.len() - 1).is_err());
}
