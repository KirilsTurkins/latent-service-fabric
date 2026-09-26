//! Real signed packages and compiler, including both preparation entry paths.
use super::*;

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires fresh LSF_OPERATOR_FIXTURE_ROOT and real LSF_AOT_COMPILER"]
async fn external_profile_preserves_cold_warm_and_restart_requirements() {
    for workers in [Some(1), None] {
        let fixture = Fixture::new(Cause::ProofAge);
        let clock = Arc::new(Clock(AtomicU64::new(fixture.now)));
        let authority = fixture.authority(clock.clone());
        let repository = fixture.repository(authority.clone());
        reject_parent_inputs(&fixture, &repository).await;
        let admitted = repository
            .admit_package(&TenantId("tests".into()), fixture.upload(), &mut |_| Ok(()))
            .await
            .unwrap();
        let release = admitted.descriptor.release_digest;
        let selected = WasmtimeConfig {
            compiler_workers: workers,
            ..config()
        };
        let session = Session::with_config(&fixture, repository.clone(), selected.clone());
        let key = session.factory.preparation_key(release.clone());
        for _ in 0..2 {
            let active = if workers.is_some() {
                let ready = session.prepare(repository.clone(), &release).await.unwrap();
                session.backend.materialize_ready(ready).unwrap()
            } else {
                session
                    .backend
                    .prepare_from_repository(repository.as_ref(), &key)
                    .await
                    .unwrap()
            };
            session.invoke(active).await;
        }
        assert_eq!(session.snapshot().isolated_compilations, 1);
        assert_eq!(session.snapshot().images.loader_attempts, 1);
        assert_eq!(
            session.snapshot().producer,
            latent_wasmtime::AotResourceSnapshot::default()
        );
        session.close();
        drop(repository);
        authority.retire();
        drop(authority);
        clock.0.fetch_add(6, Ordering::AcqRel);

        let authority = fixture.authority(clock);
        let repository = fixture.repository(authority);
        let reopened = Session::with_config(&fixture, repository.clone(), selected);
        let ready = reopened.prepare(repository, &release).await.unwrap();
        assert_eq!(reopened.snapshot().cache_hits, 1);
        assert_eq!(reopened.snapshot().isolated_compilations, 0);
        assert_eq!(reopened.snapshot().images.loader_attempts, 1);
        reopened
            .invoke(reopened.backend.materialize_ready(ready).unwrap())
            .await;
        assert_eq!(
            reopened.snapshot().producer,
            latent_wasmtime::AotResourceSnapshot::default()
        );
        reopened.close();
    }
}

async fn reject_parent_inputs(fixture: &Fixture, repository: &DirectoryArtifactRepository) {
    for variant in 0..4 {
        let mut upload = fixture.upload();
        let mut tenant = TenantId("tests".into());
        match variant {
            0 => upload.manifest = b"{".to_vec(),
            1 => upload.configuration = b"{}".to_vec(),
            2 => upload.signatures.clear(),
            3 => tenant = TenantId("unauthorized-tenant".into()),
            _ => unreachable!(),
        }
        assert!(repository.admit_package(&tenant, upload, &mut |_| Ok(())).await.is_err(),
            "malformed package, changed digest, absent publisher proof and wrong tenant cannot acquire authority");
    }
    // The subsequent valid admission/preparation must still succeed: rejected
    // parent-side work cannot poison the catalog or force compilation fallback.
}
