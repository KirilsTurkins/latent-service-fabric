use prost::Message;
use tonic::Code;

use super::{package, proto, validation};
use crate::management::{ManagementLimits, RequestBudget};

fn upload() -> proto::PublishReleaseRequest {
    proto::PublishReleaseRequest {
        package: Some(proto::PackageAdmissionUpload {
            manifest: b"{}".to_vec(),
            configuration: b"{}".to_vec(),
            layers: vec![proto::PackageAdmissionLayer {
                path: "component.wasm".to_owned(),
                data: vec![0],
            }],
            signatures: vec![proto::PackageAdmissionEvidence {
                manifest: b"{}".to_vec(),
                configuration: b"{}".to_vec(),
                payload: vec![1],
            }],
            ..proto::PackageAdmissionUpload::default()
        }),
        ..proto::PublishReleaseRequest::default()
    }
}

#[test]
fn package_transport_rejects_ambiguous_inputs_and_every_descriptor_claim() {
    let limits = ManagementLimits::default();
    validation::publish(&upload(), &limits).unwrap();
    let mut value = upload();
    value.artifact = Some(proto::CapsuleArtifactUpload::default());
    assert_eq!(
        validation::publish(&value, &limits).unwrap_err().code(),
        Code::InvalidArgument
    );
    value.artifact = None;
    value.release = Some(proto::ReleaseDescriptor::default());
    assert_eq!(
        validation::publish(&value, &limits).unwrap_err().code(),
        Code::InvalidArgument
    );
    assert_eq!(
        validation::publish(&proto::PublishReleaseRequest::default(), &limits)
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
}

#[test]
fn package_transport_bounds_capacity_slots_and_evidence_before_conversion() {
    let limits = ManagementLimits::default();
    let mut value = upload();
    value.package.as_mut().unwrap().layers[0].path = String::with_capacity(241);
    assert_eq!(
        validation::publish(&value, &limits).unwrap_err().code(),
        Code::ResourceExhausted
    );
    let mut value = upload();
    value
        .package
        .as_mut()
        .unwrap()
        .signatures
        .resize(9, proto::PackageAdmissionEvidence::default());
    assert_eq!(
        validation::publish(&value, &limits).unwrap_err().code(),
        Code::ResourceExhausted
    );
    let mut value = upload();
    value.package.as_mut().unwrap().signatures[0].payload = Vec::with_capacity(4097);
    assert_eq!(
        validation::publish(&value, &limits).unwrap_err().code(),
        Code::ResourceExhausted
    );
    let mut limits = limits;
    limits.max_request_bytes = 512;
    assert_eq!(
        validation::publish(&upload(), &limits).unwrap_err().code(),
        Code::ResourceExhausted
    );
}

#[test]
fn package_conversion_preserves_exact_input_bytes_and_associations() {
    let value = upload().package.unwrap();
    let expected = value.clone();
    let actual = package::into_upload(value).unwrap();
    assert_eq!(actual.manifest, expected.manifest);
    assert_eq!(actual.configuration, expected.configuration);
    assert_eq!(
        actual.layers,
        vec![(
            expected.layers[0].path.clone(),
            expected.layers[0].data.clone()
        )]
    );
    assert_eq!(
        actual.signatures[0].manifest,
        expected.signatures[0].manifest
    );
    assert_eq!(
        actual.signatures[0].configuration,
        expected.signatures[0].configuration
    );
    assert_eq!(actual.signatures[0].payload, expected.signatures[0].payload);
    assert!(actual.provenance.is_empty() && actual.sboms.is_empty());
}

#[test]
fn protobuf_decoded_publication_accepts_bounded_empty_evidence_configuration() {
    let decoded =
        proto::PublishReleaseRequest::decode(upload().encode_to_vec().as_slice()).unwrap();
    let configuration = &decoded.package.as_ref().unwrap().signatures[0].configuration;
    assert_eq!(configuration, b"{}");
    assert!(configuration.capacity() > configuration.len());
    assert!(configuration.capacity() <= 8);
    validation::publish(&decoded, &ManagementLimits::default()).unwrap();
    let domain = package::into_upload(decoded.package.unwrap()).unwrap();
    assert_eq!(domain.signatures[0].configuration, b"{}");
}

fn renewal() -> proto::RenewReleaseEvidenceRequest {
    let entry = upload().package.unwrap().signatures.remove(0);
    proto::RenewReleaseEvidenceRequest {
        digest: format!("sha256:{}", "a".repeat(64)),
        package_digest: format!("sha256:{}", "b".repeat(64)),
        evidence: Some(proto::ReleaseEvidenceUpload {
            signatures: vec![entry.clone()],
            provenance: vec![entry],
            sboms: Vec::new(),
        }),
        operation: Some(proto::ReleaseOperationPrecondition {
            operation_id: "renew-1".to_owned(),
            expected_generation: Some(1),
        }),
    }
}

fn validate_renewal(value: &proto::RenewReleaseEvidenceRequest) -> Result<(), tonic::Status> {
    let limits = ManagementLimits::default();
    let mut budget = RequestBudget::new::<proto::RenewReleaseEvidenceRequest>(&limits)?;
    let evidence = value.evidence.as_ref().unwrap();
    package::validate_evidence(
        &evidence.signatures,
        &evidence.provenance,
        &evidence.sboms,
        &mut budget,
        &limits,
        true,
    )
}

#[test]
fn protobuf_decoded_renewal_charges_spare_evidence_slots_without_rejecting_one_entry() {
    let decoded =
        proto::RenewReleaseEvidenceRequest::decode(renewal().encode_to_vec().as_slice()).unwrap();
    let evidence = decoded.evidence.as_ref().unwrap();
    for entries in [&evidence.signatures, &evidence.provenance] {
        assert_eq!(entries.len(), 1);
        assert!(entries.capacity() > entries.len());
        assert_eq!(entries[0].configuration, b"{}");
        assert!(entries[0].configuration.capacity() > 2);
    }
    validate_renewal(&decoded).unwrap();
}

#[test]
fn evidence_configuration_keeps_content_capacity_and_exact_renewal_bounds() {
    let limits = ManagementLimits::default();
    for configuration in [b"{} ".to_vec(), {
        let mut value = Vec::with_capacity(9);
        value.extend_from_slice(b"{}");
        value
    }] {
        let mut publication = upload();
        publication.package.as_mut().unwrap().signatures[0].configuration = configuration;
        assert_eq!(
            validation::publish(&publication, &limits)
                .unwrap_err()
                .code(),
            Code::ResourceExhausted
        );
        let mut renewal = renewal();
        renewal.evidence.as_mut().unwrap().signatures[0].configuration = publication
            .package
            .unwrap()
            .signatures
            .remove(0)
            .configuration;
        assert_eq!(
            validate_renewal(&renewal).unwrap_err().code(),
            Code::ResourceExhausted
        );
    }
    let mut value = renewal();
    value.evidence.as_mut().unwrap().signatures[0].configuration = b"[]".to_vec();
    assert_eq!(
        validate_renewal(&value).unwrap_err().code(),
        Code::InvalidArgument
    );
}
