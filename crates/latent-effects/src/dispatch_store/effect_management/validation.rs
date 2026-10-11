use latent_state::embedded::{Family, ReadView, RowKey, StoreError};
use latent_state::reservation::{LogicalReservation, KEY_PREFIX};

use super::{
    codec, EffectManagementCatalog, EffectManagementError, EffectManagementPlan,
    EffectManagementReceipt, EffectManagementRequest, COUNTER_PREFIX, PLAN_PREFIX, RECEIPT_PREFIX,
    RESERVATION_OWNER_PREFIX, RESERVED_DISPOSITION_BYTES, SLOT_PREFIX,
};
use crate::dispatch::EffectRecord;
use crate::dispatch_store::{effect_row_key, storage_error};

const COUNTER_FORMAT: &[u8] = b"LEMC\x01";
// One counter and each original slot/plan/receipt/reservation observation.
// All 128 accepted slots fit the original 1024-row engine batch ceiling.
const MAXIMUM_RETAINED_ROWS: usize = 1 + 4 * 128;

pub(super) fn encode_counter(value: u32) -> Result<Vec<u8>, StoreError> {
    if !(1..=128).contains(&value) {
        return Err(StoreError::Invalid);
    }
    let mut bytes = COUNTER_FORMAT.to_vec();
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(bytes)
}
pub(super) fn decode_counter(bytes: &[u8]) -> Result<u32, StoreError> {
    if !bytes.starts_with(COUNTER_FORMAT) {
        return Err(StoreError::UnsupportedFormat);
    }
    if bytes.len() != 9 {
        return Err(StoreError::Corrupt);
    }
    let value = u32::from_be_bytes(bytes[5..].try_into().map_err(|_| StoreError::Corrupt)?);
    encode_counter(value).map_err(|_| StoreError::Corrupt)?;
    Ok(value)
}

impl EffectManagementCatalog {
    /// Actual original row ownership after the same closed plan/receipt/link
    /// validators. The shared LCU2 ledger covers these optional metadata bytes.
    pub fn tenant_census_contribution(
        view: &ReadView,
        key: &RowKey,
        bytes: &[u8],
    ) -> Result<latent_state::tenant::TenantCensusContribution, StoreError> {
        let effect = linked_effect(view, key, bytes)?;
        let record_key = effect_row_key(&effect)?;
        let record = EffectRecord::decode(&view.get(&record_key)?.ok_or(StoreError::Corrupt)?)
            .map_err(storage_error)?;
        let authority = record.authority().map_err(storage_error)?;
        let scope = authority.scope();
        let tenant = latent_core::TenantId(scope.tenant.clone());
        let ledger_key = latent_state::reservation::namespace_ledger_key(
            &tenant,
            &latent_core::StateNamespaceId(scope.namespace.clone()),
            scope.incarnation,
        )?;
        if !latent_state::reservation::NamespaceLedger::decode(
            &view
                .get_bounded(&ledger_key, latent_state::reservation::QUOTA_BYTES)?
                .ok_or(StoreError::Corrupt)?,
        )?
        .is_accounted()
        {
            return Err(StoreError::UnsupportedFormat);
        }
        Ok(latent_state::tenant::TenantCensusContribution::Covered { tenant })
    }

