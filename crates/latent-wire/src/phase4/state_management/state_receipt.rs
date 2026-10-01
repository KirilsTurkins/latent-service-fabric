//! Bounded immutable outcomes in the existing protected namespace family.
//! Historical operation bytes never replace current inspection permission.
use super::{c, contract, inspection, response};
use latent_core::TenantId;
use latent_state::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::{
        catalog::{NamespaceCatalog, NamespaceOperationContext},
        NamespaceRecord, NamespaceStatus,
    },
    session::{version::ViewIdentity, StateScope},
};
use prost::Message;
use sha2::{Digest, Sha256};

const PREFIX: &[u8] = b"ns-state-op-v1\0";
const MAGIC: &[u8] = b"lsf-state-operation-v1\0";
pub(super) const MAX_BYTES: usize = 8192;

pub(super) struct Receipt {
    pub request: c::MutateStateRequest,
    pub public: c::StateOperationReceipt,
    pub after: NamespaceRecord,
}

pub(super) fn key(context: &NamespaceOperationContext) -> RowKey {
    let mut hash = Sha256::new();
    hash.update(b"lsf-state-operation-key-v1\0");
    for value in [&context.tenant.0, &context.actor, &context.operation_id] {
        hash.update((value.len() as u64).to_le_bytes());
        hash.update(value.as_bytes());
    }
    let mut key = PREFIX.to_vec();
    key.extend_from_slice(&hash.finalize());
    RowKey {
        family: Family::Namespace,
        key,
    }
}

