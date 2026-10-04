use super::super::*;
use crate::{
    embedded::{
        AtomicBatch, EmbeddedStore, Family, ReadView, RowKey, RowMutation, StoreError, StoreLimits,
    },
    namespace::{
        catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
        compatibility::{RetainedCount, RetainedInventory, ReviewedSchema, SchemaDeclaration},
        NamespaceQuota, NamespaceTransition,
    },
    recovery::snapshot::{
        export_snapshot, inspect_snapshot, visit_view, RequiredArtifact, SnapshotClosure,
        SnapshotMetadata,
    },
    session::{ObservedCell, StateMode, StateScope, StateSession},
    store_identity::StoreIdentity,
    tenant::{GlobalMetadataAllowance, TenantCensus, TenantQuota, TenantUsage},
};
use latent_core::{transaction_contract::Value, StateNamespaceId, TenantId};
use std::{
    io::Cursor,
    time::{Duration, Instant},
};

pub(crate) struct Fixture {
    pub store: EmbeddedStore,
    pub root: tempfile::TempDir,
    pub archive: Vec<u8>,
    inputs: Inputs,
}

#[derive(Clone)]
pub(crate) struct Inputs {
    pub recipe: AggregateMigrationRecipe,
    pub request: AggregateMigrationRequest,
    pub schema: ReviewedSchema,
    pub metadata: SnapshotMetadata,
    pub quota: Option<TenantQuota>,
}

impl std::ops::Deref for Fixture {
    type Target = Inputs;
    fn deref(&self) -> &Inputs {
        &self.inputs
    }
}
impl std::ops::DerefMut for Fixture {
    fn deref_mut(&mut self) -> &mut Inputs {
        &mut self.inputs
    }
}

pub(crate) struct Receipt {
    action: MigrationAction,
    progress: AggregateMigrationProgress,
}
impl Receipt {
    pub fn action(&self) -> MigrationAction {
        self.action
    }
    pub fn progress(&self) -> &AggregateMigrationProgress {
        &self.progress
    }
}

pub(in crate::recovery) fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(20)
}

pub(super) fn open(path: &std::path::Path, create: bool) -> EmbeddedStore {
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(create)
        .open(path.join("migration.redb"))
        .unwrap();
    EmbeddedStore::open_file(
        file,
        StoreLimits {
            cache_bytes: 1024 * 1024,
            ..StoreLimits::default()
        },
    )
    .unwrap()
}

impl Fixture {
    pub fn new(recipe: AggregateMigrationRecipe, installed: bool) -> Self {
        Self::selected(recipe, installed, 32, None)
    }

    pub fn selected(
        recipe: AggregateMigrationRecipe,
        installed: bool,
        metadata_rows: u64,
        entity: Option<String>,
    ) -> Self {
        let root = tempfile::tempdir().unwrap();
        let store = open(root.path(), true);
        let view = store.snapshot().unwrap();
        let identity = StoreIdentity::new("original-migration-source".into()).unwrap();
        let batch = identity.prepare_initialization(&view).unwrap().unwrap();
        drop(view);
        store.apply(batch).unwrap();
        let inputs = populate(&store, recipe, installed, metadata_rows, entity);
        let mut fixture = Self {
            store,
            root,
            inputs,
            archive: vec![],
        };
        fixture.archive = fixture.export(fixture.metadata.clone());
        fixture.refresh_checkpoint_request();
        fixture
    }
}

pub(crate) fn populate(
    store: &EmbeddedStore,
    recipe: AggregateMigrationRecipe,
    installed: bool,
    metadata_rows: u64,
    entity: Option<String>,
) -> Inputs {
    let quota = installed.then(|| quota(metadata_rows));
    if let Some(quota) = &quota {
        let view = store.snapshot().unwrap();
        let setup = crate::tenant::prepare_install(&view, std::slice::from_ref(quota)).unwrap();
        drop(view);
        setup.publish(store, || Ok::<(), StoreError>(())).unwrap();
    }
    let mut scope = create_namespace(store, entity);
    put_original(store, &scope, recipe);
    scope.entity = None; // The installed recipe inspects the entire namespace.
    quiesce(store, &scope);
    let schema = reviewed_schema();
    let metadata = snapshot_metadata(recipe);
    let current = NamespaceMigrationView::capture(
        &store.snapshot().unwrap(),
        &scope.tenant,
        &scope.namespace,
    )
    .unwrap();
    let request = AggregateMigrationRequest {
        scope,
        operation_id: "change-format".into(),
        operator_id: "operator".into(),
        expected_view: current.view_token().unwrap(),
        checkpoint_digest: [1; 32],
        checkpoint_manifest_digest: [2; 32],
        package_digest: [43; 32],
        review_digest: [46; 32],
    };
    Inputs {
        recipe,
        request,
        schema,
        metadata,
        quota,
    }
}

