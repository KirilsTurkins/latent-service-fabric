use latent_contracts::{
    ContractDescriptor, FieldDescriptor, FunctionDescriptor, InterfaceDescriptor, ValueType,
};
use latent_core::{
    ArtifactReference, ContractId, FunctionId, InterfaceId, Metadata, PublisherId, ReleaseDigest,
};
use latent_manifest::__serde::{Deserialize, Serialize};

use crate::{ArtifactDescriptor, ArtifactLayer};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
pub(super) struct StoredMetadata {
    pub(super) descriptor: StoredArtifactDescriptor,
    pub(super) contracts: Vec<StoredContractDescriptor>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
pub(super) struct StoredArtifactDescriptor {
    reference: String,
    release_digest: String,
    media_type: String,
    size_bytes: u64,
    publisher: Option<String>,
    layers: Vec<StoredArtifactLayer>,
    annotations: Metadata,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
struct StoredArtifactLayer {
    media_type: String,
    digest: String,
    size_bytes: u64,
    annotations: Metadata,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
pub(super) struct StoredContractDescriptor {
    id: String,
    package_name: String,
    semantic_version: String,
    interfaces: Vec<StoredInterfaceDescriptor>,
    dependencies: Vec<String>,
    digest: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
struct StoredInterfaceDescriptor {
    id: String,
    functions: Vec<StoredFunctionDescriptor>,
    documentation: Option<String>,
    digest: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
struct StoredFunctionDescriptor {
    id: String,
    name: String,
    asynchronous: bool,
    parameters: Vec<StoredFieldDescriptor>,
    results: Vec<StoredFieldDescriptor>,
    documentation: Option<String>,
    attributes: Metadata,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
struct StoredFieldDescriptor {
    name: String,
    value_type: StoredValueType,
    documentation: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde")]
enum StoredValueType {
    Bool,
    U8,
    U16,
    U32,
    U64,
    S8,
    S16,
    S32,
    S64,
    F32,
    F64,
    Char,
    String,
    Bytes,
    List(Box<StoredValueType>),
    Option(Box<StoredValueType>),
    Result {
        ok: Option<Box<StoredValueType>>,
        error: Option<Box<StoredValueType>>,
    },
    Tuple(Vec<StoredValueType>),
    Record(String),
    Variant(String),
    Resource(String),
    Future(Box<StoredValueType>),
    Stream(Box<StoredValueType>),
}

impl From<&ArtifactDescriptor> for StoredArtifactDescriptor {
    fn from(value: &ArtifactDescriptor) -> Self {
        Self {
            reference: value.reference.0.clone(),
            release_digest: value.release_digest.0.clone(),
            media_type: value.media_type.clone(),
            size_bytes: value.size_bytes,
            publisher: value
                .publisher
                .as_ref()
                .map(|publisher| publisher.0.clone()),
            layers: value.layers.iter().map(StoredArtifactLayer::from).collect(),
            annotations: value.annotations.clone(),
        }
    }
}

impl From<StoredArtifactDescriptor> for ArtifactDescriptor {
    fn from(value: StoredArtifactDescriptor) -> Self {
        Self {
            reference: ArtifactReference(value.reference),
            release_digest: ReleaseDigest(value.release_digest),
            media_type: value.media_type,
            size_bytes: value.size_bytes,
            publisher: value.publisher.map(PublisherId),
            layers: value.layers.into_iter().map(ArtifactLayer::from).collect(),
            annotations: value.annotations,
        }
    }
}

impl From<&ArtifactLayer> for StoredArtifactLayer {
    fn from(value: &ArtifactLayer) -> Self {
        Self {
            media_type: value.media_type.clone(),
            digest: value.digest.clone(),
            size_bytes: value.size_bytes,
            annotations: value.annotations.clone(),
        }
    }
}

impl From<StoredArtifactLayer> for ArtifactLayer {
    fn from(value: StoredArtifactLayer) -> Self {
        Self {
            media_type: value.media_type,
            digest: value.digest,
            size_bytes: value.size_bytes,
            annotations: value.annotations,
        }
    }
}

impl From<&ContractDescriptor> for StoredContractDescriptor {
    fn from(value: &ContractDescriptor) -> Self {
        Self {
            id: value.id.0.clone(),
            package_name: value.package_name.clone(),
            semantic_version: value.semantic_version.clone(),
            interfaces: value
                .interfaces
                .iter()
                .map(StoredInterfaceDescriptor::from)
                .collect(),
            dependencies: value
                .dependencies
                .iter()
                .map(|dependency| dependency.0.clone())
                .collect(),
            digest: value.digest.clone(),
        }
    }
}

impl From<StoredContractDescriptor> for ContractDescriptor {
    fn from(value: StoredContractDescriptor) -> Self {
        Self {
            id: ContractId(value.id),
            package_name: value.package_name,
            semantic_version: value.semantic_version,
            interfaces: value
                .interfaces
                .into_iter()
                .map(InterfaceDescriptor::from)
                .collect(),
            dependencies: value.dependencies.into_iter().map(ContractId).collect(),
            digest: value.digest,
        }
    }
}

impl From<&InterfaceDescriptor> for StoredInterfaceDescriptor {
    fn from(value: &InterfaceDescriptor) -> Self {
        Self {
            id: value.id.0.clone(),
            functions: value
                .functions
                .iter()
                .map(StoredFunctionDescriptor::from)
                .collect(),
            documentation: value.documentation.clone(),
            digest: value.digest.clone(),
        }
    }
}

impl From<StoredInterfaceDescriptor> for InterfaceDescriptor {
    fn from(value: StoredInterfaceDescriptor) -> Self {
        Self {
            id: InterfaceId(value.id),
            functions: value
                .functions
                .into_iter()
                .map(FunctionDescriptor::from)
                .collect(),
            documentation: value.documentation,
            digest: value.digest,
        }
    }
}

impl From<&FunctionDescriptor> for StoredFunctionDescriptor {
    fn from(value: &FunctionDescriptor) -> Self {
        Self {
            id: value.id.0.clone(),
            name: value.name.clone(),
            asynchronous: value.asynchronous,
            parameters: value
                .parameters
                .iter()
                .map(StoredFieldDescriptor::from)
                .collect(),
            results: value
                .results
                .iter()
                .map(StoredFieldDescriptor::from)
                .collect(),
            documentation: value.documentation.clone(),
            attributes: value.attributes.clone(),
        }
    }
}

impl From<StoredFunctionDescriptor> for FunctionDescriptor {
    fn from(value: StoredFunctionDescriptor) -> Self {
        Self {
            id: FunctionId(value.id),
            name: value.name,
            asynchronous: value.asynchronous,
            parameters: value
                .parameters
                .into_iter()
                .map(FieldDescriptor::from)
                .collect(),
            results: value
                .results
                .into_iter()
                .map(FieldDescriptor::from)
                .collect(),
            documentation: value.documentation,
            attributes: value.attributes,
        }
    }
}

impl From<&FieldDescriptor> for StoredFieldDescriptor {
    fn from(value: &FieldDescriptor) -> Self {
        Self {
            name: value.name.clone(),
            value_type: StoredValueType::from(&value.value_type),
            documentation: value.documentation.clone(),
        }
    }
}

impl From<StoredFieldDescriptor> for FieldDescriptor {
    fn from(value: StoredFieldDescriptor) -> Self {
        Self {
            name: value.name,
            value_type: ValueType::from(value.value_type),
            documentation: value.documentation,
        }
    }
}

impl From<&ValueType> for StoredValueType {
    fn from(value: &ValueType) -> Self {
        match value {
            ValueType::Bool => Self::Bool,
            ValueType::U8 => Self::U8,
            ValueType::U16 => Self::U16,
            ValueType::U32 => Self::U32,
            ValueType::U64 => Self::U64,
            ValueType::S8 => Self::S8,
            ValueType::S16 => Self::S16,
            ValueType::S32 => Self::S32,
            ValueType::S64 => Self::S64,
            ValueType::F32 => Self::F32,
            ValueType::F64 => Self::F64,
            ValueType::Char => Self::Char,
            ValueType::String => Self::String,
            ValueType::Bytes => Self::Bytes,
            ValueType::List(inner) => Self::List(Box::new(Self::from(inner.as_ref()))),
            ValueType::Option(inner) => Self::Option(Box::new(Self::from(inner.as_ref()))),
            ValueType::Result { ok, error } => Self::Result {
                ok: ok
                    .as_ref()
                    .map(|inner| Box::new(Self::from(inner.as_ref()))),
                error: error
                    .as_ref()
                    .map(|inner| Box::new(Self::from(inner.as_ref()))),
            },
            ValueType::Tuple(values) => Self::Tuple(values.iter().map(Self::from).collect()),
            ValueType::Record(name) => Self::Record(name.clone()),
            ValueType::Variant(name) => Self::Variant(name.clone()),
            ValueType::Resource(name) => Self::Resource(name.clone()),
            ValueType::Future(inner) => Self::Future(Box::new(Self::from(inner.as_ref()))),
            ValueType::Stream(inner) => Self::Stream(Box::new(Self::from(inner.as_ref()))),
        }
    }
}

impl From<StoredValueType> for ValueType {
    fn from(value: StoredValueType) -> Self {
        match value {
            StoredValueType::Bool => Self::Bool,
            StoredValueType::U8 => Self::U8,
            StoredValueType::U16 => Self::U16,
            StoredValueType::U32 => Self::U32,
            StoredValueType::U64 => Self::U64,
            StoredValueType::S8 => Self::S8,
            StoredValueType::S16 => Self::S16,
            StoredValueType::S32 => Self::S32,
            StoredValueType::S64 => Self::S64,
            StoredValueType::F32 => Self::F32,
            StoredValueType::F64 => Self::F64,
            StoredValueType::Char => Self::Char,
            StoredValueType::String => Self::String,
            StoredValueType::Bytes => Self::Bytes,
            StoredValueType::List(inner) => Self::List(Box::new(Self::from(*inner))),
            StoredValueType::Option(inner) => Self::Option(Box::new(Self::from(*inner))),
            StoredValueType::Result { ok, error } => Self::Result {
                ok: ok.map(|inner| Box::new(Self::from(*inner))),
                error: error.map(|inner| Box::new(Self::from(*inner))),
            },
            StoredValueType::Tuple(values) => {
                Self::Tuple(values.into_iter().map(Self::from).collect())
            }
            StoredValueType::Record(name) => Self::Record(name),
            StoredValueType::Variant(name) => Self::Variant(name),
            StoredValueType::Resource(name) => Self::Resource(name),
            StoredValueType::Future(inner) => Self::Future(Box::new(Self::from(*inner))),
            StoredValueType::Stream(inner) => Self::Stream(Box::new(Self::from(*inner))),
        }
    }
}
