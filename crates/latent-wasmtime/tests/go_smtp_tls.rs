//! Standard SMTP upgrades its compiler-owned TCP Conn with guest crypto/tls.
//! This is not a host-TLS or final-kernel-retirement qualification.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "local_service/component.rs"]
#[allow(dead_code)]
mod component;
#[path = "local_service/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "guest_sdk/package.rs"]
mod package;
#[path = "local_service/packages.rs"]
#[allow(dead_code)]
mod packages;
#[path = "../../latent-signing/tests/build_provenance/support.rs"]
#[allow(dead_code)]
mod provenance;
#[path = "go_smtp_tls/setup.rs"]
mod setup;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use fixture::Fixture;
use latent_activation::{ActivationOutcome, ActivationRequest};
use latent_artifacts::ArtifactRepository;
use latent_core::{ContractId, TenantId};
use latent_network::AddressPolicy;
use latent_policy::capability::{StreamEndpoint, StreamTransport};
use latent_streams::{StreamDestination, StreamLimits, StreamProviderConfig, StreamResolution};
use serde_json::json;
use std::{sync::Arc, time::Duration};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt, BufReader},
    net::TcpListener,
};
use tokio_rustls::TlsAcceptor;

const CONTRACT: &str = "examples:go-standard-network/api@1.0.0";
const PROFILE: &str = "go-component-activation-v5";
const SOURCE: &[u8] = include_bytes!("../../../sdk/go-guest/runtime/smtp-tls-conformance/main.go");
const WORLD: &str = include_str!("../../../sdk/go-guest/runtime/smtp-tls-conformance/world.wit");

fn identity() -> (TlsAcceptor, String) {
    let ca_key = rcgen::KeyPair::generate().unwrap();
    let mut ca_params = rcgen::CertificateParams::new(vec![]).unwrap();
    ca_params.is_ca = rcgen::IsCa::Ca(rcgen::BasicConstraints::Unconstrained);
    ca_params.key_usages = vec![rcgen::KeyUsagePurpose::KeyCertSign];
    let ca = ca_params.self_signed(&ca_key).unwrap();
    let issuer = rcgen::Issuer::new(ca_params, &ca_key);
    let key = rcgen::KeyPair::generate().unwrap();
    let mut params = rcgen::CertificateParams::new(vec!["mail.stream.test".into()]).unwrap();
    params.extended_key_usages = vec![rcgen::ExtendedKeyUsagePurpose::ServerAuth];
    let cert = params.signed_by(&key, &issuer).unwrap();
    let config = rustls::ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_safe_default_protocol_versions()
    .unwrap()
    .with_no_client_auth()
    .with_single_cert(
        vec![cert.der().clone()],
        rustls::pki_types::PrivateKeyDer::Pkcs8(key.serialize_der().into()),
    )
    .unwrap();
    let pem = format!(
        "-----BEGIN CERTIFICATE-----\n{}\n-----END CERTIFICATE-----\n",
        base64::Engine::encode(&base64::engine::general_purpose::STANDARD, ca.der())
    );
    (TlsAcceptor::from(Arc::new(config)), pem)
}

async fn command<S: AsyncRead + AsyncWrite + Unpin>(wire: &mut BufReader<S>, expected: &str) {
    // Only fixed fixture commands are accepted; no application payload is logged.
    let mut line = [0; 128];
    for index in 0..line.len() {
        wire.read_exact(&mut line[index..index + 1]).await.unwrap();
        if line[index] == b'\n' {
            assert_eq!(&line[..index + 1], expected.as_bytes());
            return;
        }
    }
    panic!("ordinary SMTP fixture command exceeded its fixed bound");
}

async fn finish<S: AsyncRead + AsyncWrite + Unpin>(wire: &mut BufReader<S>) {
    command(wire, "NOOP\r\n").await;
    wire.get_mut().write_all(b"250 OK\r\n").await.unwrap();
    command(wire, "QUIT\r\n").await;
    wire.get_mut().write_all(b"221 Bye\r\n").await.unwrap();
    wire.get_mut().shutdown().await.unwrap();
}

async fn exchange(listener: &TcpListener, acceptor: &TlsAcceptor, mode: u32) {
    let (socket, _) = listener.accept().await.unwrap();
    let mut wire = BufReader::new(socket);
    wire.get_mut()
        .write_all(b"220 mail.stream.test\r\n")
        .await
        .unwrap();
    command(&mut wire, "EHLO localhost\r\n").await;
    wire.get_mut()
        .write_all(b"250-mail.stream.test\r\n250 STARTTLS\r\n")
        .await
        .unwrap();
    if mode == 0 {
        finish(&mut wire).await;
        return;
    }
    command(&mut wire, "STARTTLS\r\n").await;
    wire.get_mut()
        .write_all(b"220 Begin TLS\r\n")
        .await
        .unwrap();
    assert!(wire.buffer().is_empty());
    let secure = acceptor.accept(wire.into_inner()).await;
    if mode == 2 || mode == 3 {
        assert!(
            secure.is_err(),
            "guest verification refusal must abort the TLS upgrade"
        );
        return;
    }
    let mut wire = BufReader::new(secure.unwrap());
    command(&mut wire, "EHLO localhost\r\n").await;
    wire.get_mut()
        .write_all(b"250 mail.stream.test\r\n")
        .await
        .unwrap();
    finish(&mut wire).await;
}

#[tokio::test]
#[ignore = "requires the freshly compiled ordinary Go SMTP/TLS fixture"]
async fn signed_ordinary_go_smtp_starttls_preserves_trust_hostname_and_fresh_connection() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").unwrap(), "go");
    let root = tempfile::tempdir().unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (acceptor, root_pem) = identity();
    let mut fixture = setup::configured(root.path(), port).await;
    let peer = tokio::spawn(async move {
        for mode in 0..6 {
            tokio::time::timeout(
                Duration::from_secs(60),
                exchange(&listener, &acceptor, mode),
            )
            .await
            .unwrap();
        }
    });
    for (mode, label, expected) in [
        (0, "ordinary-smtp-plain", "ordinary-smtp-plain"),
        (1, "ordinary-starttls13", "ordinary-smtp-tls13"),
        (2, "hostname-refused", "ordinary-starttls-hostname-refused"),
        (3, "trust-refused", "ordinary-starttls-trust-refused"),
        (4, "ordinary-starttls12", "ordinary-smtp-tls12"),
        (5, "fresh-starttls13", "ordinary-smtp-tls13"),
    ] {
        let receipt = fixture
            .manager
            .start(setup::request(&fixture, label, mode, port, &root_pem))
            .unwrap()
            .await;
        setup::returned(receipt, expected, 1);
        setup::idle(&fixture, label).await;
        setup::observed(label, mode, expected, 1);
    }
    peer.await.unwrap();
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 6);
    fixture.streams.take().unwrap().shutdown().await;
    println!(
        "GO_SMTP_COMPLETE {}",
        json!({"cases":6,"contacts":6,
        "cleanLogicalProviderStop":true,"normalProviderInstalled":false,
        "kernelRetirementQualified":false,"hostTlsQualified":false})
    );
}
