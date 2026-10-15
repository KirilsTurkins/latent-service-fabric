use super::fixture::*;
use latent_core::PlatformError;

impl Fixture {
    pub async fn restore(
        &mut self,
        snapshot: &serde_json::Value,
        name: &str,
    ) -> NativeBuffer<Result<serde_json::Value, PlatformError>> {
        self.idle().await;
        let target = self.root.path().join(format!("restored-{name}"));
        let checkpoint = self.root.path().join(format!("checkpoint-{name}"));
        super::fixture::private_directory(&target);
        super::fixture::private_directory(&checkpoint);
        let identity = StoreIdentity::new(format!("restored-{name}")).unwrap();
        let operation = format!("restore-{name}");
        let source = snapshot["snapshotDigest"].as_str().unwrap();
        let manifest = snapshot["manifestDigest"].as_str().unwrap();
        self.reseal(Action::InspectRestore {
            file: self.file(name),
            destination_root: target.clone(),
            destination_checkpoint_root: checkpoint.clone(),
            operation_id: operation.clone(),
            snapshot_digest: source.into(),
            manifest_digest: manifest.into(),
            destination_store_identity: Some(identity.clone()),
        });
        let response = self
            .codecs
            .original
            .reserve_buffer(NativeBufferClass::Response, 2 * 1024 * 1024)
            .unwrap();
        let inspected = Box::pin(super::super::execute(
            &self.store,
            self.codecs.clone(),
            &self.settings,
        ))
        .await;
        let inspected = response.attach(inspected);
        let acknowledgement = match inspected.get() {
            Ok(value) => {
                assert_eq!(value["resourcePhysicallyRetired"], true);
                value["windowDigest"].as_str().unwrap().to_owned()
            }
            Err(_) => return inspected,
        };
        drop(inspected);
        self.idle().await;
        self.reseal(Action::Restore {
            file: self.file(name),
            destination_root: target,
            destination_checkpoint_root: checkpoint,
            operation_id: operation,
            snapshot_digest: source.into(),
            manifest_digest: manifest.into(),
            window_acknowledgement: acknowledgement,
            destination_store_identity: Some(identity),
        });
        let response = self
            .codecs
            .original
            .reserve_buffer(NativeBufferClass::Response, 2 * 1024 * 1024)
            .unwrap();
        response.attach(
            Box::pin(super::super::execute(
                &self.store,
                self.codecs.clone(),
                &self.settings,
            ))
            .await,
        )
    }
}
