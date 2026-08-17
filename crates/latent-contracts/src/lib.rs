//! Contract descriptors, registries, compatibility checks, and binding compilation.

#![forbid(unsafe_code)]

use latent_core::{BoxFuture, ContractId, FunctionId, InterfaceId, Metadata, PlatformError};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ValueType {
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
    List(Box<ValueType>),
    Option(Box<ValueType>),
    Result {
        ok: Option<Box<ValueType>>,
        error: Option<Box<ValueType>>,
    },
    Tuple(Vec<ValueType>),
    Record(String),
    Variant(String),
    Resource(String),
    Future(Box<ValueType>),
    Stream(Box<ValueType>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FieldDescriptor {
    pub name: String,
    pub value_type: ValueType,
    pub documentation: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FunctionDescriptor {
    pub id: FunctionId,
    pub name: String,
    pub asynchronous: bool,
    pub parameters: Vec<FieldDescriptor>,
    pub results: Vec<FieldDescriptor>,
    pub documentation: Option<String>,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InterfaceDescriptor {
    pub id: InterfaceId,
    pub functions: Vec<FunctionDescriptor>,
    pub documentation: Option<String>,
    pub digest: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContractDescriptor {
    pub id: ContractId,
    pub package_name: String,
    pub semantic_version: String,
    pub interfaces: Vec<InterfaceDescriptor>,
    pub dependencies: Vec<ContractId>,
    pub digest: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CompatibilityLevel {
    Identical,
    BackwardCompatible,
    ForwardCompatible,
    BidirectionallyCompatible,
    Breaking,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompatibilityIssue {
    pub path: String,
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompatibilityReport {
    pub level: CompatibilityLevel,
    pub issues: Vec<CompatibilityIssue>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BindingPlan {
    pub consumer: ContractId,
    pub provider: ContractId,
    pub required_adapters: Vec<String>,
    pub plan_digest: String,
}

pub trait ContractRegistry: Send + Sync {
    fn get<'a>(
        &'a self,
        id: &'a ContractId,
    ) -> BoxFuture<'a, Result<Option<ContractDescriptor>, PlatformError>>;

    fn publish<'a>(
        &'a self,
        contract: ContractDescriptor,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn list<'a>(&'a self, package_prefix: &'a str)
        -> BoxFuture<'a, Result<Vec<ContractDescriptor>, PlatformError>>;
}

pub trait CompatibilityChecker: Send + Sync {
    fn compare(
        &self,
        consumer: &ContractDescriptor,
        provider: &ContractDescriptor,
    ) -> CompatibilityReport;
}

pub trait BindingCompiler: Send + Sync {
    fn compile<'a>(
        &'a self,
        consumer: &'a ContractDescriptor,
        provider: &'a ContractDescriptor,
    ) -> BoxFuture<'a, Result<BindingPlan, PlatformError>>;
}
