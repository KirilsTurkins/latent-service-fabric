use super::{wire, TriggerBinding, TriggerConfig};
use crate::{
    network::{Connection, Scope},
    protocol, EventError, Result,
};
use latent_capabilities::broker::pools::IngressRequest;
use serde::{
    de::{Error, IgnoredAny, SeqAccess, Visitor},
    Deserialize, Deserializer,
};
use std::fmt;

#[derive(Deserialize)]
struct Info<'a> {
    stream_name: &'a str,
    name: &'a str,
    #[serde(borrow)]
    config: Consumer<'a>,
    #[serde(default)]
    paused: bool,
}
#[derive(Deserialize)]
struct Consumer<'a> {
    durable_name: &'a str,
    name: &'a str,
    filter_subject: &'a str,
    ack_policy: &'a str,
    replay_policy: &'a str,
    deliver_policy: &'a str,
    ack_wait: u64,
    max_deliver: u32,
    max_waiting: u32,
    max_ack_pending: u32,
    max_batch: u32,
    max_bytes: usize,
    max_expires: u64,
    #[serde(default)]
    headers_only: bool,
    #[serde(default)]
    flow_control: bool,
    deliver_subject: Option<&'a str>,
    filter_subjects: Option<Empty>,
    backoff: Option<Empty>,
}
struct Empty;
impl<'de> Deserialize<'de> for Empty {
    fn deserialize<D: Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        struct Array;
        impl<'de> Visitor<'de> for Array {
            type Value = Empty;
            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("an empty optional configuration array")
            }
            fn visit_seq<A: SeqAccess<'de>>(
                self,
                mut a: A,
            ) -> std::result::Result<Empty, A::Error> {
                if a.next_element::<IgnoredAny>()?.is_some() {
                    return Err(A::Error::custom("unsupported consumer configuration"));
                }
                Ok(Empty)
            }
        }
        d.deserialize_seq(Array)
    }
}
pub(super) fn maximum_wire_bytes(config: &TriggerConfig) -> usize {
    config.maximum_payload_bytes + 9216
}
pub(super) fn validate(
    bytes: &[u8],
    binding: &TriggerBinding,
    config: &TriggerConfig,
) -> Result<()> {
    protocol::guard(bytes)?;
    let info: Info<'_> = serde_json::from_slice(bytes).map_err(|_| EventError::Unavailable)?;
    let c = info.config;
    // Merely visiting these optional fields rejects nonempty arrays without
    // retaining server-selected lists. All other extension fields are ignored.
    let _ = (c.filter_subjects, c.backoff);
    if info.stream_name != binding.stream
        || info.name != binding.consumer
        || info.paused
        || c.durable_name != binding.consumer
        || c.name != binding.consumer
        || c.filter_subject != binding.filter_subject
        || c.ack_policy != "explicit"
        || c.replay_policy != "instant"
        || c.deliver_policy != "all"
        || c.headers_only
        || c.flow_control
        || c.deliver_subject.is_some_and(|s| !s.is_empty())
        || c.ack_wait != config.ack_wait_millis * 1_000_000
        || c.max_deliver != config.maximum_deliveries
        || c.max_waiting != 1
        || c.max_ack_pending != 1
        || c.max_batch != 1
        || c.max_bytes != maximum_wire_bytes(config)
        || c.max_expires != 100_000_000
    {
        return Err(EventError::PermissionDenied);
    }
    Ok(())
}
pub(super) async fn check(
    connection: &mut Connection,
    request: &IngressRequest,
    binding: &TriggerBinding,
    config: &TriggerConfig,
    inbox: &str,
) -> Result<()> {
    request.begin_operation()?;
    let scope = Scope::from(request);
    protocol::subscribe(connection, scope, inbox).await?;
    let subject = format!(
        "$JS.API.CONSUMER.INFO.{}.{}",
        binding.stream, binding.consumer
    );
    wire::send(connection, scope, &subject, inbox, b"").await?;
    let response = wire::receive(connection, scope, &[inbox], 8192).await?;
    if response.reply.is_some() || response.headers != 0 {
        return Err(EventError::Unavailable);
    }
    validate(response.payload(), binding, config)
}

pub(super) async fn pull(
    connection: &mut Connection,
    request: &IngressRequest,
    binding: &TriggerBinding,
    config: &TriggerConfig,
    inbox: &str,
) -> Result<Option<(wire::Frame, wire::DeliveryIdentity)>> {
    request.begin_operation()?;
    let scope = Scope::from(request);
    protocol::subscribe(connection, scope, inbox).await?;
    let subject = format!(
        "$JS.API.CONSUMER.MSG.NEXT.{}.{}",
        binding.stream, binding.consumer
    );
    let body = format!(
        "{{\"batch\":1,\"no_wait\":true,\"expires\":100000000,\"max_bytes\":{}}}",
        maximum_wire_bytes(config)
    );
    wire::send(connection, scope, &subject, inbox, body.as_bytes()).await?;
    let response = wire::receive(
        connection,
        scope,
        &[inbox, &binding.filter_subject],
        config.maximum_payload_bytes,
    )
    .await?;
    if let Some(status) = response.status()? {
        if response.subject == inbox && matches!(status, 404 | 408 | 409) {
            return Ok(None);
        }
        return Err(EventError::Unavailable);
    }
    if response.subject != binding.filter_subject {
        return Err(EventError::Unavailable);
    }
    let identity = wire::identity(
        response.reply.as_deref().ok_or(EventError::Unavailable)?,
        binding,
    )?;
    Ok(Some((response, identity)))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Ack {
    Success,
    Retry,
    Terminate,
}
pub(super) async fn acknowledge(
    connection: &mut Connection,
    request: &IngressRequest,
    response: &wire::Frame,
    ack: Ack,
    delay_millis: u64,
    inbox: &str,
) -> Result<()> {
    request.begin_operation()?;
    let scope = Scope::from(request);
    protocol::subscribe(connection, scope, inbox).await?;
    let value = match ack {
        Ack::Success => "+ACK".into(),
        Ack::Terminate => "+TERM".into(),
        Ack::Retry => format!("-NAK {{\"delay\":{}}}", delay_millis * 1_000_000),
    };
    // A broker reply is used only after identity() verifies the configured
    // stream/consumer and the closed acknowledgement subject grammar.
    let reply = response.reply.as_deref().ok_or(EventError::Unavailable)?;
    wire::send(connection, scope, reply, inbox, value.as_bytes())
        .await
        .map_err(|_| EventError::Uncertain)?;
    let result = wire::receive(connection, scope, &[inbox], 0)
        .await
        .map_err(|_| EventError::Uncertain)?;
    if !result.bytes.is_empty() || result.reply.is_some() || result.headers != 0 {
        return Err(EventError::Uncertain);
    }
    Ok(())
}
