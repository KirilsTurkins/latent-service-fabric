// Generated from exact Protobuf owners. Do not edit.
use super::codec::{Field, Kind, Schema};

pub(super) static LATENT_CONTROL_V1_AUDITACK: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::AuditAck>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_CONTROLDISPATCHERRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::ControlDispatcherResponse>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_CONTROL_V1_DISPATCHEROPERATIONRECEIPT),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::Message(&LATENT_CONTROL_V1_AUDITACK),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_DISPATCHERGENERATION: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::DispatcherGeneration>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_DISPATCHEROPERATIONRECEIPT: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::DispatcherOperationReceipt>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::Message(&LATENT_CONTROL_V1_DISPATCHERGENERATION),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::Message(&LATENT_CONTROL_V1_DISPATCHERGENERATION),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 8,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 9,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 10,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 11,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_DISPATCHERSNAPSHOT: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::DispatcherSnapshot>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_CONTROL_V1_DISPATCHERGENERATION),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 8,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 9,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 10,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 11,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 12,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 13,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 14,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 15,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 16,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 17,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 18,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 19,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 20,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 21,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 22,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_EFFECTMANAGEMENTPLAN: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::EffectManagementPlan>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_CONTROL_V1_PLANEFFECTMUTATIONREQUEST),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::U32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::U32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 8,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 9,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 10,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 11,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_EFFECTMANAGEMENTRECEIPTDETAILS: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::EffectManagementReceiptDetails>()
        + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_CONTROL_V1_EFFECTMANAGEMENTPLAN),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 6,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 2,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_ENTITYINSPECTION: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::EntityInspection>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_ERRORDETAIL: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::ErrorDetail>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Map(&LATENT_CONTROL_V1_ERRORDETAIL_FIELDSENTRY),
            repeated: true,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_ERRORDETAIL_FIELDSENTRY: Schema = Schema {
    allocation: 256,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_GETDISPATCHEROPERATIONRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::GetDispatcherOperationResponse>()
        + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_CONTROL_V1_DISPATCHEROPERATIONRECEIPT),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Message(&LATENT_CONTROL_V1_AUDITACK),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_GETSTATEOPERATIONRECEIPTRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::GetStateOperationReceiptResponse>(
    ) + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_CONTROL_V1_STATEOPERATIONRECEIPT),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Message(&LATENT_CONTROL_V1_NAMESPACEOPERATIONRECEIPT),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::Message(&LATENT_CONTROL_V1_AUDITACK),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_INSPECTDISPATCHERRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::InspectDispatcherResponse>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_CONTROL_V1_DISPATCHERSNAPSHOT),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Message(&LATENT_CONTROL_V1_AUDITACK),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_INSPECTNAMESPACERESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::InspectNamespaceResponse>() + 64,
    fields: &[Field {
        number: 1,
        kind: Kind::Message(&LATENT_CONTROL_V1_NAMESPACEINSPECTION),
        repeated: false,
        maximum: 128,
        oneof: 0,
    }],
};

pub(super) static LATENT_CONTROL_V1_MUTATENAMESPACERESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::MutateNamespaceResponse>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_CONTROL_V1_NAMESPACEOPERATIONRECEIPT),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::Message(&LATENT_CONTROL_V1_AUDITACK),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_MUTATESTATERESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::MutateStateResponse>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_CONTROL_V1_STATEOPERATIONRECEIPT),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Message(&LATENT_CONTROL_V1_AUDITACK),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_NAMESPACEINSPECTION: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::NamespaceInspection>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_VIEWIDENTITY),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_LINKEDRETENTION),
            repeated: true,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 8,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 9,
            kind: Kind::Message(&LATENT_CONTROL_V1_NAMESPACEQUOTA),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 10,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 11,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_NAMESPACEOPERATIONRECEIPT: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::NamespaceOperationReceipt>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_NAMESPACESELECTOR),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 7,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 8,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 9,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 10,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_NAMESPACEQUOTA: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::NamespaceQuota>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 8,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_PLANEFFECTMUTATIONREQUEST: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::PlanEffectMutationRequest>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_GETEFFECTREQUEST),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_PLANEFFECTMUTATIONRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::PlanEffectMutationResponse>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_CONTROL_V1_EFFECTMANAGEMENTPLAN),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::Message(&LATENT_CONTROL_V1_AUDITACK),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_PLATFORMERROR: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::PlatformError>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::Message(&LATENT_CONTROL_V1_ERRORDETAIL),
            repeated: true,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_PUBLICATIONREF: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::PublicationRef>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_SELECTENTITYRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::SelectEntityResponse>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_CONTROL_V1_ENTITYINSPECTION),
            repeated: true,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_PAGERESPONSE),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_CONTROL_V1_STATEOPERATIONRECEIPT: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::control::v1::StateOperationReceipt>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_NAMESPACESELECTOR),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 8,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 9,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 10,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 11,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 12,
            kind: Kind::Message(&LATENT_CONTROL_V1_EFFECTMANAGEMENTRECEIPTDETAILS),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_INVOCATION_V1_BUDGETCONSUMPTION: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::invocation::v1::BudgetConsumption>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::U32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::U32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 8,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 9,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 10,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 11,
            kind: Kind::U32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_INVOCATION_V1_DECLAREDERROR: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::invocation::v1::DeclaredError>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::Map(&LATENT_INVOCATION_V1_DECLAREDERROR_METADATAENTRY),
            repeated: true,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_INVOCATION_V1_DECLAREDERROR_METADATAENTRY: Schema = Schema {
    allocation: 256,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_INVOCATION_V1_ERRORDETAIL: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::invocation::v1::ErrorDetail>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Map(&LATENT_INVOCATION_V1_ERRORDETAIL_FIELDSENTRY),
            repeated: true,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_INVOCATION_V1_ERRORDETAIL_FIELDSENTRY: Schema = Schema {
    allocation: 256,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_INVOCATION_V1_INVOKERESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::invocation::v1::InvokeResponse>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::Message(&LATENT_INVOCATION_V1_SUCCESS),
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 8,
            kind: Kind::Message(&LATENT_INVOCATION_V1_DECLAREDERROR),
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 9,
            kind: Kind::Message(&LATENT_INVOCATION_V1_PLATFORMERROR),
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 7,
            kind: Kind::Message(&LATENT_INVOCATION_V1_BUDGETCONSUMPTION),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 10,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 2,
        },
    ],
};

