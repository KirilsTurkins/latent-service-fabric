//! Separately scoped signed publications on one development stream lifecycle.
//! This is not an unchanged client or installed-provider qualification.
use super::{
    component, configuration, failure, idle, physical_closure, replace_tenant_record, success,
};
use crate::{
    fixture::{streams, Fixture},
    packages,
    runtime::{package, provenance},
};
use latent_activation::ActivationOutcome;
use latent_artifacts::{ArtifactRepository, LifecycleScope, PublicationRef};
use latent_core::{ActivationId, CancelDisposition, PlatformErrorCode, TenantId};
use latent_policy::capability::RecordKind;
use std::time::{Duration, Instant};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

async fn configured_two_tenants(root: &std::path::Path, port: u16) -> Fixture {
    let caller = packages::outbound_streams(component::bytes_with_contract(
        port,
        crate::component::CALLER,
    ));
    let callee = packages::callee(42);
    let signers = package::Signers::for_tenant(
        latent_signing::PROVENANCE_BUILD_TYPE,
        &TenantId("tenant-b".into()),
    );
    let config = configuration(port);
    let mut uploads = Vec::new();
    for (tenant, bundle) in [
        ("tenant-b", &caller),
        ("tenant-b", &callee),
        ("tenant-a", &caller),
    ] {
        let mut observation = provenance::observation();
        observation.source.repository =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        observation.component_digest = bundle.layout().component_release().unwrap().0;
        observation.component_size = bundle.blob("component.wasm").unwrap().len() as u64;
        let mut source = include_bytes!("../../outbound_streams/component.rs").to_vec();
        source.extend_from_slice(include_bytes!("../component.rs"));
        source.extend_from_slice(include_bytes!("../packages.rs"));
        source.extend_from_slice(include_bytes!("../fixture.rs"));
        source.extend_from_slice(include_bytes!("owners.rs"));
        source.extend_from_slice(include_bytes!("../outbound.rs"));
        source.extend_from_slice(include_bytes!("cross_tenant.rs"));
        source.extend_from_slice(include_bytes!(
            "../../../../../wit/platform/network/package.wit"
        ));
        source.extend_from_slice(&serde_json::to_vec(&config).unwrap());
        observation.source.snapshot_digest =
            latent_artifacts::package::artifact_blob_digest(&source).into_string();
        let material = observation
            .materials
            .iter_mut()
            .find(|material| material.name == "source-snapshot")
            .unwrap();
        material
            .digest
            .clone_from(&observation.source.snapshot_digest);
        material.size = source.len() as u64;
        let tenant = TenantId(tenant.into());
        uploads.push((
            tenant.clone(),
            signers.upload_for_tenant(bundle, &observation, &tenant),
        ));
    }
    let catalog = package::catalog(root, signers.policy, Some(packages::budget().memory_bytes));
    for (tenant, upload) in uploads {
        catalog
            .admit_package(&tenant, upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    let publication = |tenant: &str| {
        PublicationRef::package(
            LifecycleScope::Tenant(TenantId(tenant.into())),
            caller.layout().digest(),
        )
        .unwrap()
    };
    let first = publication("tenant-a");
    let second = publication("tenant-b");
    assert_ne!(first.id, second.id);
    for reference in [&first, &second] {
        let eligibility = catalog
            .execution_eligibility_selected(&packages::release(&caller), Some(&reference.id))
            .unwrap()
            .unwrap();
        assert_eq!(eligibility.publication(), &reference.id);
        catalog.fetch_publication(reference).unwrap();
    }
    Fixture::with_two_tenant_outbound_streams((catalog, caller, callee), config).await
}

fn request(
    fixture: &Fixture,
    tenant: &str,
    id: &str,
    mode: u32,
) -> latent_activation::ActivationRequest {
    let mut request = fixture.request(id, mode);
    request.target.tenant = TenantId(tenant.into());
    request.principal.tenant = Some(TenantId(tenant.into()));
    request
}

fn policy_document(fixture: &Fixture, tenant: &str) -> Vec<u8> {
    fixture
        .policies
        .get(
            tenant,
            RecordKind::Policy,
            streams::POLICY,
            65536,
            Instant::now() + Duration::from_secs(2),
        )
        .unwrap()
        .value()
        .as_ref()
        .unwrap()
        .document
        .as_ref()
        .unwrap()
        .as_bytes()
        .to_vec()
}

#[tokio::test]
async fn signed_tenant_b_succeeds_after_tenant_a_cancel_and_policy_retirement() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut fixture =
        configured_two_tenants(root.path(), listener.local_addr().unwrap().port()).await;
    let a_policy = policy_document(&fixture, "tenant-a");
    let b_policy = policy_document(&fixture, "tenant-b");
    let a: serde_json::Value = serde_json::from_slice(&a_policy).unwrap();
    let b: serde_json::Value = serde_json::from_slice(&b_policy).unwrap();
    assert_eq!(a["tenant"], "tenant-a");
    assert_eq!(b["tenant"], "tenant-b");
    assert_ne!(a["rules"][0]["publications"], b["rules"][0]["publications"]);

    let before_stores = fixture.backend.resource_snapshot().stores_created;

    let (accepted, accepted_rx) = tokio::sync::oneshot::channel();
    let (retired, retired_rx) = tokio::sync::oneshot::channel();
    let peer = async {
        let (mut original, _) = listener.accept().await.unwrap();
        let mut first = [0; 4];
        original.read_exact(&mut first).await.unwrap();
        assert_eq!(&first, b"PING");
        original.write_all(b"P").await.unwrap();
        accepted.send(()).unwrap();
        physical_closure(&mut original).await;
        retired_rx.await.unwrap();
        let (mut fresh, _) = listener.accept().await.unwrap();
        let mut second = Vec::with_capacity(5);
        (&mut fresh).take(5).read_to_end(&mut second).await.unwrap();
        assert_eq!(second, b"PING");
        fresh.write_all(b"PONG").await.unwrap();
        fresh.shutdown().await.unwrap();
    };
    let calls = async {
        let id = ActivationId("tenant-a-cancelled-stream".into());
        let mut original = Box::pin(
            fixture
                .manager
                .start(request(&fixture, "tenant-a", &id.0, 2))
                .unwrap(),
        );
        tokio::select! {
            result = &mut original => panic!("tenant A did not wait: {:?}", result.outcome),
            result = accepted_rx => result.unwrap(),
        }
        assert_eq!(fixture.backend.resource_snapshot().live_stores, 1);
        assert_eq!(
            fixture
                .manager
                .cancel_for(&TenantId("tenant-b".into()), &id, "foreign-stream-cancel")
                .unwrap(),
            CancelDisposition::NotFound
        );
        assert_eq!(fixture.backend.resource_snapshot().live_stores, 1);
        assert_eq!(
            fixture
                .manager
                .cancel_for(&TenantId("tenant-a".into()), &id, "owned-stream-cancel")
                .unwrap(),
            CancelDisposition::Accepted
        );
        let receipt = original.await;
        let ActivationOutcome::Failed {
            error, consumption, ..
        } = receipt.outcome
        else {
            panic!("tenant A must retain a cancelled outcome");
        };
        assert_eq!(error.code, PlatformErrorCode::Cancelled);
        assert_eq!(consumption.outbound_requests, 1);
        idle(&fixture).await;
        // Tenant B must also succeed after tenant A's own policy is removed.
        replace_tenant_record(
            &fixture,
            "tenant-a",
            RecordKind::Policy,
            streams::POLICY,
            "remove-a-after-cancel",
            None,
        );
        assert_eq!(policy_document(&fixture, "tenant-b"), b_policy);
        retired.send(()).unwrap();
        success(
            fixture
                .manager
                .start(request(&fixture, "tenant-b", "tenant-b-fresh-stream", 0))
                .unwrap()
                .await,
        );
        idle(&fixture).await;
    };
    tokio::time::timeout(Duration::from_secs(10), async {
        tokio::join!(calls, peer);
    })
    .await
    .expect("both tenant calls and their peers must complete");
    assert_eq!(
        fixture.backend.resource_snapshot().stores_created,
        before_stores + 2
    );
    fixture.streams.take().unwrap().shutdown().await;
}

#[tokio::test]
async fn signed_tenant_cannot_substitute_another_tenants_current_stream_grant() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut fixture =
        configured_two_tenants(root.path(), listener.local_addr().unwrap().port()).await;
    let a_policy = policy_document(&fixture, "tenant-a");
    let b_policy = policy_document(&fixture, "tenant-b");
    let a: serde_json::Value = serde_json::from_slice(&a_policy).unwrap();
    let b: serde_json::Value = serde_json::from_slice(&b_policy).unwrap();
    assert_ne!(a["rules"][0]["publications"], b["rules"][0]["publications"]);

    // Removing B's exact policy makes B's precompiled plan stale; A's current
    // policy and publication must not be substituted for it.
    replace_tenant_record(
        &fixture,
        "tenant-b",
        RecordKind::Policy,
        streams::POLICY,
        "remove-b-stream-policy",
        None,
    );
    let denied =
        match fixture
            .manager
            .start(request(&fixture, "tenant-b", "missing-b-stream-policy", 0))
        {
            Ok(invocation) => failure(
                tokio::time::timeout(Duration::from_secs(5), invocation)
                    .await
                    .expect("denied tenant must not wait for a peer"),
            ),
            Err(error) => error,
        };
    assert_eq!(denied.code, PlatformErrorCode::PermissionDenied);
    assert!(
        tokio::time::timeout(Duration::from_millis(100), listener.accept())
            .await
            .is_err()
    );
    idle(&fixture).await;
    assert_eq!(policy_document(&fixture, "tenant-a"), a_policy);

    // A remains independently authorized against the same provider after B's
    // revocation, so the negative cannot pass because both tenants are broken.
    let peer = async {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut input = Vec::with_capacity(5);
        (&mut socket).take(5).read_to_end(&mut input).await.unwrap();
        assert_eq!(input, b"PING");
        socket.write_all(b"PONG").await.unwrap();
        socket.shutdown().await.unwrap();
    };
    let call = async {
        success(
            fixture
                .manager
                .start(request(
                    &fixture,
                    "tenant-a",
                    "tenant-a-after-b-revocation",
                    0,
                ))
                .unwrap()
                .await,
        );
        idle(&fixture).await;
    };
    tokio::time::timeout(Duration::from_secs(10), async {
        tokio::join!(call, peer);
    })
    .await
    .expect("authorized tenant and peer must complete");
    fixture.streams.take().unwrap().shutdown().await;
}
