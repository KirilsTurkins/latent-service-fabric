//! Data-plane wire frames, handshake, codecs, and duplex channel interfaces.

#![forbid(unsafe_code)]

use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{ActivationId, BoxFuture, Metadata, NodeId, PlatformError, RouteGeneration};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FrameKind {
    Hello,
    Accept,
    Ready,
    Call,
    Result,
    Error,
    Cancel,
    StreamOpen,
    StreamData,
    StreamEnd,
    WindowUpdate,
    Ping,
    Pong,
    Drain,
    Shutdown,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProtocolVersion {
    pub major: u16,
    pub minor: u16,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Handshake {
    pub protocol: ProtocolVersion,
    pub node: NodeId,
    pub route_generation: RouteGeneration,
    pub supported_encodings: Vec<String>,
    pub supported_features: Vec<String>,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WirePayload {
    None,
    Handshake(Handshake),
    Activation(ActivationEnvelope),
    Outcome(ActivationOutcome),
    Bytes(Vec<u8>),
    Error(PlatformError),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WireFrame {
    pub kind: FrameKind,
    pub request_id: String,
    pub activation_id: Option<ActivationId>,
    pub sequence: u64,
    pub end_of_stream: bool,
    pub metadata: Metadata,
    pub payload: WirePayload,
}

pub trait WireCodec: Send + Sync {
    fn media_type(&self) -> &str;
    fn encode(&self, frame: &WireFrame) -> Result<Vec<u8>, PlatformError>;
    fn decode(&self, bytes: &[u8]) -> Result<WireFrame, PlatformError>;
}

pub trait DuplexChannel: Send + Sync {
    fn send<'a>(&'a self, frame: WireFrame) -> BoxFuture<'a, Result<(), PlatformError>>;
    fn receive<'a>(&'a self) -> BoxFuture<'a, Result<Option<WireFrame>, PlatformError>>;
    fn close<'a>(&'a self) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait RequestMultiplexer: Send + Sync {
    fn call<'a>(&'a self, frame: WireFrame) -> BoxFuture<'a, Result<WireFrame, PlatformError>>;

    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        reason: &'a str,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}