pub(super) static LATENT_INVOCATION_V1_PLATFORMERROR: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::invocation::v1::PlatformError>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::Message(&LATENT_INVOCATION_V1_ERRORDETAIL),
            repeated: true,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_INVOCATION_V1_SUCCESS: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::invocation::v1::Success>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 4,
            kind: Kind::String,
            repeated: true,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::Map(&LATENT_INVOCATION_V1_SUCCESS_METADATAENTRY),
            repeated: true,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_INVOCATION_V1_SUCCESS_METADATAENTRY: Schema = Schema {
    allocation: 256,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_ABORTFENCE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::AbortFence>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_CANCELCOMMANDRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::CancelCommandResponse>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_COMMANDINSPECTION),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_COMMANDINSPECTION: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::CommandInspection>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_COMMANDKEY),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 8,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_SOURCEIDENTITY),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 9,
            kind: Kind::Message(&LATENT_INVOCATION_V1_SUCCESS),
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 10,
            kind: Kind::Message(&LATENT_INVOCATION_V1_DECLAREDERROR),
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 11,
            kind: Kind::Message(&LATENT_INVOCATION_V1_PLATFORMERROR),
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 12,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_COMMITRECEIPT),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 13,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_ABORTFENCE),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 14,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_LINKEDRETENTION),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 15,
            kind: Kind::Message(&LATENT_INVOCATION_V1_PLATFORMERROR),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_COMMANDKEY: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::CommandKey>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_NAMESPACESELECTOR),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 5,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_COMMANDSELECTOR: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::CommandSelector>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_NAMESPACESELECTOR),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 4,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 2,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_COMMITRECEIPT: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::CommitReceipt>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::String,
            repeated: true,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 8,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_SOURCEIDENTITY),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_EFFECTRECEIPT: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::EffectReceipt>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::U32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::I32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 7,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 2,
        },
        Field {
            number: 8,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 9,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_LINKEDRETENTION),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 10,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 3,
        },
        Field {
            number: 11,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 12,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 13,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 4,
        },
        Field {
            number: 14,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 5,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_GETEFFECTREQUEST: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::GetEffectRequest>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_TRANSACTIONPROFILE),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_COMMANDSELECTOR),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::Message(&LATENT_CONTROL_V1_PUBLICATIONREF),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_GETEFFECTRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::GetEffectResponse>() + 64,
    fields: &[Field {
        number: 1,
        kind: Kind::Message(&LATENT_TRANSACTION_V1_EFFECTRECEIPT),
        repeated: false,
        maximum: 128,
        oneof: 0,
    }],
};

pub(super) static LATENT_TRANSACTION_V1_INVOKECOMMANDRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::InvokeCommandResponse>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_INVOCATION_V1_INVOKERESPONSE),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_COMMANDINSPECTION),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_LINKEDRETENTION: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::LinkedRetention>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::U32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 4,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 2,
        },
        Field {
            number: 5,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 3,
        },
        Field {
            number: 6,
            kind: Kind::String,
            repeated: true,
            maximum: 256,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::Bool,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_LISTEFFECTHISTORYRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::ListEffectHistoryResponse>()
        + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_EFFECTRECEIPT),
            repeated: true,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_PAGERESPONSE),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_LOOKUPCOMMANDRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::LookupCommandResponse>() + 64,
    fields: &[Field {
        number: 1,
        kind: Kind::Message(&LATENT_TRANSACTION_V1_COMMANDINSPECTION),
        repeated: false,
        maximum: 128,
        oneof: 0,
    }],
};

pub(super) static LATENT_TRANSACTION_V1_LOOKUPCOMMITRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::LookupCommitResponse>() + 64,
    fields: &[Field {
        number: 1,
        kind: Kind::Message(&LATENT_TRANSACTION_V1_COMMANDINSPECTION),
        repeated: false,
        maximum: 128,
        oneof: 0,
    }],
};

pub(super) static LATENT_TRANSACTION_V1_NAMESPACESELECTOR: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::NamespaceSelector>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_PAGERESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::PageResponse>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 1,
        },
        Field {
            number: 2,
            kind: Kind::U32,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_QUERYRESPONSE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::QueryResponse>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_INVOCATION_V1_INVOKERESPONSE),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_VIEWIDENTITY),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_SOURCEIDENTITY),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_SOURCEIDENTITY: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::SourceIdentity>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 4,
            kind: Kind::U64,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 5,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 6,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 7,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 8,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 9,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_TRANSACTIONPROFILE: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::TransactionProfile>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};

pub(super) static LATENT_TRANSACTION_V1_VIEWIDENTITY: Schema = Schema {
    allocation: 2 * std::mem::size_of::<latent_rpc::transaction::v1::ViewIdentity>() + 64,
    fields: &[
        Field {
            number: 1,
            kind: Kind::Message(&LATENT_TRANSACTION_V1_NAMESPACESELECTOR),
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 2,
            kind: Kind::Bytes,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
        Field {
            number: 3,
            kind: Kind::String,
            repeated: false,
            maximum: 128,
            oneof: 0,
        },
    ],
};