fn quota(metadata_rows: u64) -> TenantQuota {
    TenantQuota {
        tenant: TenantId("tenant".into()),
        limits: TenantUsage {
            state_keys: 8,
            state_bytes: 8192,
            tombstone_keys: 8,
            tombstone_bytes: 8192,
            result_rows: 8,
            result_bytes: 65536,
            effect_rows: 8,
            effect_bytes: 65536,
            payload_bytes: 65536,
            recovery_bytes: 8192,
            metadata_rows,
            metadata_bytes: 65536,
        },
    }
}

fn create_namespace(store: &EmbeddedStore, entity: Option<String>) -> StateScope {
    let catalog = NamespaceCatalog::new();
    let (v1, _) = recipe::schema_ids().unwrap();
    let prepare = catalog
        .prepare(
            store,
            NamespaceOperationContext {
                tenant: TenantId("tenant".into()),
                actor: "operator".into(),
                operation_id: "create-source".into(),
            },
            &NamespaceMutation::Create {
                id: StateNamespaceId("business".into()),
                state_schema: v1.as_str().into(),
                quota: NamespaceQuota::default(),
            },
            0,
        )
        .unwrap();
    store.apply(prepare.batch).unwrap();
    StateScope {
        tenant: TenantId("tenant".into()),
        namespace: StateNamespaceId("business".into()),
        incarnation: 1,
        state_schema: v1.as_str().into(),
        entity,
        mode: StateMode::Command,
    }
}

fn put_original(store: &EmbeddedStore, scope: &StateScope, recipe: AggregateMigrationRecipe) {
    let view = store.snapshot().unwrap();
    let mut session =
        StateSession::open(&view, scope.clone(), Default::default(), |_, _| Ok(())).unwrap();
    session
        .put(
            &view,
            recipe.key().to_vec(),
            Value {
                bytes: u64::MAX.to_le_bytes().to_vec(),
                media_type: "application/vnd.lsf.aggregate-v1".into(),
                metadata: vec![],
            },
            |_, _| Ok(()),
        )
        .unwrap();
    let state = session.seal(&view, |_, _| Ok(())).unwrap();
    let pins = state.pins();
    let mut batch = AtomicBatch::default();
    state.append_to(&mut batch, pins).unwrap();
    drop(view);
    store.apply(batch).unwrap();
}

fn quiesce(store: &EmbeddedStore, scope: &StateScope) {
    let catalog = NamespaceCatalog::new();
    let current = catalog
        .inspect(store, &scope.tenant, &scope.namespace)
        .unwrap()
        .unwrap();
    let pause = catalog
        .prepare(
            store,
            NamespaceOperationContext {
                tenant: scope.tenant.clone(),
                actor: "operator".into(),
                operation_id: "pause-source".into(),
            },
            &NamespaceMutation::Transition {
                id: scope.namespace.clone(),
                expected: current.version,
                action: NamespaceTransition::Quiesce,
            },
            0,
        )
        .unwrap();
    store.apply(pause.batch).unwrap();
}

fn reviewed_schema() -> ReviewedSchema {
    let (v1, v2) = recipe::schema_ids().unwrap();
    ReviewedSchema::accept_with(
        SchemaDeclaration {
            package_digest: [43; 32],
            readers: vec![v1.clone(), v2.clone()],
            writers: vec![v2.clone()],
        },
        [43; 32],
        [44; 32],
        |_, _, _| Ok(()),
    )
    .unwrap()
}

fn snapshot_metadata(recipe: AggregateMigrationRecipe) -> SnapshotMetadata {
    let (v1, v2) = recipe::schema_ids().unwrap();
    let artifacts = vec![
        RequiredArtifact {
            identity: v1.as_str().into(),
            digest: recipe::schema_definitions()[0].1,
        },
        RequiredArtifact {
            identity: v2.as_str().into(),
            digest: recipe::schema_definitions()[1].1,
        },
        RequiredArtifact {
            identity: recipe.identity().into(),
            digest: recipe.digest(),
        },
        RequiredArtifact {
            identity: checkpoint::package_identity(&[43; 32]),
            digest: [43; 32],
        },
    ];
    SnapshotMetadata {
        tenant: "operator-metadata-only".into(),
        operation_id: "checkpoint-source".into(),
        operator_id: "operator".into(),
        runtime_digest: [45; 32],
        decoder_formats: vec![retained_format()],
        required_artifacts: artifacts,
    }
}

impl Fixture {
    pub fn current(&self) -> NamespaceMigrationView {
        NamespaceMigrationView::capture(
            &self.store.snapshot().unwrap(),
            &self.request.scope.tenant,
            &self.request.scope.namespace,
        )
        .unwrap()
    }

    pub fn state_row(&self) -> RowMutation {
        let view = self.store.snapshot().unwrap();
        let page = view
            .scan_after(Family::State, b"state-v1\0", None, 2, 4096)
            .unwrap();
        assert_eq!(page.rows.len(), 1);
        let (key, bytes) = page.rows.into_iter().next().unwrap();
        RowMutation {
            key,
            value: Some(bytes),
        }
    }