impl Receipt {
    pub fn new(
        request: c::MutateStateRequest,
        actor: String,
        after: NamespaceRecord,
        after_version: Vec<u8>,
        completed_at: u64,
    ) -> Result<Self, StoreError> {
        let public = c::StateOperationReceipt {
            operation_id: request.operation_id.clone(),
            receipt_id: receipt_id(&request, &actor, &after, completed_at)?,
            mutation: request.mutation,
            namespace: Some(response::selector(&after)),
            authenticated_operator: actor,
            before_version: request.expected_version.clone(),
            after_version,
            completed_at_unix_millis: completed_at,
            record_id: request.record_id.clone(),
            policy_digest: request.expected_policy_digest.clone(),
            disposition: c::StateOperationDisposition::Committed as i32,
        };
        let value = Self {
            request,
            public,
            after,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn context(&self) -> NamespaceOperationContext {
        NamespaceOperationContext {
            tenant: self.after.tenant.clone(),
            actor: self.public.authenticated_operator.clone(),
            operation_id: self.public.operation_id.clone(),
        }
    }

    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        let fields = [
            self.request.encode_to_vec(),
            self.public.encode_to_vec(),
            self.after.encode().map_err(inspection::native_namespace)?,
        ];
        let mut bytes = MAGIC.to_vec();
        for field in fields {
            bytes.extend_from_slice(
                &u32::try_from(field.len())
                    .map_err(|_| StoreError::Capacity)?
                    .to_le_bytes(),
            );
            bytes.extend_from_slice(&field);
            if bytes.len() > MAX_BYTES {
                return Err(StoreError::Capacity);
            }
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.len() > MAX_BYTES || !bytes.starts_with(MAGIC) {
            return Err(StoreError::Corrupt);
        }
        let mut offset = MAGIC.len();
        let mut field = || -> Result<&[u8], StoreError> {
            let length = bytes.get(offset..offset + 4).ok_or(StoreError::Corrupt)?;
            offset += 4;
            let length =
                u32::from_le_bytes(length.try_into().map_err(|_| StoreError::Corrupt)?) as usize;
            let end = offset.checked_add(length).ok_or(StoreError::Corrupt)?;
            let value = bytes.get(offset..end).ok_or(StoreError::Corrupt)?;
            offset = end;
            Ok(value)
        };
        let request = c::MutateStateRequest::decode(field()?).map_err(|_| StoreError::Corrupt)?;
        let public = c::StateOperationReceipt::decode(field()?).map_err(|_| StoreError::Corrupt)?;
        let after = NamespaceRecord::decode(field()?).map_err(inspection::native_namespace)?;
        if offset != bytes.len() {
            return Err(StoreError::Corrupt);
        }
        let value = Self {
            request,
            public,
            after,
        };
        // Unknown/duplicate protobuf fields cannot widen the persisted codec.
        if value.encode()? != bytes {
            return Err(StoreError::Corrupt);
        }
        Ok(value)
    }

    fn validate(&self) -> Result<(), StoreError> {
        let original = contract::Request::from(self.request.clone());
        original.validate().map_err(|_| StoreError::Corrupt)?;
        contract::Response::from(c::MutateStateResponse {
            receipt: Some(self.public.clone()),
            audit_ack: None,
        })
        .validate_for(&original)
        .map_err(|_| StoreError::Corrupt)?;
        self.after
            .validate()
            .map_err(inspection::native_namespace)?;
        if self.request.mutation != c::StateMutationKind::ReleaseExpiredCommandFloor as i32
            || self.public.disposition != c::StateOperationDisposition::Committed as i32
            || self.after.status != NamespaceStatus::Retired
            || self.public.namespace != Some(response::selector(&self.after))
            || self.public.receipt_id
                != receipt_id(
                    &self.request,
                    &self.public.authenticated_operator,
                    &self.after,
                    self.public.completed_at_unix_millis,
                )?
        {
            return Err(StoreError::Corrupt);
        }
        let scope = StateScope {
            tenant: self.after.tenant.clone(),
            namespace: self.after.id.clone(),
            incarnation: self.after.version.incarnation,
            state_schema: self.after.state_schema.clone(),
            entity: None,
            mode: latent_state::session::StateMode::Query,
        };
        let before = ViewIdentity::from_token(&scope, &self.public.before_version)
            .map_err(|_| StoreError::Corrupt)?;
        let after = ViewIdentity::from_token(&scope, &self.public.after_version)
            .map_err(|_| StoreError::Corrupt)?;
        if after.namespace != self.after.version
            || before.epochs != after.epochs
            || before.namespace.incarnation != after.namespace.incarnation
            || before.namespace.generation.checked_add(1) != Some(after.namespace.generation)
        {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
}

fn receipt_id(
    request: &c::MutateStateRequest,
    actor: &str,
    after: &NamespaceRecord,
    time: u64,
) -> Result<String, StoreError> {
    let mut hash = Sha256::new();
    hash.update(b"lsf-state-operation-receipt-v1\0");
    for field in [
        request.encode_to_vec(),
        actor.as_bytes().to_vec(),
        after.encode().map_err(inspection::native_namespace)?,
        time.to_le_bytes().to_vec(),
    ] {
        hash.update((field.len() as u64).to_le_bytes());
        hash.update(field);
    }
    Ok(format!("state-receipt:{}", response::hex(&hash.finalize())))
}

pub(super) fn read(
    view: &ReadView,
    context: &NamespaceOperationContext,
) -> Result<Option<Receipt>, StoreError> {
    view.get(&key(context))?
        .as_deref()
        .map(Receipt::decode)
        .transpose()
}

pub(super) fn validate_row(view: &ReadView, row: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    if row.family != Family::Namespace || !row.key.starts_with(PREFIX) {
        return Err(StoreError::UnsupportedFormat);
    }
    let receipt = Receipt::decode(bytes)?;
    if *row != key(&receipt.context()) {
        return Err(StoreError::Corrupt);
    }
    let current = NamespaceCatalog::read_in(
        view,
        &TenantId(receipt.after.tenant.0.clone()),
        &receipt.after.id,
    )
    .map_err(inspection::native_namespace)?
    .ok_or(StoreError::Corrupt)?;
    if current.record().version.incarnation < receipt.after.version.incarnation
        || (current.record().version.incarnation == receipt.after.version.incarnation
            && current.record().version.generation < receipt.after.version.generation)
    {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}
