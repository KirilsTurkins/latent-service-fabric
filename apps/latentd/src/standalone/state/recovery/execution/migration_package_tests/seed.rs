use super::fixture::*;
use latent_core::transaction_contract::Value;
use latent_effects::{authority::EffectTime, dispatch_store::DispatchCatalog};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, StoreError},
    namespace::{
        catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
        NamespaceQuota, NamespaceTransition,
    },
    session::{StateMode, StateScope, StateSession},
    tenant::TenantQuota,
};

pub(super) fn populate(engine: &EmbeddedStore, quota: TenantQuota) -> Result<(), StoreError> {
    let view = engine.snapshot()?;
    let installed = latent_state::tenant::prepare_install(&view, &[quota])?;
    drop(view);
    installed
        .publish(engine, || Ok::<_, StoreError>(()))
        .unwrap();
    DispatchCatalog::begin_exclusive_epoch(
        engine,
        EffectTime {
            unix_millis: 1_100_000,
            continuity_proven: true,
        },
        None,
    )
    .unwrap();
    let catalog = NamespaceCatalog::new();
    let tenant = TenantId("examples".into());
    let namespace = latent_core::StateNamespaceId("transactional-aggregate".into());
    let v1 = latent_state::namespace::compatibility::SchemaId::from_definition(
        super::super::super::profile::V1,
    )
    .unwrap();
    let created = catalog
        .prepare(
            engine,
            NamespaceOperationContext {
                tenant: tenant.clone(),
                actor: "operator".into(),
                operation_id: "create".into(),
            },
            &NamespaceMutation::Create {
                id: namespace.clone(),
                state_schema: v1.as_str().into(),
                quota: NamespaceQuota::default(),
            },
            0,
        )
        .unwrap();
    engine.apply(created.batch)?;
    let view = engine.snapshot()?;
    let mut session = StateSession::open(
        &view,
        StateScope {
            tenant: tenant.clone(),
            namespace: namespace.clone(),
            incarnation: 1,
            state_schema: v1.as_str().into(),
            entity: None,
            mode: StateMode::Command,
        },
        Default::default(),
        |_, _| Ok(()),
    )
    .unwrap();
    session
        .put(
            &view,
            b"aggregate/count".to_vec(),
            Value {
                bytes: 37u64.to_le_bytes().to_vec(),
                media_type: "application/vnd.lsf.aggregate-v1".into(),
                metadata: vec![],
            },
            |_, _| Ok(()),
        )
        .unwrap();
    let sealed = session.seal(&view, |_, _| Ok(())).unwrap();
    let pins = sealed.pins();
    let mut batch = AtomicBatch::default();
    sealed.append_to(&mut batch, pins).unwrap();
    drop(view);
    engine.apply(batch)?;
    let current = catalog
        .inspect(engine, &tenant, &namespace)
        .unwrap()
        .unwrap();
    let quiesced = catalog
        .prepare(
            engine,
            NamespaceOperationContext {
                tenant,
                actor: "operator".into(),
                operation_id: "quiesce".into(),
            },
            &NamespaceMutation::Transition {
                id: namespace,
                expected: current.version,
                action: NamespaceTransition::Quiesce,
            },
            0,
        )
        .unwrap();
    engine.apply(quiesced.batch)
}
