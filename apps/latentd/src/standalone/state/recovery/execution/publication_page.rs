//! Scoped offline inspection of the original unresolved effects.
use super::{
    awaited, protected, storage, Action, Arc, Codecs, DispatchCatalog, ProtectedStoreOwner,
};
use crate::standalone::state::recovery::request::PublicationEffectCursor;
use latent_core::{native_capacity::NativeBufferClass, PlatformError, PlatformErrorCode};
use latent_state::{embedded::StoreError, store_io::StoreIoKind};

const WORK_BYTES: u64 = 1024 * 1024;

pub(super) async fn inspect(
    store: &ProtectedStoreOwner,
    codecs: Arc<Codecs>,
) -> Result<serde_json::Value, PlatformError> {
    let memory = codecs
        .original
        .reserve_buffer(NativeBufferClass::Work, WORK_BYTES)
        .map_err(|_| super::super::capacity())?;
    let worker = Arc::clone(&codecs);
    let job = store
        .with_store_retaining(
            StoreIoKind::RecoveryRead,
            WORK_BYTES,
            Arc::clone(&codecs) as Arc<dyn std::any::Any + Send + Sync>,
            move |engine| {
                let _memory = memory;
                let view = engine.snapshot()?;
                // Invalid continuations are logical errors. Leave the store usable.
                Ok(inspect_view(&worker, &view))
            },
        )
        .map_err(protected)?;
    awaited(job, &codecs)
        .await?
        .map_err(protected)?
        .map_err(|error| {
            if error == StoreError::Conflict {
                PlatformError {
                    code: PlatformErrorCode::StateConflict,
                    message: "effect-inventory-view-changed".into(),
                    retryable: false,
                    details: Vec::new(),
                }
            } else {
                storage(error)
            }
        })
}

fn inspect_view(
    codecs: &Codecs,
    view: &latent_state::embedded::ReadView,
) -> Result<serde_json::Value, StoreError> {
    let Action::InspectPublicationEffects { cursor } = &codecs.action else {
        return Err(StoreError::Invalid);
    };
    codecs.check()?;
    let token = codecs.selected_view(view)?.view_token()?;
    let checkpoint = codecs.checkpoint.generation();
    let operation = &codecs.catalog.primary().operation;
    let publication = operation.publication().publication().as_str();
    let review = super::digest(codecs.review);
    if cursor.as_ref().is_some_and(|cursor| {
        cursor.publication != publication
            || cursor.view != token
            || cursor.checkpoint_generation != checkpoint
            || cursor.review_digest != review
    }) {
        return Err(StoreError::Conflict);
    }

    let scope = operation.target();
    let page = DispatchCatalog::publication_effect_page(
        view,
        &scope.tenant.0,
        operation.namespace(),
        operation.incarnation(),
        publication,
        cursor.as_ref().map(|cursor| cursor.after_effect.as_str()),
        &mut || codecs.check(),
    )?;
    let next_cursor = page
        .after_effect
        .map(|after_effect| PublicationEffectCursor {
            after_effect,
            publication: publication.into(),
            view: token.clone(),
            checkpoint_generation: checkpoint,
            review_digest: review,
        });
    codecs.fence("namespace-inspect", || Ok(()))?;
    Ok(serde_json::json!({
        "action": "inspect-publication-effects",
        "publication": publication,
        "namespace": operation.namespace(),
        "incarnation": operation.incarnation().to_string(),
        "view": token,
        "checkpointGeneration": checkpoint,
        "effects": page.effects,
        "nextCursor": next_cursor,
    }))
}
