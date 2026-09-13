use super::*;

#[test]
fn caller_loss_after_observed_request_keeps_digest_uncertain_and_releases_owner() {
    runtime().block_on(async {
        let root=tempfile::tempdir().unwrap();
        let package=package();
        let args=input(root.path(),&package,evidence(&package));
        let (entered,ready)=tokio::sync::oneshot::channel();
        let mut entered=Some(entered);
        let server=server::Server::start(move |method,_,_| {
            assert_eq!(method,"HEAD");
            entered.take().unwrap().send(()).unwrap();
            server::Reply::held()
        }).await;
        let (registry,reference)=server.client();
        let budget=budget::Budget::new(MAX_GRAPH_BYTES);
        let mut progress=transfer::Progress::default();
        let command=PackageCommand::Push(args);
        {
            let transfer=transfer::run(&registry,reference,&command,&budget,&mut progress,Instant::now()+Duration::from_secs(5));
            tokio::pin!(transfer);
            tokio::select! {
                observed=tokio::time::timeout(Duration::from_secs(2),ready)=>observed.unwrap().unwrap(),
                result=&mut transfer=>panic!("transfer completed before cancellation: {result:?}"),
            }
        }
        assert_eq!(progress.summary(false)["uncertainDigest"],package.layout().digest().to_string());
        assert_eq!(progress.summary(false)["confirmedDigests"],serde_json::json!([]));
        registry.shutdown(Instant::now()+Duration::from_secs(2)).await.unwrap();
        assert_eq!(registry.usage().in_flight,0);
        assert_eq!(registry.usage().retained_bytes,0);
        assert_eq!(server.stop().await.len(),1);
    });
}

#[test]
fn denied_pull_does_not_export_and_diagnostics_exclude_credentials() {
    runtime().block_on(async {
        let root = tempfile::tempdir().unwrap();
        let server = server::Server::start(|_, _, _| server::Reply::status(403)).await;
        let (registry, reference) = server.client();
        let command = PackageCommand::Pull(PackagePullArgs {
            registry_profile: root.path().join("unused"),
            reference: "release".into(),
            output_dir: root.path().join("out"),
            evidence_output: root.path().join("proofs"),
        });
        let mut progress = transfer::Progress::default();
        let error = transfer::run(
            &registry,
            reference,
            &command,
            &budget::Budget::new(MAX_GRAPH_BYTES),
            &mut progress,
            Instant::now() + Duration::from_secs(5),
        )
        .await
        .err()
        .unwrap();
        assert!(!root.path().join("out").exists());
        assert!(!root.path().join("proofs").exists());
        assert!(!format!("{error:?}").contains("fixture-public-token"));
        assert!(progress.uncertain.is_none());
        registry
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap();
        assert_eq!(server.stop().await.len(), 1);
    });
}
