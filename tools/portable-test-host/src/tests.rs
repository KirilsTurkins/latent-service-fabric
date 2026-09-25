use latent_artifacts::{ArtifactDescriptor, CapsuleArtifact, DevelopmentTestArtifact};
use latent_core::{ArtifactReference, Metadata, TenantId};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidator, Phase1ManifestValidator,
};

fn artifact() -> CapsuleArtifact {
    let component_bytes = b"\0asm\x0d\0\x01\0".to_vec();
    let digest = latent_artifacts::content_digest(&component_bytes);
    let mut manifest = JsonManifestCodec::default()
        .decode_capsule(include_bytes!(
            "../../../examples/echo-contract/capsule.json"
        ))
        .unwrap();
    manifest.component_digest = digest.clone();
    manifest.metadata.tenant = None;
    manifest.metadata.name = "test".into();
    Phase1ManifestValidator.validate_capsule(&manifest).unwrap();
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://controlled-test".into()),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".into(),
            size_bytes: component_bytes.len() as u64,
            publisher: None,
            layers: vec![],
            annotations: Metadata::new(),
        },
        manifest,
        contracts: vec![],
        component_bytes,
    }
}

#[test]
fn test_owner_seals_are_distinct_and_retire_on_drop() {
    let first = DevelopmentTestArtifact::new(artifact(), TenantId("tests".into())).unwrap();
    let second = DevelopmentTestArtifact::new(artifact(), TenantId("tests".into())).unwrap();
    let proof = first.eligibility().clone();
    proof.check_for_catalog(&first.authority()).unwrap();
    assert!(proof.check_for_catalog(&second.authority()).is_err());
    assert!(proof.admission().is_none());
    assert!(proof.authorize_tenant(&TenantId("other".into())).is_err());
    drop(first);
    assert!(proof.check_current().is_err());
    second.eligibility().check_current().unwrap();
}

#[test]
fn test_owner_rejects_mismatched_bytes_and_tenant() {
    let mut changed = artifact();
    changed.component_bytes.push(0);
    assert!(DevelopmentTestArtifact::new(changed, TenantId("tests".into())).is_err());
    let mut changed = artifact();
    changed.manifest.metadata.tenant = Some(TenantId("other".into()));
    assert!(DevelopmentTestArtifact::new(changed, TenantId("tests".into())).is_err());
}

#[test]
fn guest_clock_fixture_is_explicit_full_width_and_rejects_ambiguous_values() {
    use crate::request::ClockFixture;
    let fixture = ClockFixture {
        monotonic_nanos: u64::MAX.to_string(),
        wall_unix_millis: "0".into(),
    };
    let readings = fixture.readings().unwrap();
    assert_eq!(readings.monotonic_nanos, u64::MAX);
    assert_eq!(readings.wall_unix_millis, 0);
    for value in ["", "-1", "+1", "01", "1.0", "18446744073709551616"] {
        assert!(ClockFixture {
            monotonic_nanos: value.into(),
            wall_unix_millis: "0".into(),
        }
        .readings()
        .is_err());
    }
    assert!(
        serde_json::from_str::<ClockFixture>(r#"{"monotonicNanos":0,"wallUnixMillis":"0"}"#)
            .is_err()
    );
    assert!(serde_json::from_str::<ClockFixture>(
        r#"{"monotonicNanos":"0","wallUnixMillis":"0","controlClock":true}"#
    )
    .is_err());
}

#[test]
fn guest_clock_fixture_cannot_select_an_external_capsule_profile() {
    use latent_wasmtime::{DevelopmentClockReadings, ExecutionIsolationProfile, WasmtimeConfig};
    let mut config = WasmtimeConfig {
        development_clock_readings: Some(DevelopmentClockReadings {
            monotonic_nanos: 0,
            wall_unix_millis: u64::MAX,
        }),
        ..WasmtimeConfig::default()
    };
    config.validate().unwrap();
    config.execution_isolation_profile = ExecutionIsolationProfile::ExternalCapsule;
    assert!(config.validate().is_err());
    assert!(WasmtimeConfig::default()
        .development_clock_readings
        .is_none());
}

#[tokio::test]
async fn http_fixture_owns_private_authority_and_rejects_other_workspaces() {
    use crate::http_fixture::{Exchange, Fixture, Peer};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    fn fixture() -> Fixture {
        let probe = std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0)).unwrap();
        Fixture {
            port: probe.local_addr().unwrap().port(),
            exchanges: vec![Exchange {
                method: "GET".into(),
                path: "/fixture".into(),
                request_body: String::new(),
                status: 200,
                response_body: "b3duZWQ=".into(),
            }],
        }
    }
    async fn request(fixture: &Fixture, authorization: &str) -> Vec<u8> {
        let mut stream =
            tokio::net::TcpStream::connect((std::net::Ipv4Addr::LOCALHOST, fixture.port))
                .await
                .unwrap();
        stream.write_all(format!("GET /fixture HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nAuthorization: {authorization}\r\n\r\n", fixture.port).as_bytes()).await.unwrap();
        let mut reply = Vec::new();
        tokio::time::timeout(
            std::time::Duration::from_secs(3),
            stream.read_to_end(&mut reply),
        )
        .await
        .unwrap()
        .unwrap();
        reply
    }
    let first = fixture();
    let mut peer = Peer::start(&first).unwrap();
    let mut other = Peer::start(&fixture()).unwrap();
    assert_ne!(peer.authorization(), other.authorization());
    assert!(Peer::start(&first).is_err());
    let rejected = request(&first, other.authorization()).await;
    assert!(rejected.starts_with(b"HTTP/1.1 401"));
    assert!(!rejected.windows(5).any(|value| value == b"owned"));
    let accepted = request(&first, peer.authorization()).await;
    assert!(accepted.ends_with(b"owned"));
    assert_eq!(peer.shutdown().await.unwrap(), 1);
    assert_eq!(other.shutdown().await.unwrap(), 0);
    assert!(
        tokio::net::TcpStream::connect((std::net::Ipv4Addr::LOCALHOST, first.port))
            .await
            .is_err()
    );
}
