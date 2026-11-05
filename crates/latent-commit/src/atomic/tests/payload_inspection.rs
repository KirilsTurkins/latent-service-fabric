//! These synthetic rows exercise read-only semantic inspection, not blob custody.
use super::*;
use latent_state::payload_references::{
    LocalPayloadIdentity, PayloadLinks, PayloadOwner, PayloadOwnerKind, PayloadReference,
    PreparedPayloadReferences,
};
use sha2::{Digest, Sha256};

#[test]
fn result_and_effect_descriptors_require_actual_attempt_format_and_bytes() {
    let (_dir, store, effects) = setup();
    let admitted = claim(&store, input("payload-inspection"));
    let view = store.snapshot().unwrap();
    let envelope = CompleteEnvelope::success(
        &view,
        admitted,
        None,
        vec![intent()],
        value(b"exact response"),
        &effects,
        time(101),
    )
    .unwrap();
    let command = confirm(envelope, &store, &effects);
    drop(view);
    let anchor = super::super::payload_links::anchor(&command).unwrap();
    let reference = |owner: PayloadOwner, bytes: &[u8]| PayloadReference {
        owner,
        payload: LocalPayloadIdentity {
            tenant: "tenant".into(),
            provider: "local".into(),
            provider_epoch: 1,
            provider_configuration: [3; 32],
            blob_namespace: "owned".into(),
            digest: Sha256::digest(bytes).into(),
            size: bytes.len() as u64,
            media_type: "application/octet-stream".into(),
        },
    };
    let result = reference(anchor.clone(), b"exact response");
    let effect = reference(
        PayloadOwner {
            kind: PayloadOwnerKind::Effect,
            identity: command.effect_ids()[0].0,
            format: "lsf-value-v1".into(),
            ..anchor.clone()
        },
        b"updated",
    );
    let links = PayloadLinks {
        anchor,
        references: vec![result.clone(), effect.clone()],
    };
    let view = store.snapshot().unwrap();
    let mut plan = PreparedPayloadReferences::prepare(
        &view,
        &[(None, Some(result.clone())), (None, Some(effect.clone()))],
    )
    .unwrap();
    plan.replace_links(&view, None, Some(&links)).unwrap();
    let mut batch = AtomicBatch::default();
    plan.append_to(&mut batch).unwrap();
    drop(view);
    store.apply(batch).unwrap();
    let view = store.snapshot().unwrap();
    for key in [
        result.owner_key().unwrap(),
        effect.object_key().unwrap(),
        links.row_key().unwrap(),
    ] {
        let bytes = view.get(&key).unwrap().unwrap();
        inspect_payload_reference(&view, &key, &bytes).unwrap();
    }
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: result_row_key(command.id, command.attempt),
                value: Some(b"corrupt".to_vec()),
            }],
        })
        .unwrap();
    let view = store.snapshot().unwrap();
    let key = effect.owner_key().unwrap();
    let bytes = view.get(&key).unwrap().unwrap();
    assert!(inspect_payload_reference(&view, &key, &bytes).is_err());
}

#[test]
fn rejection_reference_rejects_consistent_catalogue_with_wrong_content_digest() {
    let (_dir, store, effects) = setup();
    let admitted = claim(&store, input("rejection-reference"));
    let view = store.snapshot().unwrap();
    let envelope = CompleteEnvelope::rejection(
        &view,
        admitted,
        "declined".into(),
        value(b"rejected"),
        time(101),
    )
    .unwrap();
    let command = confirm(envelope, &store, &effects);
    drop(view);
    let anchor = super::super::payload_links::anchor(&command).unwrap();
    let reference = PayloadReference {
        owner: anchor.clone(),
        payload: LocalPayloadIdentity {
            tenant: "tenant".into(),
            provider: "local".into(),
            provider_epoch: 1,
            provider_configuration: [3; 32],
            blob_namespace: "owned".into(),
            digest: Sha256::digest(b"different").into(),
            size: 8,
            media_type: "application/octet-stream".into(),
        },
    };
    let links = PayloadLinks {
        anchor,
        references: vec![reference.clone()],
    };
    let view = store.snapshot().unwrap();
    let mut plan =
        PreparedPayloadReferences::prepare(&view, &[(None, Some(reference.clone()))]).unwrap();
    plan.replace_links(&view, None, Some(&links)).unwrap();
    let mut batch = AtomicBatch::default();
    plan.append_to(&mut batch).unwrap();
    drop(view);
    store.apply(batch).unwrap();
    let view = store.snapshot().unwrap();
    let key = reference.owner_key().unwrap();
    let bytes = view.get(&key).unwrap().unwrap();
    assert_eq!(
        inspect_payload_reference(&view, &key, &bytes),
        Err(AtomicError::Corrupt)
    );
}
