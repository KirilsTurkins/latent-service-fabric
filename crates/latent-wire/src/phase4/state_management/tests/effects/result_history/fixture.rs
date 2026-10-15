use super::*;
use latent_state::{
    embedded::{AtomicBatch, ExpectedRow, Family, RowKey, RowMutation, StoreError},
    namespace::{history::history_key, history::NamespaceHistory},
    store_io::StoreIoKind,
};

pub(super) struct HistoryFixture {
    pub effect: effects_fixture::FixtureEffect,
    pub backend: StateManagementBackend,
    pub original: t::CommandInspection,
    pub original_schema: String,
    pub current_schema: String,
}

pub(super) fn backend(
    effect: &effects_fixture::FixtureEffect,
    schema: &str,
    result_policy: &str,
) -> StateManagementBackend {
    let original = &effect.fixture.backend.0.bindings[0];
    let mut binding = super::super::super::fixture::binding(
        original.publication.clone(),
        original.component.clone(),
    );
    binding.state_schema = schema.into();
    binding.result_policy = result_policy.into();
    binding
        .state
        .operations
        .extend(["read-result".into(), "cancel-command".into()]);
    let services = &effect.fixture.backend.0.services;
    StateManagementBackend::new(
        StateManagementServices {
            store: Arc::clone(&services.store),
            namespaces: Arc::clone(&services.namespaces),
            policy: Arc::clone(&services.policy),
            artifacts: Arc::clone(&services.artifacts),
            authorization: Arc::clone(&services.authorization),
            admission: Arc::clone(&services.admission),
            maintenance: Arc::clone(&services.maintenance),
            maintenance_clock: Arc::clone(&services.maintenance_clock),
            clock: Arc::clone(&services.clock),
            audit: services.audit.clone(),
        },
        vec![binding],
    )
    .unwrap()
    .with_command_recovery(effect.dispatcher.command_admission_source())
    .unwrap()
}

impl HistoryFixture {
    pub async fn new() -> Self {
        let mut effect = effects_fixture::setup_with_recovery().await;
        let mut document = effect.fixture.document.clone();
        for rule in document["rules"].as_array_mut().unwrap() {
            if rule["id"] == "alice-effect-reader" || rule["id"] == "bob-effect-reader" {
                rule["operations"] =
                    serde_json::json!(["inspect-effect", "read-result", "cancel-command"]);
            }
        }
        effect
            .fixture
            .update(Some(&document), "original-result-reader-policy");
        effect.fixture.document = document;
        let original_schema = effect.fixture.backend.0.bindings[0].state_schema.clone();
        let backend = backend(&effect, &original_schema, "visibility-v1");
        let response = backend
            .execute_state(effects_fixture::reader("alice"), request(&effect).into())
            .await
            .unwrap();
        response.owner.with_current(&mut || {}).unwrap();
        let original = inspection(&response).clone();
        drop(response);
        Self {
            effect,
            backend,
            original,
            original_schema,
            current_schema: format!("sha256:{}", "4".repeat(64)),
        }
    }

    pub async fn advance(&mut self) {
        advance(&self.effect, &self.current_schema).await;
        self.backend = backend(&self.effect, &self.current_schema, "visibility-v1");
    }

    pub async fn finish(mut self) {
        drop(self.backend);
        self.effect.finish().await;
        assert!(self
            .effect
            .fixture
            .admission
            .native
            .snapshot()
            .unwrap()
            .physically_retired());
    }
}

pub(super) fn request(effect: &effects_fixture::FixtureEffect) -> t::LookupCommandRequest {
    t::LookupCommandRequest {
        profile: Some(contract::current_profile()),
        command: Some(effect.command.clone()),
        authorization_publication: effect.fixture.target().authorization_publication,
        attempt_id: None,
    }
}

pub(super) fn commit_request(fixture: &HistoryFixture) -> t::LookupCommitRequest {
    let request = request(&fixture.effect);
    t::LookupCommitRequest {
        profile: request.profile,
        command: request.command,
        authorization_publication: request.authorization_publication,
        receipt_id: fixture.original.commit.as_ref().unwrap().receipt_id.clone(),
    }
}

pub(super) fn inspection(response: &OwnedPhase4Response) -> &t::CommandInspection {
    match &response.response {
        contract::Response::LookupCommand(value) => value.command.as_ref().unwrap(),
        contract::Response::LookupCommit(value) => value.command.as_ref().unwrap(),
        _ => panic!("original result inspection required"),
    }
}

pub(super) async fn rows(effect: &effects_fixture::FixtureEffect) -> Vec<(RowKey, Vec<u8>)> {
    effect
        .fixture
        .store
        .with_store(StoreIoKind::RecoveryRead, WORK_BYTES as u64, |engine| {
            let view = engine.snapshot()?;
            let mut result = Vec::new();
            for family in [
                Family::Command,
                Family::Attempt,
                Family::Result,
                Family::State,
                Family::Outbox,
            ] {
                result.extend(view.scan(family, &[], 128, 1024 * 1024)?);
            }
            Ok(result)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}

pub(super) async fn advance(effect: &effects_fixture::FixtureEffect, schema: &str) {
    let schema = schema.to_owned();
    let namespaces = Arc::clone(&effect.fixture.backend.0.services.namespaces);
    effect
        .fixture
        .store
        .with_store(StoreIoKind::RecoveryWrite, 65_536, move |engine| {
            let view = engine.snapshot()?;
            let before = NamespaceCatalog::read_in(
                &view,
                &TenantId("a".into()),
                &StateNamespaceId("orders".into()),
            )
            .map_err(|_| StoreError::Corrupt)?
            .unwrap();
            let mut after = before.record().clone();
            after.state_schema = schema;
            after.version.generation = after.version.generation.checked_add(1).unwrap();
            let (mut history, old_history) = NamespaceHistory::capture(&view, before.record())?;
            history.state_schema.clone_from(&after.state_schema);
            history.epochs.schema = history.epochs.schema.checked_add(1).unwrap();
            let key = history_key(&after.tenant, &after.id, after.version.incarnation).unwrap();
            let expected = before.expectation();
            // Descriptive post-migration metadata fixture, not a migration producer
            // receipt. Original command/result/state/outbox bytes are not rewritten.
            // The real lifecycle accepts the same namespace/history CAS and resolves
            // only from the freshly committed actual row.
            let batch = AtomicBatch {
                expectations: vec![
                    expected.clone(),
                    ExpectedRow {
                        key: key.clone(),
                        value: old_history,
                    },
                ],
                mutations: vec![
                    RowMutation {
                        key: expected.key,
                        value: Some(after.encode().unwrap()),
                    },
                    RowMutation {
                        key,
                        value: Some(history.encode().unwrap()),
                    },
                ],
            };
            let mut completion = None;
            engine
                .apply_fenced(batch, || {
                    completion = Some(
                        namespaces
                            .lifecycle()
                            .begin_transition(&before, &after, true)
                            .map_err(|_| StoreError::Unavailable)?,
                    );
                    Ok::<_, StoreError>(())
                })
                .map_err(|_| StoreError::Unavailable)?;
            let current = NamespaceCatalog::read_in(&engine.snapshot()?, &after.tenant, &after.id)
                .map_err(|_| StoreError::Corrupt)?
                .unwrap();
            completion
                .unwrap()
                .resolve(&current)
                .map_err(|_| StoreError::Unavailable)?;
            Ok(())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}
