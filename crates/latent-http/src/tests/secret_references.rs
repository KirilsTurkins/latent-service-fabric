#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
use super::*;
use latent_capabilities::broker::{secrets::CredentialScope, CapabilityBindingSpec};
use latent_core::{DeploymentId, TenantId};
use latent_policy::capability::{MutationRequest, RecordKind};
use latent_secrets::{
    LocalSecretStore, SecretLimits, SecretPurpose, SecretSource, SecretSpec, SystemSecretClock,
};
use std::{os::unix::fs::PermissionsExt, time::Instant};

fn specs(origin: &HttpOrigin, version: &str) -> Vec<SecretSpec> {
    vec![SecretSpec {
        tenant: TenantId("a".into()),
        reference: "upstream-auth".into(),
        source: SecretSource::File {
            name: "token".into(),
        },
        purpose: SecretPurpose::ProviderCredential {
            provider_id: "http".into(),
            origin: origin.clone(),
        },
        media_type: "text/plain".into(),
        version: version.into(),
        expires_at_unix_millis: None,
    }]
}
fn write(root: &std::path::Path, bytes: &[u8]) {
    let path = root.join("token");
    std::fs::write(&path, bytes).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
}
#[expect(
    clippy::too_many_lines,
    reason = "compose explicit real catalog, provider and replacement binding ownership in one fixture"
)]
async fn configured(port: u16, streaming: bool) -> (Fixture, LocalSecretStore, std::path::PathBuf) {
    let mut config = config(port);
    config.destinations[0].redirect_destinations.clear();
    let origin = config.destinations[0].origin.clone();
    let limits = HttpStreamLimits {
        maximum_input_bytes: 1024,
        maximum_output_bytes: 1024,
        maximum_chunk_bytes: 64,
        maximum_outstanding_chunks: 1,
    };
    let mut f = if streaming {
        Fixture::streaming(config.clone(), limits)
    } else {
        Fixture::new(config.clone())
    };
    let root = f.directory.path().join("secrets");
    std::fs::create_dir(&root).unwrap();
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
    write(&root, b"Bearer synthetic-alpha");
    let store = LocalSecretStore::open(
        f.pools.clone(),
        root.clone(),
        SecretLimits::default(),
        vec![],
        Arc::new(SystemSecretClock),
    )
    .unwrap()
    .await
    .unwrap();
    store.reload(0, specs(&origin, "1")).unwrap().await.unwrap();
    let reference = HttpCredentialReference {
        destination: 0,
        name: "authorization".into(),
        binding: store
            .bind_credential(
                CredentialScope {
                    tenant: TenantId("a".into()),
                    provider_id: "http".into(),
                    origin,
                },
                "upstream-auth".into(),
            )
            .unwrap(),
    };
    if streaming {
        let provider = StreamingHttpProvider::install_with_secret_references(
            f.pools.clone(),
            "http",
            2,
            1,
            config,
            limits,
            vec![reference],
        )
        .unwrap();
        f.provider = provider.provider.clone();
        f.streaming = Some(provider);
    } else {
        f.provider = HttpProvider::install_with_secret_references(
            f.pools.clone(),
            "http",
            2,
            1,
            config,
            vec![reference],
        )
        .unwrap();
    }
    let reference = f.provider.reference();
    let body = serde_json::to_vec(&serde_json::json!({"formatVersion":1,"tenant":"a","capability":reference.capability(),
        "providerProfile":reference.profile(),"configurationDigest":reference.configuration_digest(),"configurationEpoch":2,"restriction":{"operations":[]}})).unwrap();
    f.policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "binding",
                kind: RecordKind::ProviderBinding,
                operation_id: "install-opaque",
                expected_revision: 3,
                document: Some(&body),
            },
            Instant::now() + Duration::from_secs(2),
            |_| Ok(()),
        )
        .unwrap();
    f.plan = f
        .broker
        .compile_invocation_plan(
            &f.revision,
            Some(&DeploymentId("http-deployment".into())),
            &[CapabilityBindingSpec {
                definition_digest: Some(&latent_artifacts::package::artifact_blob_digest(
                    b"http-fixture-binding-v1",
                )),
                provider: &reference,
                imported_operations: &[if streaming { "open" } else { "send" }.into()],
                policy_ids: &["p".into()],
                provider_binding_id: "binding",
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
    (f, store, root)
}

#[tokio::test]
async fn both_http_profiles_use_rotated_opaque_credentials_and_refuse_revoked_material() {
    use latent_capabilities::broker::streaming_http::{StreamingHttpInvoker, StreamingHttpRequest};
    for streaming in [false, true] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let (f, store, root) = configured(port, streaming).await;
        let server = tokio::spawn(async move {
            for token in ["Bearer synthetic-alpha", "Bearer synthetic-beta"] {
                let (mut stream, _) = listener.accept().await.unwrap();
                let wire = read_request(&mut stream).await;
                assert!(String::from_utf8(wire)
                    .unwrap()
                    .contains(&format!("authorization: {token}\r\n")));
                stream
                    .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    .await
                    .unwrap();
            }
            assert!(
                tokio::time::timeout(Duration::from_millis(150), listener.accept())
                    .await
                    .is_err()
            );
        });
        let origin = f.provider.inner.config.destinations[0].origin.clone();
        for number in 1..=3 {
            let (session, _) = f.session(5000);
            let accepted = if streaming {
                let upload = f
                    .streaming
                    .as_ref()
                    .unwrap()
                    .start(
                        &session,
                        StreamingHttpRequest {
                            metadata: request(port, HttpMethod::Get),
                            body_length: Some(0),
                        },
                    )
                    .unwrap()
                    .await;
                match upload {
                    Ok(upload) => upload
                        .finish()
                        .await
                        .map(|body| {
                            assert_eq!(body.head().status(), 200);
                            drop(body);
                        })
                        .is_ok(),
                    Err(_) => false,
                }
            } else {
                f.provider
                    .start(&session, request(port, HttpMethod::Get))
                    .unwrap()
                    .await
                    .unwrap()
                    .response
                    .is_ok()
            };
            assert_eq!(accepted, number < 3);
            drop(session);
            if number == 1 {
                write(&root, b"Bearer synthetic-beta");
                store.reload(1, specs(&origin, "2")).unwrap().await.unwrap();
            }
            if number == 2 {
                store.reload(2, vec![]).unwrap().await.unwrap();
            }
        }
        server.await.unwrap();
        store.close();
        f.clean().await;
    }
}

#[tokio::test]
async fn provider_bindings_reject_wrong_tenant_origin_header_and_guest_overrides() {
    let (f, store, _) = configured(8080, false).await;
    let mut scope = CredentialScope {
        tenant: TenantId("b".into()),
        provider_id: "http".into(),
        origin: f.provider.inner.config.destinations[0].origin.clone(),
    };
    assert!(store
        .bind_credential(scope, "upstream-auth".into())
        .is_err());
    scope = CredentialScope {
        tenant: TenantId("a".into()),
        provider_id: "other".into(),
        origin: f.provider.inner.config.destinations[0].origin.clone(),
    };
    assert!(store
        .bind_credential(scope, "upstream-auth".into())
        .is_err());
    let credential = f.provider.inner.credential_references[0].binding.clone();
    let mut config = f.provider.inner.config.clone();
    config.destinations[0].origin.port = 8081;
    assert!(HttpProvider::install_with_secret_references(
        f.pools.clone(),
        "other",
        1,
        0,
        config,
        vec![HttpCredentialReference {
            destination: 0,
            name: "authorization".into(),
            binding: credential.clone()
        }]
    )
    .is_err());
    assert!(HttpProvider::install_with_secret_references(
        f.pools.clone(),
        "http",
        3,
        2,
        f.provider.inner.config.clone(),
        vec![HttpCredentialReference {
            destination: 0,
            name: "host".into(),
            binding: credential
        }]
    )
    .is_err());
    assert!(f
        .provider
        .inner
        .check_credential_tenant(&TenantId("b".into()), 0)
        .is_err());
    let (session, _) = f.session(5000);
    let mut input = request(8080, HttpMethod::Get);
    input.headers.push(HttpHeader {
        name: "authorization".into(),
        value: "guest-attempt".into(),
    });
    assert!(f.provider.start(&session, input).is_err());
    drop(session);
    store.close();
    f.clean().await;
}
