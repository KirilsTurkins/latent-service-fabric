use super::*;
use latent_capabilities::broker::secrets::{
    CredentialScope, TlsCredentialDestination, TlsCredentialProtocol, TlsCredentialScope,
};
use latent_secrets::SecretPurpose;

fn scope() -> TlsCredentialScope {
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

#[tokio::test]
async fn protocol_purpose_and_destination_cannot_be_substituted_or_retained_after_rotation() {
    let f = Fixture::new().await;
    let http = f
        .secrets
        .bind_credential(http_scope(), "opaque".into())
        .unwrap();
    for reference in ["opaque", "allowed"] {
        assert!(matches!(
            f.secrets.bind_tls_credential(scope(), reference.into()),
            Err(SecretError::PermissionDenied)
        ));
    }
    let mut next = specs("2");
    next[1].purpose = SecretPurpose::TlsProviderCredential {
        provider_id: "http".into(),
        destination: scope().destination,
    };
    f.secrets.reload(1, next).unwrap().await.unwrap();
    assert!(matches!(
        http.with_current_value(&mut |_| panic!("HTTP binding disclosed TLS material")),
        Err(SecretError::PermissionDenied)
    ));
    assert!(f
        .secrets
        .bind_credential(http_scope(), "opaque".into())
        .is_err());
    assert_eq!(invoke(&f, 2).await, 1001); // Actual guest cannot read TLS material.
    for selector in 0..4 {
        let mut wrong = scope();
        match selector {
            0 => wrong.tenant = TenantId("other".into()),
            1 => wrong.provider_id = "nats".into(),
            2 => wrong.destination.server_name = "localhost".into(),
            _ => wrong.destination.port = 4222,
        }
        assert!(f
            .secrets
            .bind_tls_credential(wrong, "opaque".into())
            .is_err());
    }
    let tls = f
        .secrets
        .bind_tls_credential(scope(), "opaque".into())
        .unwrap();
    tls.with_current_value(&mut |bytes| {
        assert_eq!(bytes, b"Alpha");
        Ok(())
    })
    .unwrap();
    f.secrets.reload(2, specs("3")).unwrap().await.unwrap();
    assert!(matches!(
        tls.with_current_value(&mut |_| panic!("TLS binding disclosed HTTP material")),
        Err(SecretError::PermissionDenied)
    ));
    drop((http, tls));
    shutdown(&f).await;
}
