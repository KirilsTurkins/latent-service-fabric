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

#[test]
fn response_expiry_releases_only_its_shared_reference_and_keeps_effect_linkage() {
    exercise_result_expiry(false);
}

#[test]
fn reviewed_terminalization_also_releases_only_the_response_reference() {
    exercise_result_expiry(true);
}

fn exercise_result_expiry(reviewed: bool) {
    use latent_state::embedded::ExpectedRow;
    let (_dir, store, effects) = accounted::setup(8);
    let admitted = claim(&store, input("shared-retention"));
    let view = store.snapshot().unwrap();
    let envelope = CompleteEnvelope::success(
        &view,
        admitted,
        None,
        vec![intent()],
        value(b"updated"),
        &effects,
        time(101),
    )
    .unwrap();
    let command = confirm(envelope, &store, &effects);
    drop(view);
    let anchor = super::super::payload_links::anchor(&command).unwrap();
    let physical = LocalPayloadIdentity {
        tenant: "tenant".into(),
        provider: "local".into(),
        provider_epoch: 1,
        provider_configuration: [3; 32],
        blob_namespace: "owned".into(),
        digest: Sha256::digest(b"updated").into(),
        size: 7,
        media_type: "application/octet-stream".into(),
    };
    let result = PayloadReference {
        owner: anchor.clone(),
        payload: physical.clone(),
    };
    let effect = PayloadReference {
        owner: PayloadOwner {
            kind: PayloadOwnerKind::Effect,
            identity: command.effect_ids()[0].0,
            format: "lsf-value-v1".into(),
            ..anchor.clone()
        },
        payload: physical.clone(),
    };
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
    let (mut usage, usage_key, previous_usage) = writer::Usage::read(&view, &command.key).unwrap();
    usage.payload_bytes += 14;
    batch.expectations.push(ExpectedRow {
        key: usage_key.clone(),
        value: previous_usage,
    });
    batch.mutations.push(RowMutation {
        key: usage_key,
        value: Some(usage.encode().unwrap()),
    });
    let namespace_key = namespace_key();
    let previous_namespace = view.get(&namespace_key).unwrap().unwrap();
    let mut namespace = NamespaceRecord::decode(&previous_namespace).unwrap();
    namespace.pins.payload_references += 2;
    batch.expectations.push(ExpectedRow {
        key: namespace_key.clone(),
        value: Some(previous_namespace),
    });
    batch.mutations.push(RowMutation {
        key: namespace_key,
        value: Some(namespace.encode().unwrap()),
    });
    super::super::accounting::apply(&view, &TenantId("tenant".into()), &mut batch).unwrap();
    drop(view);
    store.apply(batch).unwrap();
    let before = accounted::usage(&store);
    let owner = ResultMaintenanceOwner::default();
    let clock = |now| MaintenanceClock {
        time: time(now),
        boot: [7; 32],
        monotonic_millis: now,
    };
    owner.anchor(&store, None, clock(101), |_| Ok(())).unwrap();
    let request = RetentionRequest {
        key: command.key.clone(),
        expected_command_digest: RetentionRequest::command_digest(&command).unwrap(),
        actor: "operator".into(),
        operation_id: "review-1".into(),
        policy: "retention".into(),
        retain_until_millis: 2300,
        inbox_expires_at_millis: None,
    };
    let mut calls = 0;
    let rejected = if reviewed {
        owner
            .terminalize(&store, &request, clock(2200), |_, _, _| {
                calls += 1;
                if calls == 3 {
                    Err(AtomicError::PermissionDenied)
                } else {
                    Ok(())
                }
            })
            .map(|_| ())
    } else {
        owner
            .step(&store, clock(1100), |_| {
                calls += 1;
                if calls == 3 {
                    Err(AtomicError::PermissionDenied)
                } else {
                    Ok(())
                }
            })
            .map(|_| ())
    };
    assert!(matches!(rejected, Err(AtomicError::PermissionDenied)));
    let view = store.snapshot().unwrap();
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(2)
    );
    assert!(view.get(&result.owner_key().unwrap()).unwrap().is_some());
    drop(view);
    if reviewed {
        owner
            .terminalize(&store, &request, clock(2200), |_, _, _| Ok(()))
            .unwrap();
    } else {
        owner.step(&store, clock(1100), |_| Ok(())).unwrap();
    }
    let view = store.snapshot().unwrap();
    assert!(view.get(&result.owner_key().unwrap()).unwrap().is_none());
    let bytes = view.get(&effect.owner_key().unwrap()).unwrap().unwrap();
    inspect_payload_reference(&view, &effect.owner_key().unwrap(), &bytes).unwrap();
    assert_eq!(
        latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
        Some(1)
    );
    assert_eq!(
        writer::Usage::read(&view, &command.key)
            .unwrap()
            .0
            .payload_bytes,
        usage.payload_bytes - 7
    );
    drop(view);
    let after = accounted::usage(&store);
    assert_eq!(after.usage.payload_bytes, before.usage.payload_bytes - 7);
    assert!(after.usage.metadata_rows < before.usage.metadata_rows);
    super::census::census(&store).unwrap();
    if reviewed {
        owner
            .purge(&store, &request, clock(2300), |_, _, _| Ok(()))
            .unwrap();
        let view = store.snapshot().unwrap();
        assert!(view.get(&effect.owner_key().unwrap()).unwrap().is_none());
        assert_eq!(
            latent_state::payload_references::physical_owner_count(&view, &physical).unwrap(),
            Some(0)
        );
        drop(view);
        super::census::census(&store).unwrap();
    }
}

