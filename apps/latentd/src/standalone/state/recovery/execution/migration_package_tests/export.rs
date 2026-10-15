use super::fixture::*;
use latent_core::PlatformError;
use latent_state::{
    protected_store::ProtectedSnapshotProfile, recovery::snapshot::SnapshotMetadata,
};

impl Fixture {
    pub fn legacy_metadata(&self, name: &str) -> SnapshotMetadata {
        SnapshotMetadata {
            tenant: "examples".into(),
            operation_id: name.into(),
            operator_id: "operator".into(),
            runtime_digest: self.codecs.runtime,
            decoder_formats: self.codecs.catalog.formats.clone(),
            required_artifacts: self.codecs.catalog.artifacts.clone(),
        }
    }

    pub async fn export_metadata(
        &self,
        metadata: SnapshotMetadata,
        name: &str,
    ) -> NativeBuffer<Result<serde_json::Value, PlatformError>> {
        self.idle().await;
        let response = self
            .codecs
            .original
            .reserve_buffer(NativeBufferClass::Response, 2 * 1024 * 1024)
            .unwrap();
        let view = self.codecs.clone();
        let artifact = self.codecs.clone();
        let row = self.codecs.clone();
        let current = self.codecs.clone();
        let file = self.file(name);
        let result = async {
            let job = self
                .store
                .create_reviewed_snapshot_profile(
                    super::super::file_config(&file),
                    metadata,
                    self.codecs.original.clone(),
                    move |source| {
                        view.closure(source)
                            .map_err(latent_state::recovery::snapshot::SnapshotError::Review)
                    },
                    move |required| artifact.artifact(required),
                    move |key, bytes| row.row(key, bytes),
                    Arc::new(move || current.check()),
                    self.codecs.authority.file_bytes,
                    ProtectedSnapshotProfile::SingleNamespace,
                )
                .map_err(super::super::protected)?;
            let (snapshot, outcome) = super::super::awaited(job, &self.codecs).await?;
            let outcome = outcome
                .map_err(super::super::protected)?
                .map_err(super::super::snapshot_error);
            let retired = super::super::retire(snapshot, &self.codecs).await;
            Ok(super::super::with_retirement(
                super::super::snapshot_value(&outcome?),
                retired,
            ))
        }
        .await;
        response.attach(result)
    }
}
