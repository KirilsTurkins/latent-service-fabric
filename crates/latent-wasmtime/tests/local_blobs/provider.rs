use super::*;
use latent_capabilities::broker::blob::{BlobError, BlobInvoker};

#[tokio::test]
async fn retained_writer_rechecks_revocation_before_physical_write() {
    let f = Fixture::new().await;
    let (session, _control) = f.session("retained-writer");
    let mut writer = f
        .provider
        .create(&session, "text/plain".into(), Some(4))
        .unwrap()
        .await
        .unwrap();
    let before = f.provider.store().snapshot().unwrap();
    f.revoke();
    let result = match writer.write(0, b"data".to_vec()) {
        Ok(future) => future.await,
        Err(e) => Err(e),
    };
    assert!(matches!(result, Err(BlobError::PermissionDenied)));
    drop((writer, session));
    let after = f.provider.store().snapshot().unwrap();
    assert_eq!(after.objects, before.objects);
    assert_eq!(after.reserved_stage_bytes, 4);
    assert_eq!(after.handles, 0);
    f.provider.store().reclaim(64, &|| Ok(())).unwrap();
    f.idle();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
async fn chunks_and_file_handles_keep_independent_ownership_until_real_drop() {
    let f = Fixture::new().await;
    let (session, control) = f.session("chunk-owners");
    let observer = session.observer();
    let mut writer = f
        .provider
        .create(&session, "text/plain".into(), Some(4))
        .unwrap()
        .await
        .unwrap();
    writer.write(0, b"data".to_vec()).unwrap().await.unwrap();
    let sealed = writer.seal().unwrap().await.unwrap();
    let reference = sealed.reference;
    drop(sealed.owner);
    let mut reader = f
        .provider
        .open(&session, reference.clone())
        .unwrap()
        .await
        .unwrap();
    let chunk = reader.read(0, 4).unwrap().await.unwrap();
    assert_eq!(chunk.bytes(), b"data");
    assert_eq!(f.io.snapshot().result_bytes, 4);
    let local = latent_blobs::BlobReference {
        digest: latent_core::BlobDigest(reference.digest),
        size_bytes: reference.size,
        media_type: reference.media_type,
        tenant: TenantId("tests".into()),
        metadata: Metadata::new(),
    };
    f.provider
        .store()
        .release_reference(&TenantId("tests".into()), &local, &|| Ok(()))
        .unwrap();
    assert_eq!(
        f.provider.store().reclaim(64, &|| Ok(())).unwrap().objects,
        0
    );
    drop(reader);
    assert_eq!(
        f.provider.store().reclaim(64, &|| Ok(())).unwrap().objects,
        1
    );
    // A copied range no longer pins the file, but retains its own charged data.
    assert_eq!(chunk.bytes(), b"data");
    control.probe.0.store(true, Ordering::Release);
    drop(session);
    assert!(!observer.is_quiescent());
    assert_eq!(f.pools.snapshot().unwrap().running_requests, 1);
    drop(chunk);
    assert!(observer.is_quiescent());
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    f.idle();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
async fn closed_session_cannot_reauthorize_retained_writer() {
    let f = Fixture::new().await;
    let (session, _control) = f.session("closed-session");
    let mut writer = f
        .provider
        .create(&session, "text/plain".into(), Some(4))
        .unwrap()
        .await
        .unwrap();
    drop(session);
    assert!(writer.write(0, b"data".to_vec()).is_err());
    drop(writer);
    assert_eq!(
        f.provider.store().reclaim(64, &|| Ok(())).unwrap().stages,
        1
    );
    f.idle();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[test]
fn package_binding_preserves_owned_blob_chunks_and_value_only_exports() {
    let package = packages::capsule();
    latent_packaging::compile_host_binding(
        &package,
        component::CAP,
        latent_packaging::PackageComparisonLimits::default(),
    )
    .unwrap();
    let artifact = packages::artifact(&package);
    assert!(artifact.contracts[0].interfaces[0].functions[0].asynchronous);
    assert_eq!(artifact.manifest.imports[0].contract.0, component::CAP);
}

#[tokio::test]
async fn missing_provider_rejects_preparation_before_creating_a_store() {
    let factory = WasmtimeComponentEngineFactory::new(support::config()).unwrap();
    let backend = factory.create_backend_instance();
    let artifact = packages::artifact(&packages::capsule());
    let error = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .unwrap_err();
    assert_eq!(
        error.code,
        latent_core::PlatformErrorCode::IncompatibleContract
    );
    assert_eq!(backend.resource_snapshot().stores_created, 0);
}

#[tokio::test]
async fn cumulative_byte_budgets_reject_before_further_physical_io() {
    use latent_core::BudgetDimension;
    let f = Fixture::new().await;
    let (session, control) = f.session("finite-blob-bytes");
    control
        .budget
        .consume(BudgetDimension::BlobWriteBytes, 65532)
        .unwrap();
    control
        .budget
        .consume(BudgetDimension::BlobReadBytes, 65532)
        .unwrap();
    let mut writer = f
        .provider
        .create(&session, "text/plain".into(), Some(4))
        .unwrap()
        .await
        .unwrap();
    writer.write(0, b"data".to_vec()).unwrap().await.unwrap();
    let sealed = writer.seal().unwrap().await.unwrap();
    let reference = sealed.reference;
    drop(sealed.owner);
    let mut writer = f
        .provider
        .create(&session, "text/plain".into(), Some(4))
        .unwrap()
        .await
        .unwrap();
    assert_eq!(
        writer.write(0, b"more".to_vec()).unwrap().await,
        Err(BlobError::BudgetExhausted)
    );
    drop(writer);
    let mut reader = f.provider.open(&session, reference).unwrap().await.unwrap();
    let chunk = reader.read(0, 4).unwrap().await.unwrap();
    assert_eq!(chunk.bytes(), b"data");
    drop(chunk);
    assert!(matches!(
        reader.read(0, 1).unwrap().await,
        Err(BlobError::BudgetExhausted)
    ));
    drop(reader);
    let consumed = control.budget.snapshot_at(Instant::now());
    assert_eq!(consumed.blob_read_bytes, 65536);
    assert_eq!(consumed.blob_write_bytes, 65536);
    let retained = f.provider.store().snapshot().unwrap();
    assert_eq!(retained.resident_disk_bytes, 4);
    assert_eq!(retained.handles, 0);
    assert_eq!(
        f.provider.store().reclaim(64, &|| Ok(())).unwrap().stages,
        1
    );
    drop(session);
    f.idle();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}
