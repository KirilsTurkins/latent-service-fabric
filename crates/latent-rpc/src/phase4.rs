//! Finite structural checks shared by authenticated adapters and explicit clients.
//!
//! These checks describe a request. They do not resolve a publication, derive a
//! caller scope, authorize a lookup, reserve recovery capacity, or prove abort.

mod bounds;
mod profile;
mod request;
mod response;
pub use profile::{HOST_ABI_DIGEST, PREPARATION_PROFILE_DIGEST, PROFILE};

use crate::{control::v1 as control, transaction::v1 as transaction};
use prost::Message;

pub const MAX_REQUEST_BYTES: usize = 2 * 1024 * 1024;
pub const MAX_RESPONSE_BYTES: usize = 2 * 1024 * 1024;
pub const MAX_PAGE_ENTRIES: usize = 128;
pub const MAX_PAGE_BYTES: usize = 1024 * 1024;
pub const MAX_ID_BYTES: usize = 256;

#[must_use]
pub fn current_profile() -> transaction::TransactionProfile {
    transaction::TransactionProfile {
        profile: PROFILE.into(),
        host_abi_digest: HOST_ABI_DIGEST.into(),
        preparation_profile_digest: PREPARATION_PROFILE_DIGEST.into(),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ValidationError {
    Capacity,
    Shape,
    UnsupportedProfile,
    Association,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Request {
    InspectNamespace(Box<control::InspectNamespaceRequest>),
    MutateNamespace(Box<control::MutateNamespaceRequest>),
    SelectEntity(Box<control::SelectEntityRequest>),
    MutateState(Box<control::MutateStateRequest>),
    GetStateOperationReceipt(Box<control::GetStateOperationReceiptRequest>),
    InvokeCommand(Box<transaction::InvokeCommandRequest>),
    Query(Box<transaction::QueryRequest>),
    LookupCommand(Box<transaction::LookupCommandRequest>),
    LookupCommit(Box<transaction::LookupCommitRequest>),
    GetEffect(Box<transaction::GetEffectRequest>),
    ListEffectHistory(Box<transaction::ListEffectHistoryRequest>),
    CancelCommand(Box<transaction::CancelCommandRequest>),
}

#[derive(Debug, Clone, PartialEq)]
pub enum Response {
    InspectNamespace(Box<control::InspectNamespaceResponse>),
    MutateNamespace(Box<control::MutateNamespaceResponse>),
    SelectEntity(Box<control::SelectEntityResponse>),
    MutateState(Box<control::MutateStateResponse>),
    GetStateOperationReceipt(Box<control::GetStateOperationReceiptResponse>),
    InvokeCommand(Box<transaction::InvokeCommandResponse>),
    Query(Box<transaction::QueryResponse>),
    LookupCommand(Box<transaction::LookupCommandResponse>),
    LookupCommit(Box<transaction::LookupCommitResponse>),
    GetEffect(Box<transaction::GetEffectResponse>),
    ListEffectHistory(Box<transaction::ListEffectHistoryResponse>),
    CancelCommand(Box<transaction::CancelCommandResponse>),
}

/// Selector/precondition metadata retained while the owned request is consumed
/// by the real runtime. It excludes payload, expected-version arrays and trace.
pub struct Association(Request);

macro_rules! conversion {
    ($enum:ident;$(($variant:ident,$message:ty)),+$(,)?)=>{
        $(impl From<$message> for $enum {
            fn from(message:$message)->Self { Self::$variant(Box::new(message)) }
        })+
        impl $enum {
            pub(super) fn native_message_bytes(&self)->usize {
                match self { $(Self::$variant(message)=>std::mem::size_of_val(&**message),)+ }
            }
        }
    };
}
conversion!(Request;
    (InspectNamespace,control::InspectNamespaceRequest),(MutateNamespace,control::MutateNamespaceRequest),
    (SelectEntity,control::SelectEntityRequest),(MutateState,control::MutateStateRequest),
    (GetStateOperationReceipt,control::GetStateOperationReceiptRequest),(InvokeCommand,transaction::InvokeCommandRequest),
    (Query,transaction::QueryRequest),(LookupCommand,transaction::LookupCommandRequest),
    (LookupCommit,transaction::LookupCommitRequest),(GetEffect,transaction::GetEffectRequest),
    (ListEffectHistory,transaction::ListEffectHistoryRequest),(CancelCommand,transaction::CancelCommandRequest));
conversion!(Response;
    (InspectNamespace,control::InspectNamespaceResponse),(MutateNamespace,control::MutateNamespaceResponse),
    (SelectEntity,control::SelectEntityResponse),(MutateState,control::MutateStateResponse),
    (GetStateOperationReceipt,control::GetStateOperationReceiptResponse),(InvokeCommand,transaction::InvokeCommandResponse),
    (Query,transaction::QueryResponse),(LookupCommand,transaction::LookupCommandResponse),
    (LookupCommit,transaction::LookupCommitResponse),(GetEffect,transaction::GetEffectResponse),
    (ListEffectHistory,transaction::ListEffectHistoryResponse),(CancelCommand,transaction::CancelCommandResponse));

macro_rules! encoded_len {
    ($name:ident, $($variant:ident),+ $(,)?) => {
        impl $name {
            #[must_use]
            pub fn encoded_len(&self) -> usize {
                match self { $(Self::$variant(message) => message.encoded_len(),)+ }
            }
        }
    };
}
encoded_len!(
    Request,
    InspectNamespace,
    MutateNamespace,
    SelectEntity,
    MutateState,
    GetStateOperationReceipt,
    InvokeCommand,
    Query,
    LookupCommand,
    LookupCommit,
    GetEffect,
    ListEffectHistory,
    CancelCommand
);
encoded_len!(
    Response,
    InspectNamespace,
    MutateNamespace,
    SelectEntity,
    MutateState,
    GetStateOperationReceipt,
    InvokeCommand,
    Query,
    LookupCommand,
    LookupCommit,
    GetEffect,
    ListEffectHistory,
    CancelCommand
);

impl Request {
    /// Bounded traversal precedes `encoded_len`, target resolution and lookup.
    pub fn validate(&self) -> Result<(), ValidationError> {
        request::validate(self)?;
        if self.encoded_len() > MAX_REQUEST_BYTES {
            return Err(ValidationError::Capacity);
        }
        Ok(())
    }

    /// Requested tenant only; the listener still compares its authenticated
    /// principal, and the domain owner seals current publication/data authority.
    #[must_use]
    pub fn tenant(&self) -> Option<&str> {
        request::tenant(self)
    }

    #[must_use]
    pub fn association(&self) -> Association {
        let request = match self {
            Self::InvokeCommand(value) => Self::from(transaction::InvokeCommandRequest {
                command: value.command.clone(),
                ..Default::default()
            }),
            Self::Query(value) => Self::from(transaction::QueryRequest {
                namespace: value.namespace.clone(),
                ..Default::default()
            }),
            _ => self.clone(),
        };
        Association(request)
    }

    #[must_use]
    pub const fn is_management(&self) -> bool {
        matches!(
            self,
            Self::InspectNamespace(_)
                | Self::MutateNamespace(_)
                | Self::SelectEntity(_)
                | Self::MutateState(_)
                | Self::GetStateOperationReceipt(_)
        )
    }

    /// These calls need the host's reserved recovery owner, including reads.
    #[must_use]
    pub const fn is_recovery(&self) -> bool {
        !matches!(self, Self::InvokeCommand(_) | Self::Query(_))
    }
}

impl Response {
    pub fn validate_association(&self, association: &Association) -> Result<(), ValidationError> {
        self.validate_for(&association.0)
    }
    /// Validates allocation, closed vocabulary and original request association.
    /// A response that says unknown/expired never acquires abort authority.
    pub fn validate_for(&self, request: &Request) -> Result<(), ValidationError> {
        response::validate(self, request)?;
        if self.encoded_len() > MAX_RESPONSE_BYTES {
            return Err(ValidationError::Capacity);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests;