    /// Finite, exact optional metadata closure. An unfinished plan remains a
    /// protection even after its deadline; elapsed time proves no physical
    /// management-owner retirement. Large closures refuse without mutation.
    pub(crate) fn retained_rows(
        view: &ReadView,
        effect: &str,
    ) -> Result<(Vec<latent_state::embedded::ExpectedRow>, u64), StoreError> {
        use latent_state::embedded::ExpectedRow;
        let identity = crate::effect_identity::parse(effect).map_err(storage_error)?;
        let counter_key = codec::row(COUNTER_PREFIX, &identity);
        let counter = view.get_bounded(&counter_key, 9)?;
        let mut rows = vec![ExpectedRow {
            key: counter_key.clone(),
            value: counter.clone(),
        }];
        let Some(counter) = counter else {
            return Ok((rows, 0));
        };
        validate_counter(view, &counter_key, &counter)?;
        let mut total = super::accounting::charge(&counter_key, &counter)?;
        let mut encoded = counter_key.key.len() + counter.len();
        for sequence in 1..=decode_counter(&counter)? {
            let slot_key = codec::slot(&identity, sequence);
            let slot = view
                .get_bounded(&slot_key, 32)?
                .ok_or(StoreError::Corrupt)?;
            let operation = slot
                .as_slice()
                .try_into()
                .map_err(|_| StoreError::Corrupt)?;
            let plan_key = codec::row(PLAN_PREFIX, &operation);
            let plan = view
                .get_bounded(&plan_key, super::MAXIMUM_PLAN_BYTES)?
                .ok_or(StoreError::Corrupt)?;
            validate_plan(view, &plan_key, &plan)?;
            let receipt_key = codec::row(RECEIPT_PREFIX, &operation);
            let receipt = view
                .get_bounded(&receipt_key, super::MAXIMUM_RECEIPT_BYTES)?
                .ok_or(StoreError::Capacity)?;
            validate_receipt(view, &receipt_key, &receipt)?;
            let reservation_key = codec::reservation(&operation)?;
            if view.get_bounded(&reservation_key, 20)?.is_some() {
                return Err(StoreError::Corrupt);
            }
            for (key, bytes) in [(slot_key, slot), (plan_key, plan), (receipt_key, receipt)] {
                total = total
                    .checked_add(super::accounting::charge(&key, &bytes)?)
                    .ok_or(StoreError::Capacity)?;
                encoded = encoded
                    .checked_add(key.key.len() + bytes.len())
                    .ok_or(StoreError::Capacity)?;
                if rows.len() >= MAXIMUM_RETAINED_ROWS || encoded > 4 * 1024 * 1024 {
                    return Err(StoreError::Capacity);
                }
                rows.push(ExpectedRow {
                    key,
                    value: Some(bytes),
                });
            }
            if rows.len() >= MAXIMUM_RETAINED_ROWS {
                return Err(StoreError::Capacity);
            }
            rows.push(ExpectedRow {
                key: reservation_key,
                value: None,
            });
        }
        Ok((rows, total))
    }

    #[must_use]
    pub fn owns_row(key: &RowKey) -> bool {
        key.family == Family::Maintenance
            && ([PLAN_PREFIX, RECEIPT_PREFIX, COUNTER_PREFIX, SLOT_PREFIX]
                .iter()
                .any(|prefix| key.key.starts_with(prefix))
                || key.key.starts_with(&reservation_prefix()))
    }

    pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        if key.family != Family::Maintenance {
            return Err(StoreError::UnsupportedFormat);
        }
        if key.key.starts_with(PLAN_PREFIX) {
            let operation = identity(key, PLAN_PREFIX)?;
            let plan = EffectManagementPlan::decode(bytes).map_err(codec::storage)?;
            if codec::operation(plan.request()) != operation {
                return Err(StoreError::Corrupt);
            }
        } else if key.key.starts_with(RECEIPT_PREFIX) {
            let operation = identity(key, RECEIPT_PREFIX)?;
            let receipt = EffectManagementReceipt::decode(bytes).map_err(codec::storage)?;
            if codec::operation(receipt.plan.request()) != operation {
                return Err(StoreError::Corrupt);
            }
        } else if key.key.starts_with(COUNTER_PREFIX) {
            identity(key, COUNTER_PREFIX)?;
            decode_counter(bytes)?;
        } else if key.key.starts_with(SLOT_PREFIX) {
            slot_identity(key)?;
            if bytes.len() != 32 {
                return Err(StoreError::Corrupt);
            }
        } else if key.key.starts_with(&reservation_prefix()) {
            identity(key, &reservation_prefix())?;
            let reservation = LogicalReservation::decode(bytes)?;
            if reservation.bytes != RESERVED_DISPOSITION_BYTES
                || !(1..=128).contains(&reservation.generation)
            {
                return Err(StoreError::Corrupt);
            }
        } else {
            return Err(StoreError::UnsupportedFormat);
        }
        Ok(())
    }

    pub fn validate_view(view: &ReadView) -> Result<(), StoreError> {
        walk(view, PLAN_PREFIX, |key, bytes| {
            validate_plan(view, key, bytes)
        })?;
        walk(view, RECEIPT_PREFIX, |key, bytes| {
            validate_receipt(view, key, bytes)
        })?;
        walk(view, COUNTER_PREFIX, |key, bytes| {
            validate_counter(view, key, bytes)
        })?;
        walk(view, SLOT_PREFIX, |key, bytes| {
            Self::validate_row(key, bytes)?;
            let (effect, sequence) = slot_identity(key)?;
            let operation = bytes.try_into().map_err(|_| StoreError::Corrupt)?;
            let plan = load_plan(view, &operation)?;
            if crate::effect_identity::parse(&plan.request.0.effect).map_err(storage_error)?
                != effect
                || plan.sequence != sequence
            {
                return Err(StoreError::Corrupt);
            }
            Ok(())
        })?;
        walk(view, &reservation_prefix(), |key, bytes| {
            Self::validate_row(key, bytes)?;
            let operation = identity(key, &reservation_prefix())?;
            let plan = load_plan(view, &operation)?;
            if LogicalReservation::decode(bytes)?.generation != u64::from(plan.sequence)
                || view.get(&codec::row(RECEIPT_PREFIX, &operation))?.is_some()
            {
                return Err(StoreError::Corrupt);
            }
            Ok(())
        })
    }

    pub(crate) fn validate_effect(
        view: &ReadView,
        record: &EffectRecord,
    ) -> Result<(), StoreError> {
        let Some(stamp) = record.management() else {
            return Ok(());
        };
        let operation =
            crate::effect_identity::parse(stamp.operation_digest()).map_err(storage_error)?;
        let receipt_key = codec::row(RECEIPT_PREFIX, &operation);
        let receipt =
            EffectManagementReceipt::decode(&view.get(&receipt_key)?.ok_or(StoreError::Corrupt)?)
                .map_err(codec::storage)?;
        check_target(record, receipt.plan.request()).map_err(codec::storage)?;
        if receipt.plan.sequence != stamp.sequence()
            || receipt.fact != stamp.fact()
            || receipt.provider_receipt.as_deref() != stamp.provider_receipt()
            || receipt.provider_observed_at_millis != stamp.provider_observed_at_millis()
            || receipt.plan.original_attempt.as_ref() != stamp.original_attempt()
            || receipt.completed_at_millis != stamp.observed_at_millis()
        {
            return Err(StoreError::Corrupt);
        }
        let owner = view
            .get(&crate::dispatch_store::codec::OwnerRecord::key())?
            .ok_or(StoreError::Corrupt)?;
        if crate::dispatch_store::codec::OwnerRecord::decode(&owner)?.clock_floor
            < stamp.observed_at_millis()
        {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
}

fn linked_effect(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<String, StoreError> {
    EffectManagementCatalog::validate_row(key, bytes)?;
    let request = if key.key.starts_with(PLAN_PREFIX) {
        validate_plan(view, key, bytes)?;
        EffectManagementPlan::decode(bytes)
            .map_err(codec::storage)?
            .request
    } else if key.key.starts_with(RECEIPT_PREFIX) {
        validate_receipt(view, key, bytes)?;
        EffectManagementReceipt::decode(bytes)
            .map_err(codec::storage)?
            .plan
            .request
    } else if key.key.starts_with(COUNTER_PREFIX) {
        validate_counter(view, key, bytes)?;
        return Ok(crate::effect_identity::render(&identity(
            key,
            COUNTER_PREFIX,
        )?));
    } else if key.key.starts_with(SLOT_PREFIX) {
        let (effect, sequence) = slot_identity(key)?;
        let operation = bytes.try_into().map_err(|_| StoreError::Corrupt)?;
        let plan = load_plan(view, &operation)?;
        if plan.sequence != sequence
            || crate::effect_identity::parse(&plan.request.0.effect).map_err(storage_error)?
                != effect
        {
            return Err(StoreError::Corrupt);
        }
        validate_plan(
            view,
            &codec::row(PLAN_PREFIX, &operation),
            &plan.encode().map_err(codec::storage)?,
        )?;
        plan.request
    } else {
        let operation = identity(key, &reservation_prefix())?;
        let plan = load_plan(view, &operation)?;
        if LogicalReservation::decode(bytes)?.generation != u64::from(plan.sequence)
            || view.get(&codec::row(RECEIPT_PREFIX, &operation))?.is_some()
        {
            return Err(StoreError::Corrupt);
        }
        validate_plan(
            view,
            &codec::row(PLAN_PREFIX, &operation),
            &plan.encode().map_err(codec::storage)?,
        )?;
        plan.request
    };
    let record = load_effect(view, &request)?;
    check_target(&record, &request).map_err(codec::storage)?;
    Ok(request.input().effect.clone())
}

fn validate_plan(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    EffectManagementCatalog::validate_row(key, bytes)?;
    let plan = EffectManagementPlan::decode(bytes).map_err(codec::storage)?;
    let effect = crate::effect_identity::parse(&plan.request.0.effect).map_err(storage_error)?;
    let record = load_effect(view, plan.request())?;
    check_target(&record, plan.request()).map_err(codec::storage)?;
    if plan.original_attempt.as_ref().is_some_and(|attempt| {
        attempt.attempt() > record.attempts()
            || attempt.owner_epoch() > record.owner_epoch()
            || attempt.claim_generation() > record.claim_generation()
    }) {
        return Err(StoreError::Corrupt);
    }
    let counter = view
        .get(&codec::row(COUNTER_PREFIX, &effect))?
        .ok_or(StoreError::Corrupt)?;
    if decode_counter(&counter)? < plan.sequence
        || view.get(&codec::slot(&effect, plan.sequence))?
            != Some(codec::operation(plan.request()).to_vec())
    {
        return Err(StoreError::Corrupt);
    }
    let operation = codec::operation(plan.request());
    let reservation = view.get(&codec::reservation(&operation)?)?;
    let receipt = view.get(&codec::row(RECEIPT_PREFIX, &operation))?;
    match receipt {
        Some(bytes) => {
            let receipt = EffectManagementReceipt::decode(&bytes).map_err(codec::storage)?;
            if receipt.plan != plan || reservation.is_some() {
                return Err(StoreError::Corrupt);
            }
        }
        None => {
            if LogicalReservation::decode(reservation.as_deref().ok_or(StoreError::Corrupt)?)?
                != (LogicalReservation {
                    generation: u64::from(plan.sequence),
                    bytes: RESERVED_DISPOSITION_BYTES,
                })
            {
                return Err(StoreError::Corrupt);
            }
        }
    }
    Ok(())
}
fn validate_receipt(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    EffectManagementCatalog::validate_row(key, bytes)?;
    let operation = identity(key, RECEIPT_PREFIX)?;
    let receipt = EffectManagementReceipt::decode(bytes).map_err(codec::storage)?;
    if load_plan(view, &operation)? != receipt.plan
        || view.get(&codec::reservation(&operation)?)?.is_some()
    {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}
fn validate_counter(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    EffectManagementCatalog::validate_row(key, bytes)?;
    let effect = identity(key, COUNTER_PREFIX)?;
    let record_key = effect_row_key(&crate::effect_identity::render(&effect))?;
    let record = EffectRecord::decode(&view.get(&record_key)?.ok_or(StoreError::Corrupt)?)
        .map_err(storage_error)?;
    let count = decode_counter(bytes)?;
    if record
        .management()
        .is_some_and(|stamp| stamp.sequence() > count)
    {
        return Err(StoreError::Corrupt);
    }
    for sequence in 1..=count {
        let bytes = view
            .get(&codec::slot(&effect, sequence))?
            .ok_or(StoreError::Corrupt)?;
        let operation = bytes
            .as_slice()
            .try_into()
            .map_err(|_| StoreError::Corrupt)?;
        let plan = load_plan(view, &operation)?;
        if plan.sequence != sequence
            || plan.request.0.effect != crate::effect_identity::render(&effect)
        {
            return Err(StoreError::Corrupt);
        }
    }
    Ok(())
}
fn load_effect(
    view: &ReadView,
    request: &EffectManagementRequest,
) -> Result<EffectRecord, StoreError> {
    let key = effect_row_key(&request.0.effect)?;
    let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
    crate::dispatch_store::validate_row(&key, &bytes)?;
    EffectRecord::decode(&bytes).map_err(storage_error)
}
fn load_plan(view: &ReadView, operation: &[u8; 32]) -> Result<EffectManagementPlan, StoreError> {
    let key = codec::row(PLAN_PREFIX, operation);
    let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
    EffectManagementCatalog::validate_row(&key, &bytes)?;
    EffectManagementPlan::decode(&bytes).map_err(codec::storage)
}
fn check_target(
    record: &EffectRecord,
    request: &EffectManagementRequest,
) -> Result<(), EffectManagementError> {
    let authority = record.authority()?;
    let input = request.input();
    if authority.scope().tenant != input.actor_tenant
        || authority.scope().namespace != input.namespace
        || authority.scope().incarnation != input.incarnation
        || authority.link().command != input.command
        || authority.link().attempt != input.command_attempt
        || authority.link().caller_scope != input.caller_scope
        || authority.link().effect != input.effect
    {
        return Err(EffectManagementError::PermissionDenied);
    }
    Ok(())
}
fn identity(key: &RowKey, prefix: &[u8]) -> Result<[u8; 32], StoreError> {
    if key.key.len() != prefix.len() + 32 {
        return Err(StoreError::Corrupt);
    }
    key.key[prefix.len()..]
        .try_into()
        .map_err(|_| StoreError::Corrupt)
}
fn slot_identity(key: &RowKey) -> Result<([u8; 32], u32), StoreError> {
    if key.key.len() != SLOT_PREFIX.len() + 36 {
        return Err(StoreError::Corrupt);
    }
    let effect = key.key[SLOT_PREFIX.len()..SLOT_PREFIX.len() + 32]
        .try_into()
        .map_err(|_| StoreError::Corrupt)?;
    let sequence = u32::from_be_bytes(
        key.key[SLOT_PREFIX.len() + 32..]
            .try_into()
            .map_err(|_| StoreError::Corrupt)?,
    );
    if !(1..=128).contains(&sequence) {
        return Err(StoreError::Corrupt);
    }
    Ok((effect, sequence))
}
fn reservation_prefix() -> Vec<u8> {
    let mut prefix = KEY_PREFIX.to_vec();
    prefix.extend_from_slice(RESERVATION_OWNER_PREFIX);
    prefix
}
fn walk(
    view: &ReadView,
    prefix: &[u8],
    mut verify: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError>,
) -> Result<(), StoreError> {
    let mut cursor = None;
    loop {
        let page = view.scan_after(
            Family::Maintenance,
            prefix,
            cursor.as_deref(),
            16,
            1024 * 1024,
        )?;
        for (key, bytes) in &page.rows {
            verify(key, bytes)?;
        }
        cursor = page.resume;
        if cursor.is_none() {
            return Ok(());
        }
    }
}
