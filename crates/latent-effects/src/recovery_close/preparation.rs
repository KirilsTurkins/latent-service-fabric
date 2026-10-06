use super::{
    effect_row_key, inspect, prepare_update, row_charge, storage_error, validate_receipt_links,
    AtomicBatch, ClosePlan, CloseReceipt, CloseScope, DispatchCatalog, Disposition, DueRecord,
    EffectRecord, EffectTime, ExpectedRow, Family, PreparedClose, ReadView, RowKey, RowMutation,
    StateNamespaceId, StoreError, TenantDelta, TenantId, TenantUsage, FORMAT,
};

/// Exact row/generation/guard CAS. Caller supplies independent current operator
/// authority at the physical fence. The original guard remains paused.
pub fn prepare(
    view: &ReadView,
    plan: &ClosePlan,
    scope: &CloseScope,
    operator: &str,
    operation: &str,
    acknowledgement: [u8; 32],
    time: EffectTime,
) -> Result<PreparedClose, StoreError> {
    plan.validate()?;
    if &plan.scope != scope
        || plan.operator_id != operator
        || plan.operation_id != operation
        || plan.digest()? != acknowledgement
        || !time.continuity_proven
    {
        return Err(StoreError::Unavailable);
    }
    let key = plan.receipt_key()?;
    if let Some(bytes) = view.get(&key)? {
        return replay(view, plan, key, bytes, acknowledgement);
    }
    let original = inspect(
        view,
        scope.clone(),
        operator.into(),
        operation.into(),
        plan.effects
            .iter()
            .map(|row| row.effect_id.clone())
            .collect(),
        plan.reason.clone(),
    )?;
    if &original != plan {
        return Err(StoreError::Conflict);
    }
    let receipt = CloseReceipt {
        schema_version: FORMAT.into(),
        outcome: "closed-without-redrive".into(),
        plan: plan.clone(),
        acknowledgement,
        observed_at_millis: time.unix_millis,
    };
    let encoded = receipt.encode()?;
    let mut batch = AtomicBatch {
        expectations: vec![
            ExpectedRow {
                key: key.clone(),
                value: None,
            },
            ExpectedRow {
                key: latent_state::recovery::guard_key(),
                value: Some(plan.expected_guard.clone()),
            },
        ],
        mutations: vec![RowMutation {
            key: key.clone(),
            value: Some(encoded.clone()),
        }],
    };
    let tenant = TenantId(scope.tenant.clone());
    let namespace = StateNamespaceId(scope.namespace.clone());
    for namespace_key in [
        RowKey {
            family: Family::Namespace,
            key: latent_state::namespace::namespace_record_key(&tenant, &namespace)
                .map_err(|_| StoreError::Invalid)?,
        },
        latent_state::namespace::history::history_key(&tenant, &namespace, scope.incarnation)
            .map_err(|_| StoreError::Invalid)?,
    ] {
        batch.expectations.push(ExpectedRow {
            value: view.get(&namespace_key)?,
            key: namespace_key,
        });
    }
    append_effects(view, plan, time, &mut batch)?;
    prepare_update(
        view,
        &tenant,
        TenantDelta {
            added: TenantUsage {
                metadata_rows: 1,
                metadata_bytes: row_charge(&key, &encoded)?,
                ..TenantUsage::default()
            },
            ..TenantDelta::default()
        },
    )?
    .append_to(&mut batch)?;
    Ok(PreparedClose {
        batch,
        receipt,
        replay: false,
    })
}
fn replay(
    view: &ReadView,
    plan: &ClosePlan,
    key: RowKey,
    bytes: Vec<u8>,
    acknowledgement: [u8; 32],
) -> Result<PreparedClose, StoreError> {
    let receipt = CloseReceipt::validate_row(&key, &bytes)?;
    if &receipt.plan != plan || receipt.acknowledgement != acknowledgement {
        return Err(StoreError::Conflict);
    }
    validate_receipt_links(view, &receipt)?;
    let mut batch = AtomicBatch {
        expectations: vec![
            ExpectedRow {
                key,
                value: Some(bytes),
            },
            ExpectedRow {
                key: latent_state::recovery::guard_key(),
                value: view.get(&latent_state::recovery::guard_key())?,
            },
        ],
        mutations: vec![],
    };
    prepare_update(
        view,
        &TenantId(plan.scope.tenant.clone()),
        TenantDelta::default(),
    )?
    .append_read_expectations(&mut batch)?;
    Ok(PreparedClose {
        batch,
        receipt,
        replay: true,
    })
}
fn append_effects(
    view: &ReadView,
    plan: &ClosePlan,
    time: EffectTime,
    batch: &mut AtomicBatch,
) -> Result<(), StoreError> {
    for selected in &plan.effects {
        let row_key = effect_row_key(&selected.effect_id)?;
        let old = view.get(&row_key)?.ok_or(StoreError::Conflict)?;
        let mut record = EffectRecord::decode(&old).map_err(storage_error)?;
        let retained = DispatchCatalog::retention_rows(view, &selected.effect_id)?;
        for expected in retained.expectations {
            if expected.key != row_key
                && !batch.expectations.iter().any(|row| row.key == expected.key)
            {
                batch.expectations.push(expected);
            }
        }
        let old_disposition = record.disposition();
        if matches!(
            old_disposition,
            Disposition::Pending | Disposition::RetryScheduled
        ) {
            let authority = record.authority().map_err(storage_error)?;
            let due = DueRecord {
                due_millis: if old_disposition == Disposition::Pending {
                    authority.committed_at_millis()
                } else {
                    record.retry_at_millis()
                },
                effect: selected.effect_id.clone(),
                incarnation: plan.scope.incarnation,
                claim_generation: record.claim_generation(),
            };
            let due_key = due.key()?;
            batch.mutations.push(RowMutation {
                key: due_key,
                value: None,
            });
        }
        record
            .close_without_redrive(plan.receipt_digest()?, time)
            .map_err(storage_error)?;
        batch.expectations.push(ExpectedRow {
            key: row_key.clone(),
            value: Some(old),
        });
        batch.mutations.push(RowMutation {
            key: row_key,
            value: Some(record.encode().map_err(storage_error)?),
        });
    }
    Ok(())
}
