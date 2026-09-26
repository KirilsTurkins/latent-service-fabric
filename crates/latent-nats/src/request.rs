//! Validate actual lengths/capacities before retaining a future or encoding frames.
use crate::{
    config::{subject, text},
    EventError, Result,
};
use latent_capabilities::broker::{events::Event, CapabilityRequestDigest};
use sha2::{Digest, Sha256};
use std::fmt::Write;

pub(crate) struct Size {
    pub typed: usize,
    pub retained: usize,
}
pub(crate) fn validate(event: &Event, maximum: usize) -> Result<Size> {
    if !subject(&event.topic) || event.topic.capacity() > 128 {
        return Err(EventError::InvalidTopic);
    }
    if event.payload.len() > maximum
        || event.payload.capacity() > maximum
        || !text(&event.idempotency_key, 256)
        || event.idempotency_key.capacity() > 256
        || !text(&event.media_type, 128)
        || event.media_type.capacity() > 128
        || event
            .key
            .as_ref()
            .is_some_and(|k| !text(k, 256) || k.capacity() > 256)
        || event.attributes.capacity() > 16
    {
        return Err(EventError::InvalidEvent);
    }
    let mut headers = 0;
    for (i, (name, value)) in event.attributes.iter().enumerate() {
        if !text(name, 64)
            || name.capacity() > 64
            || !text(value, 256)
            || value.capacity() > 256
            || !name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
            || event.attributes[..i]
                .iter()
                .any(|(n, _)| n.eq_ignore_ascii_case(name))
        {
            return Err(EventError::InvalidEvent);
        }
        headers += name.len() + value.len() + 20;
    }
    if headers > 3072 {
        return Err(EventError::InvalidEvent);
    }
    let typed = event.topic.len()
        + event.key.as_ref().map_or(0, String::len)
        + event.payload.len()
        + event.media_type.len()
        + event.idempotency_key.len()
        + event
            .attributes
            .iter()
            .map(|(k, v)| k.len() + v.len())
            .sum::<usize>();
    let retained = event.topic.capacity()
        + event.key.as_ref().map_or(0, String::capacity)
        + event.payload.capacity()
        + event.media_type.capacity()
        + event.idempotency_key.capacity()
        + event.attributes.capacity() * std::mem::size_of::<(String, String)>()
        + event
            .attributes
            .iter()
            .map(|(k, v)| k.capacity() + v.capacity())
            .sum::<usize>();
    Ok(Size {
        typed,
        retained: retained.max(1),
    })
}
pub(crate) fn digest(event: &Event) -> Result<CapabilityRequestDigest> {
    // Length-delimited incremental hash includes every semantic field without
    // constructing another payload/JSON copy. Attribute order is significant.
    let mut hash = Sha256::new();
    part(&mut hash, b"lsf-immediate-event-v1");
    for value in [
        event.topic.as_bytes(),
        event.media_type.as_bytes(),
        event.idempotency_key.as_bytes(),
        &event.payload,
    ] {
        part(&mut hash, value);
    }
    hash.update([u8::from(event.key.is_some())]);
    part(&mut hash, event.key.as_deref().unwrap_or("").as_bytes());
    for (key, value) in &event.attributes {
        part(&mut hash, key.as_bytes());
        part(&mut hash, value.as_bytes());
    }
    CapabilityRequestDigest::from_parts(&[b"lsf-event-request-sha256-v1", &hash.finalize()])
        .map_err(Into::into)
}
fn part(hash: &mut Sha256, bytes: &[u8]) {
    hash.update((bytes.len() as u64).to_le_bytes());
    hash.update(bytes);
}
pub(crate) fn message_id(namespace: &str, tenant: &str, event: &Event) -> String {
    let mut hash = Sha256::new();
    for bytes in [
        b"lsf-jetstream-id-v1".as_slice(),
        namespace.as_bytes(),
        tenant.as_bytes(),
        event.topic.as_bytes(),
        event.idempotency_key.as_bytes(),
    ] {
        part(&mut hash, bytes);
    }
    format!("lsf-{:x}", hash.finalize())
}
pub(crate) fn headers(event: &Event, stream: &str, id: &str) -> String {
    let mut out = String::with_capacity(4096);
    write!(
        out,
        "NATS/1.0\r\nNats-Expected-Stream: {stream}\r\nNats-Msg-Id: {id}\r\nContent-Type: {}\r\n",
        event.media_type
    )
    .expect("String write");
    if let Some(key) = &event.key {
        write!(out, "Lsf-Event-Key: {key}\r\n").expect("String write");
    }
    for (key, value) in &event.attributes {
        write!(out, "Lsf-Attr-{key}: {value}\r\n").expect("String write");
    }
    out.push_str("\r\n");
    out
}
