use latent_artifacts::{ArtifactCatalogEntry, ArtifactDescriptor, ArtifactLayer};
use latent_core::{
    ArtifactReference, ContractId, Metadata, PublisherId, ReleaseDigest, ServiceId, TenantId,
};
use tonic::Code;

use super::{
    proto, release_descriptor_from_proto, release_descriptor_to_proto, validation, RequestBudget,
};
use crate::management::ManagementLimits;

fn entry() -> ArtifactCatalogEntry {
    ArtifactCatalogEntry {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local:release:opaque".to_owned()),
            release_digest: ReleaseDigest(format!("sha256:{}", "a".repeat(64))),
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: u64::MAX,
            publisher: Some(PublisherId("publisher-a".to_owned())),
            layers: Vec::new(),
            annotations: Metadata::from([
                ("owner".to_owned(), "tenant-a".to_owned()),
                ("notes".to_owned(), "line one\nline two".to_owned()),
            ]),
        },
        tenant: Some(TenantId("tenant-a".to_owned())),
        service: ServiceId("tenant-a/echo".to_owned()),
        semantic_version: "1.2.3-beta.4+build.5".to_owned(),
        world: ContractId("tenant-a:echo/service@1.2.3".to_owned()),
    }
}

#[test]
fn all_representable_release_summary_fields_round_trip_without_invented_state() {
    let original = entry();
    let wire = release_descriptor_to_proto(original.clone()).expect("representable summary");
    assert_eq!(wire.digest, original.descriptor.release_digest.0);
    assert_eq!(wire.artifact_reference, original.descriptor.reference.0);
    assert_eq!(wire.service, original.service.0);
    assert_eq!(wire.semantic_version, original.semantic_version);
    assert_eq!(wire.world, original.world.0);
    assert_eq!(wire.publisher, "publisher-a");
    assert_eq!(wire.media_type, original.descriptor.media_type);
    assert_eq!(wire.size_bytes, u64::MAX);
    assert_eq!(wire.created_at_unix_millis, 0);
    assert!(wire.admitted);
    assert_eq!(wire.tenant.as_deref(), Some("tenant-a"));
    assert_eq!(
        wire.annotations.get("notes").map(String::as_str),
        Some("line one\nline two")
    );
    assert_eq!(
        release_descriptor_from_proto(wire).expect("decode"),
        original
    );
    for tenant in [None, Some(TenantId(String::new()))] {
        let mut neutral = entry();
        neutral.tenant = tenant;
        neutral.descriptor.publisher = None;
        let wire = release_descriptor_to_proto(neutral.clone()).expect("trusted optional scope");
        assert_eq!(
            release_descriptor_from_proto(wire).expect("optional scope survives"),
            neutral
        );
    }
}

#[test]
fn present_empty_publisher_and_unrepresentable_receipt_fields_are_rejected() {
    let mut value = entry();
    value.descriptor.publisher = Some(PublisherId(String::new()));
    assert_eq!(
        release_descriptor_to_proto(value)
            .expect_err("publisher presence would be lost")
            .field,
        "release.publisher"
    );
    let mut value = entry();
    value.descriptor.layers.push(ArtifactLayer {
        media_type: "layer".to_owned(),
        digest: "digest".to_owned(),
        size_bytes: 1,
        annotations: Metadata::new(),
    });
    assert_eq!(
        release_descriptor_to_proto(value)
            .expect_err("wire lacks layers")
            .field,
        "release.layers"
    );
    let mut wire = release_descriptor_to_proto(entry()).expect("fixture");
    wire.created_at_unix_millis = 1;
    assert!(release_descriptor_from_proto(wire).is_err());
    let mut wire = release_descriptor_to_proto(entry()).expect("fixture");
    wire.admitted = false;
    assert!(release_descriptor_from_proto(wire).is_err());
}

#[test]
fn matching_repository_tenant_cannot_hide_oversized_retained_capacity() {
    let limits = ManagementLimits::default();
    let tenant = TenantId("tenant-a".to_owned());
    let mut value = entry();
    let mut padded = String::with_capacity(limits.max_id_bytes + 1);
    padded.push_str(&tenant.0);
    value.tenant = Some(TenantId(padded));
    let mut budget =
        RequestBudget::for_response::<proto::GetReleaseResponse>(&limits).expect("response budget");
    assert_eq!(
        validation::entry(&value, &tenant, &mut budget, &limits)
            .expect_err("charge actual repository tenant")
            .code(),
        Code::ResourceExhausted
    );
    value.tenant = Some(tenant.clone());
    let mut budget =
        RequestBudget::for_response::<proto::GetReleaseResponse>(&limits).expect("response budget");
    validation::entry(&value, &tenant, &mut budget, &limits).expect("compact matching tenant");
}

#[test]
fn returned_publication_descriptor_is_bounded_before_receipt_comparison() {
    let limits = ManagementLimits::default();
    let mut descriptor = entry().descriptor;
    let mut padded = String::with_capacity(limits.max_string_bytes + 1);
    padded.push_str(&descriptor.reference.0);
    descriptor.reference.0 = padded;
    let mut budget =
        RequestBudget::for_response::<ArtifactDescriptor>(&limits).expect("receipt budget");
    assert_eq!(
        validation::descriptor(&descriptor, &mut budget, &limits)
            .expect_err("source capacity bound")
            .code(),
        Code::ResourceExhausted
    );
    descriptor.reference.0 = descriptor.reference.0.into_boxed_str().into_string();
    let mut budget =
        RequestBudget::for_response::<ArtifactDescriptor>(&limits).expect("receipt budget");
    validation::descriptor(&descriptor, &mut budget, &limits).expect("bounded receipt");
}
