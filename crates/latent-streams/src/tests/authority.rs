//! A working typed HTTP grant cannot be reinterpreted as opaque stream access.
use super::{config, fixture::Fixture};
use crate::{StreamErrorCode, StreamResolution};
use latent_capabilities::broker::{
    http::{HttpMethod, HttpRequest, OutboundHttpInvoker, HTTP_CAPABILITY},
    network::{OutboundStreamInvoker, StreamConnectRequest},
    CapabilityBindingSpec, CapabilitySession,
};
use latent_executor::BoundImport;
use latent_http::{HttpDestination, HttpLimits, HttpProvider, HttpProviderConfig, HttpResolution};
use latent_policy::capability::{HttpOrigin, MutationRequest, RecordKind};
use serde_json::json;
use std::time::{Duration, Instant};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, UdpSocket},
};

fn http_provider(f: &Fixture) -> HttpProvider {
    let destination = &f.provider.inner.config.destinations[0];
    HttpProvider::install(
        f.pools.clone(),
        "typed-http-control",
        1,
        0,
        HttpProviderConfig {
            format_version: 1,
            destinations: vec![HttpDestination {
                origin: HttpOrigin {
                    scheme: "http".into(),
                    host: destination.endpoint.host.clone(),
                    port: destination.endpoint.port,
                },
                addresses: destination.addresses.clone(),
                resolution: HttpResolution::Static {
                    addresses: vec!["127.0.0.1".parse().unwrap()],
                },
                allowed_request_headers: vec![],
                redirect_destinations: vec![],
            }],
            // Both providers retain the fixture's original 16 KiB I/O cap.
            // HTTP's default 32 KiB buffers would fail before this tiny GET
            // could prove that the independent typed authority works.
            limits: HttpLimits {
                maximum_request_body_bytes: 8 * 1024,
                maximum_response_body_bytes: 8 * 1024,
                maximum_encoded_response_bytes: 8 * 1024,
                maximum_header_bytes: 1024,
                maximum_headers: 8,
                maximum_redirects: 0,
            },
            extra_roots: vec![],
            public_roots: false,
        },
        &[],
    )
    .unwrap()
}

fn http_session(
    f: &Fixture,
    provider: &HttpProvider,
) -> (CapabilitySession, super::fixture::Control) {
    let reference = provider.reference();
    let endpoint = &f.provider.inner.config.destinations[0].endpoint;
    for (id, kind, document) in [
        (
            "http-only-policy",
            RecordKind::Policy,
            json!({"formatVersion":1,"tenant":"a","rules":[{
                "id":"get-only","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
                "services":["echo"],"publications":[f.publication.publication().as_str()],"capability":HTTP_CAPABILITY,
                "operations":["send"],"resources":{"kind":"http","origins":[{"scheme":"http","host":endpoint.host,"port":endpoint.port}],
                    "methods":["GET"],"paths":["/allowed"],"pathPrefixes":[]},
                "ceiling":{"operations":4,"inputBytes":1_000_000,"outputBytes":1_000_000,"wallTimeMillis":5000}
            }]}),
        ),
        (
            "http-only-binding",
            RecordKind::ProviderBinding,
            json!({"formatVersion":1,"tenant":"a","capability":HTTP_CAPABILITY,
                "providerProfile":latent_http::HTTP_PROVIDER_PROFILE,"configurationDigest":reference.configuration_digest(),
                "configurationEpoch":1,"restriction":{"operations":[]}}),
        ),
    ] {
        f.policies
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    id,
                    kind,
                    operation_id: id,
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&document).unwrap()),
                },
                Instant::now() + Duration::from_secs(2),
                |_| Ok(()),
            )
            .unwrap();
    }
    let plan = f
        .broker
        .compile_invocation_plan(
            &f.revision,
            Some(&latent_core::DeploymentId("http-only-deployment".into())),
            &[CapabilityBindingSpec {
                definition_digest: Some(&latent_artifacts::package::artifact_blob_digest(
                    b"http-only-original-binding",
                )),
                provider: &reference,
                imported_operations: &["send".into()],
                policy_ids: &["http-only-policy".into()],
                provider_binding_id: "http-only-binding",
                deployment_restriction_json: br#"{"operations":[]}"#,
            }],
            &f.publication,
            &[],
            &[],
            &[],
            None,
            Instant::now() + Duration::from_secs(2),
        )
        .unwrap();
    let (mut execution, control) = f.request("http-only-root", 5000);
    execution.imports = vec![BoundImport {
        capability: latent_core::CapabilityId(HTTP_CAPABILITY.into()),
        contract: HTTP_CAPABILITY.into(),
        opaque_handle: "not-authority".into(),
    }];
    let session = f
        .broker
        .open_session(plan, &execution, &control, &f.publication)
        .unwrap();
    (session, control)
}

#[tokio::test]
async fn genuine_http_only_authority_denies_opaque_bytes_before_dns_and_contact() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let dns = UdpSocket::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let mut configuration = config();
    configuration.destinations[0].endpoint.host = "endpoint.test".into();
    configuration.destinations[0].endpoint.port = port;
    configuration.destinations[0].resolution = StreamResolution::Dns {
        server: dns.local_addr().unwrap(),
        maximum_ttl_seconds: 1,
    };
    let f = Fixture::new(configuration);
    let http = http_provider(&f);
    let (session, control) = http_session(&f, &http);
    let invocation = f.provider.start(
        &session,
        StreamConnectRequest {
            endpoint: f.provider.inner.config.destinations[0].endpoint.clone(),
            timeout_millis: None,
        },
    );
    let denied = match invocation {
        Err(failure) => failure,
        Ok(pending) => pending.await.err().unwrap(),
    };
    assert_eq!(denied.code, StreamErrorCode::Denied);
    assert!(!denied.may_have_applied);
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        0
    );
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(f.provider.usage().unwrap().owners, 0);
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    assert_eq!(f.io.snapshot(), Default::default());
    let mut packet = [0; 512];
    assert!(
        tokio::time::timeout(Duration::from_millis(50), dns.recv_from(&mut packet))
            .await
            .is_err()
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(50), listener.accept())
            .await
            .is_err()
    );

    // The original HTTP-only session still executes the granted operation
    // after opaque stream denial; no replacement authority is issued.
    typed_get(&http, &session, listener).await;
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        1
    );
    drop(session);
    drop(http);
    f.clean().await;
}

async fn typed_get(http: &HttpProvider, session: &CapabilitySession, listener: TcpListener) {
    let port = listener.local_addr().unwrap().port();
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut header = Vec::new();
        let mut byte = [0];
        while !header.ends_with(b"\r\n\r\n") {
            assert!(header.len() < 8192);
            assert_eq!(socket.read(&mut byte).await.unwrap(), 1);
            header.push(byte[0]);
        }
        assert!(header.starts_with(b"GET /allowed HTTP/1.1\r\n"));
        socket
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
            .await
            .unwrap();
        socket.shutdown().await.unwrap();
    });
    let completion = http
        .start(
            session,
            HttpRequest {
                method: HttpMethod::Get,
                url: format!("http://endpoint.test:{port}/allowed"),
                headers: vec![],
                body: None,
                body_media_type: None,
                idempotency_key: None,
                timeout_millis: None,
            },
        )
        .unwrap()
        .await
        .unwrap();
    let response = completion.response.unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(response.body(), b"OK");
    drop(response);
    drop(completion.owner);
    peer.await.unwrap();
}