    pub fn cell(&self) -> ObservedCell {
        let row = self.state_row();
        crate::session::inspect_cell(
            &self.store.snapshot().unwrap(),
            &row.key,
            row.value.as_deref().unwrap(),
        )
        .unwrap()
    }

    pub fn progress_bytes(&self) -> Vec<u8> {
        self.store
            .snapshot()
            .unwrap()
            .get(&self.request.progress_key().unwrap())
            .unwrap()
            .unwrap()
    }

    pub fn export(&self, metadata: SnapshotMetadata) -> Vec<u8> {
        let mut archive = Vec::new();
        let required = metadata.required_artifacts.clone();
        export_snapshot(
            &self.store,
            metadata,
            &mut archive,
            deadline(),
            |view| self.closure(view, required),
            |_| Ok(()),
        )
        .unwrap();
        archive
    }

    pub fn refresh_checkpoint_request(&mut self) {
        let view = self.store.snapshot().unwrap();
        let receipt =
            inspect_snapshot(&mut Cursor::new(&self.archive), deadline(), |key, bytes| {
                row(&view, key, bytes)
            })
            .unwrap();
        self.inputs.request.checkpoint_digest = receipt.snapshot_digest;
        self.inputs.request.checkpoint_manifest_digest = receipt.manifest_digest;
    }

    pub fn checkpoint(
        &self,
        view: &ReadView,
    ) -> Result<VerifiedMigrationCheckpoint, MigrationError> {
        VerifiedMigrationCheckpoint::inspect(
            view,
            &mut Cursor::new(&self.archive),
            deadline(),
            |key, bytes| row(view, key, bytes),
            |view| {
                self.closure(view, self.metadata.required_artifacts.clone())
                    .map_err(MigrationError::source)
            },
            |_| Ok(()),
        )
    }

    pub fn prepare(
        &self,
        view: &ReadView,
        phase: MigrationPhase,
    ) -> Result<AggregateMigrationPlan, MigrationError> {
        AggregateMigrationPlan::prepare(
            view,
            &self.request,
            &self.checkpoint(view)?,
            &self.schema,
            (self.recipe, phase),
            deadline(),
            |_, _, _| Ok(()),
        )
    }

    pub fn apply(&self, phase: MigrationPhase) -> Receipt {
        let view = self.store.snapshot().unwrap();
        let plan = self.prepare(&view, phase).unwrap();
        let (batch, progress, action) = plan.into_parts();
        drop(view);
        self.store
            .apply_fenced(batch, || Ok::<(), StoreError>(()))
            .unwrap();
        Receipt { action, progress }
    }

    pub fn reopen(&mut self) {
        // Swap only fixture engines: close the actual old handle before reopen.
        let other = tempfile::tempdir().unwrap();
        let replacement = open(other.path(), true);
        let old = std::mem::replace(&mut self.store, replacement);
        drop(old);
        self.store = open(self.root.path(), false);
    }

    pub fn require_census(&self) {
        let view = self.store.snapshot().unwrap();
        let quota = self.quota.as_ref().unwrap();
        let mut census = TenantCensus::capture(
            &view,
            std::slice::from_ref(quota),
            GlobalMetadataAllowance {
                rows: 64,
                bytes: 256 * 1024,
            },
            deadline(),
        )
        .unwrap();
        visit_view(&view, deadline(), |_, key, bytes| {
            census.observe(
                key,
                bytes,
                crate::tenant::census_contribution(&view, key, bytes)?,
            )
        })
        .unwrap();
        census.finish().unwrap();
    }

    pub fn closure(
        &self,
        view: &ReadView,
        required: Vec<RequiredArtifact>,
    ) -> Result<SnapshotClosure, StoreError> {
        closure(view, required)
    }
}

pub(crate) fn closure(
    view: &ReadView,
    required: Vec<RequiredArtifact>,
) -> Result<SnapshotClosure, StoreError> {
    let mut inventory = RetainedInventory::default();
    visit_view(view, deadline(), |_, key, bytes| {
        row(view, key, bytes)?;
        if key.key.starts_with(PROGRESS_PREFIX) {
            let progress = AggregateMigrationProgress::decode(bytes)?;
            inventory
                .observe(
                    retained_format(),
                    RetainedCount {
                        rows: 1,
                        bytes: crate::tenant::row_charge(key, bytes)?,
                        unresolved: u64::from(!progress.completed()),
                    },
                )
                .map_err(|_| StoreError::Corrupt)?;
        }
        if key.key.starts_with(crate::recovery::resume::RECEIPT_PREFIX) {
            inventory
                .observe(
                    crate::recovery::resume::retained_format(),
                    RetainedCount {
                        rows: 1,
                        bytes: crate::tenant::row_charge(key, bytes)?,
                        unresolved: 0,
                    },
                )
                .map_err(|_| StoreError::Corrupt)?;
        }
        Ok(())
    })?;
    Ok(SnapshotClosure {
        inventory,
        required_artifacts: required,
    })
}

pub(crate) fn row(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    crate::tenant::census_contribution(view, key, bytes).map(|_| ())
}