#[test]
fn coherent_inventory_resolves_state_owner_to_exact_current_cell() {
    use latent_state::{embedded::ExpectedRow, payload_references::StatePayloadLink};
    let (_dir, store, effects) = accounted::setup(8);
    let admitted = claim(&store, input("state-payload-inventory"));
    let view = store.snapshot().unwrap();
    let staged = stage(&view);
    let command = confirm(
        CompleteEnvelope::success(
            &view,
            admitted,
            Some(staged),
            vec![],
            value(b"ok"),
            &effects,
            time(101),
        )
        .unwrap(),
        &store,
        &effects,
    );
    drop(view);
    let view = store.snapshot().unwrap();
    let page = view
        .scan_after(Family::State, b"state-v1\0", None, 1, 4096)
        .unwrap();
    let cell_key = page.rows[0].0.clone();
    let (owner, cell_value) =
        latent_state::session::describe_state_payload_owner(&view, &cell_key).unwrap();
    let reference = PayloadReference {
        owner,
        payload: LocalPayloadIdentity {
            tenant: "tenant".into(),
            provider: "local".into(),
            provider_epoch: 1,
            provider_configuration: [3; 32],
            blob_namespace: "owned".into(),
            digest: Sha256::digest(&cell_value.bytes).into(),
            size: cell_value.bytes.len() as u64,
            media_type: cell_value.media_type,
        },
    };
    let link = StatePayloadLink {
        reference: reference.clone(),
        cell_key: cell_key.clone(),
    };
    let mut plan = PreparedPayloadReferences::prepare(&view, &[(None, Some(reference))]).unwrap();
    plan.replace_state_link(&view, None, Some(&link)).unwrap();
    let mut batch = AtomicBatch::default();
    plan.append_to(&mut batch).unwrap();
    let (mut usage, usage_key, original_usage) = writer::Usage::read(&view, &command.key).unwrap();
    usage.payload_bytes += 8;
    batch.expectations.push(ExpectedRow {
        key: usage_key.clone(),
        value: original_usage,
    });
    batch.mutations.push(RowMutation {
        key: usage_key,
        value: Some(usage.encode().unwrap()),
    });
    let ns_key = namespace_key();
    let original_namespace = view.get(&ns_key).unwrap().unwrap();
    let mut namespace = NamespaceRecord::decode(&original_namespace).unwrap();
    namespace.pins.payload_references += 1;
    batch.expectations.push(ExpectedRow {
        key: ns_key.clone(),
        value: Some(original_namespace),
    });
    batch.mutations.push(RowMutation {
        key: ns_key,
        value: Some(namespace.encode().unwrap()),
    });
    super::super::accounting::apply(&view, &TenantId("tenant".into()), &mut batch).unwrap();
    drop(view);
    store.apply(batch).unwrap();
    super::census::census(&store).unwrap();

    let next = claim(&store, input("state-payload-replacement"));
    let view = store.snapshot().unwrap();
    let scope = StateScope {
        tenant: TenantId("tenant".into()),
        namespace: StateNamespaceId("aggregate".into()),
        incarnation: 1,
        state_schema: schema(),
        entity: None,
        mode: StateMode::Command,
    };
    let mut session =
        StateSession::open(&view, scope, SessionLimits::default(), state_permission).unwrap();
    session
        .put(
            &view,
            b"aggregate/count".to_vec(),
            value(b"replacement"),
            state_permission,
        )
        .unwrap();
    let staged = session.seal(&view, state_permission).unwrap();
    assert!(matches!(
        CompleteEnvelope::success(
            &view,
            next,
            Some(staged),
            vec![],
            value(b"ok"),
            &effects,
            time(102)
        ),
        Err(AtomicError::UnsupportedFormat)
    ));
    drop(view);

    let next = claim(&store, input("state-payload-delete"));
    let view = store.snapshot().unwrap();
    let scope = StateScope {
        tenant: TenantId("tenant".into()),
        namespace: StateNamespaceId("aggregate".into()),
        incarnation: 1,
        state_schema: schema(),
        entity: None,
        mode: StateMode::Command,
    };
    let mut session =
        StateSession::open(&view, scope, SessionLimits::default(), state_permission).unwrap();
    session
        .delete(&view, b"aggregate/count".to_vec(), state_permission)
        .unwrap();
    let staged = session.seal(&view, state_permission).unwrap();
    assert!(matches!(
        CompleteEnvelope::success(
            &view,
            next,
            Some(staged),
            vec![],
            value(b"ok"),
            &effects,
            time(102)
        ),
        Err(AtomicError::UnsupportedFormat)
    ));
    drop(view);

    let view = store.snapshot().unwrap();
    let scope = StateScope {
        tenant: TenantId("tenant".into()),
        namespace: StateNamespaceId("aggregate".into()),
        incarnation: 1,
        state_schema: schema(),
        entity: None,
        mode: StateMode::Command,
    };
    let mut session =
        StateSession::open(&view, scope, SessionLimits::default(), state_permission).unwrap();
    session
        .put(
            &view,
            b"aggregate/count".to_vec(),
            value(b"replacement"),
            state_permission,
        )
        .unwrap();
    let plan = session.seal(&view, state_permission).unwrap();
    let mut batch = AtomicBatch::default();
    let pins = plan.pins();
    plan.append_to(&mut batch, pins).unwrap();
    drop(view);
    store.apply(batch).unwrap();
    assert!(super::census::census(&store).is_err());
}
