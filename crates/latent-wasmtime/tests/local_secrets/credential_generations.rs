use super::*;
use latent_capabilities::broker::secrets::{
    CredentialScope, ProviderCredential, TlsCredentialDestination, TlsCredentialProtocol,
    TlsCredentialScope, TlsProviderCredential,
};
use latent_secrets::SecretPurpose;

fn http_scope() -> CredentialScope {
    CredentialScope {
        tenant: TenantId("tests".into()),
        provider_id: "http".into(),
        origin: latent_policy::capability::HttpOrigin {
            scheme: "http".into(),
            host: "127.0.0.1".into(),
            port: 8080,
        },
    }
}
fn tls_scope() -> TlsCredentialScope {
    TlsCredentialScope {
        tenant: TenantId("tests".into()),
        provider_id: "http".into(),
        destination: TlsCredentialDestination {
            protocol: TlsCredentialProtocol::Nats,
            server_name: "127.0.0.1".into(),
            port: 8080,
        },
    }
}

#[tokio::test]
async fn captured_generation_is_actual_owner_number_and_identical_reload_cannot_retarget_it() {
    let f = Fixture::new().await;
    let captured = f
        .secrets
        .capture_provider_credential(http_scope(), "opaque".into())
        .unwrap();
    assert_eq!(
        captured.generation(),
        f.secrets.snapshot().unwrap().generation
    );
    let mut actual = None;
    captured
        .with_current_generation(&mut |generation| {
            actual = Some(generation);
            Ok(())
        })
        .unwrap();
    assert_eq!(actual, Some(1));
    captured
        .with_current_value(&mut |bytes| {
            assert_eq!(bytes, b"Alpha");
            Ok(())
        })
        .unwrap();
    f.secrets.reload(1, specs("2")).unwrap().await.unwrap();
    assert_eq!(captured.generation(), 1); // Description does not become current.
    let mut entered = false;
    assert!(captured
        .with_current_generation(&mut |_| {
            entered = true;
            Ok(())
        })
        .is_err());
    assert!(!entered);
    assert!(captured
        .with_current_value(&mut |_| panic!("old capture used new bytes"))
        .is_err());
    let replacement = f
        .secrets
        .capture_provider_credential(http_scope(), "opaque".into())
        .unwrap();
    assert_eq!(replacement.generation(), 2);
    replacement
        .with_current_generation(&mut |_| Ok(()))
        .unwrap();
    drop((captured, replacement));
    shutdown(&f).await;
}

#[tokio::test]
async fn retained_original_generation_keeps_existing_capacity_until_real_capture_destruction() {
    let f = Fixture::new().await;
    let captured = f
        .secrets
        .capture_provider_credential(http_scope(), "opaque".into())
        .unwrap();
    let another = captured.clone();
    f.secrets.reload(1, specs("2")).unwrap().await.unwrap();
    assert_eq!(f.secrets.snapshot().unwrap().retained_generations, 2);
    assert!(f.secrets.reload(2, specs("3")).is_err());
    drop(captured);
    assert_eq!(f.secrets.snapshot().unwrap().retained_generations, 2);
    assert!(another.with_current_generation(&mut |_| Ok(())).is_err());
    drop(another);
    assert_eq!(f.secrets.snapshot().unwrap().retained_generations, 1);
    assert_eq!(f.secrets.reload(2, specs("3")).unwrap().await.unwrap(), 3);
    shutdown(&f).await;
}

#[tokio::test]
async fn captured_credential_purpose_tenant_provider_and_destination_remain_exact() {
    let f = Fixture::new().await;
    for reference in ["allowed", "opaque"] {
        assert!(f
            .secrets
            .capture_tls_provider_credential(tls_scope(), reference.into())
            .is_err());
    }
    for selector in 0..4 {
        let mut scope = http_scope();
        match selector {
            0 => scope.tenant = TenantId("other".into()),
            1 => scope.provider_id = "other".into(),
            2 => scope.origin.host = "localhost".into(),
            _ => scope.origin.port = 4222,
        }
        assert!(f
            .secrets
            .capture_provider_credential(scope, "opaque".into())
            .is_err());
    }
    let mut next = specs("2");
    next[1].purpose = SecretPurpose::TlsProviderCredential {
        provider_id: "http".into(),
        destination: tls_scope().destination,
    };
    f.secrets.reload(1, next).unwrap().await.unwrap();
    assert!(f
        .secrets
        .capture_provider_credential(http_scope(), "opaque".into())
        .is_err());
    let captured = f
        .secrets
        .capture_tls_provider_credential(tls_scope(), "opaque".into())
        .unwrap();
    assert_eq!(captured.generation(), 2);
    captured
        .with_current_generation(&mut |number| {
            assert_eq!(number, 2);
            Ok(())
        })
        .unwrap();
    captured
        .with_current_value(&mut |bytes| {
            assert_eq!(bytes, b"Alpha");
            Ok(())
        })
        .unwrap();
    assert_eq!(invoke(&f, 2).await, 1001); // Opaque TLS owner still grants no guest read.
    f.secrets.reload(2, specs("3")).unwrap().await.unwrap();
    assert!(captured
        .with_current_value(&mut |_| panic!("TLS capture retargeted HTTP purpose"))
        .is_err());
    drop(captured);
    shutdown(&f).await;
}

#[tokio::test]
async fn original_credential_expiry_is_sticky_at_metadata_fence_without_plaintext_copy() {
    let f = Fixture::new().await;
    let mut next = specs("2");
    next[1].expires_at_unix_millis = Some(1100);
    f.secrets.reload(1, next).unwrap().await.unwrap();
    let captured = f
        .secrets
        .capture_provider_credential(http_scope(), "opaque".into())
        .unwrap();
    f.secret_clock.now.store(1200, Ordering::Release);
    let mut entered = false;
    assert_eq!(
        captured.with_current_generation(&mut |_| {
            entered = true;
            Ok(())
        }),
        Err(SecretError::Expired)
    );
    assert!(!entered);
    f.secret_clock.now.store(1000, Ordering::Release);
    assert_eq!(
        captured.with_current_value(&mut |_| panic!("expired bytes used")),
        Err(SecretError::Expired)
    );
    drop(captured);
    shutdown(&f).await;
}

#[tokio::test]
async fn close_rejects_original_capture_and_holds_physical_generation_until_last_owner_drops() {
    let f = Fixture::new().await;
    let captured = f
        .secrets
        .capture_provider_credential(http_scope(), "opaque".into())
        .unwrap();
    let other = captured.clone();
    f.secrets.close();
    let snapshot = f.secrets.snapshot().unwrap();
    assert!(snapshot.closed);
    assert_eq!(snapshot.retained_generations, 1);
    assert!(snapshot.reserved_generation_bytes > 0);
    assert!(captured
        .with_current_generation(&mut |_| panic!("closed owner installed a rule"))
        .is_err());
    assert!(f
        .secrets
        .capture_provider_credential(http_scope(), "opaque".into())
        .is_err());
    drop(captured);
    assert_eq!(f.secrets.snapshot().unwrap().retained_generations, 1);
    drop(other);
    assert_eq!(f.secrets.snapshot().unwrap().retained_generations, 0);
    shutdown(&f).await;
}
