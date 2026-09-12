use tonic::Code;

use super::{package, proto, validation};
use crate::management::ManagementLimits;

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
