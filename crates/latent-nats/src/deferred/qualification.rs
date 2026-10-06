use crate::{config::text, protocol, EventError, NatsConfig, Result, TopicMapping};
use serde::{Deserialize, Serialize};

/// Operator-measured stream configuration. No guest supplies this record.
/// The narrow profile forbids purge/deletion and eviction of accepted history;
/// changing any qualified field requires a new retained dispatch profile.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct JetStreamQualification {
    pub format_version: u32,
    /// Exact qualified software version, observed inside the authenticated TLS INFO.
    pub server_version: String,
    pub stream_created: String,
    pub maximum_messages: u64,
    pub maximum_bytes: u64,
    /// Zero means no age eviction. A finite value must cover the duplicate window.
    pub maximum_age_millis: u64,
    pub maximum_message_bytes: u32,
}

impl JetStreamQualification {
    pub fn validate(&self, mapping: &TopicMapping, config: &NatsConfig) -> Result<()> {
        if self.format_version != 1
            || !text(&self.server_version, 64)
            || self.server_version.capacity() > 64
            || !text(&self.stream_created, 64)
            || self.stream_created.capacity() > 64
            || !created_at(&self.stream_created)
            || !(1..=100_000).contains(&self.maximum_messages)
            || !(4096..=64 * 1024 * 1024).contains(&self.maximum_bytes)
            || (self.maximum_age_millis != 0
                && (self.maximum_age_millis < mapping.duplicate_window_millis
                    || self.maximum_age_millis > 604_800_000))
            || u64::from(self.maximum_message_bytes) > self.maximum_bytes
            || usize::try_from(self.maximum_message_bytes)
                .is_ok_and(|maximum| maximum < config.maximum_payload_bytes + 4096)
            || self.maximum_message_bytes > 1024 * 1024
        {
            return Err(EventError::InvalidEvent);
        }
        Ok(())
    }
}

fn created_at(value: &str) -> bool {
    let bytes = value.as_bytes();
    if !(20..=30).contains(&bytes.len())
        || bytes[4] != b'-'
        || bytes[7] != b'-'
        || bytes[10] != b'T'
        || bytes[13] != b':'
        || bytes[16] != b':'
        || bytes.last() != Some(&b'Z')
        || bytes[..19]
            .iter()
            .enumerate()
            .any(|(i, byte)| !matches!(i, 4 | 7 | 10 | 13 | 16) && !byte.is_ascii_digit())
        || (bytes.len() > 20
            && (bytes[19] != b'.'
                || bytes.len() == 21
                || !bytes[20..bytes.len() - 1].iter().all(u8::is_ascii_digit)))
    {
        return false;
    }
    let number = |start, end| value[start..end].parse::<u32>().unwrap_or(0);
    let year = number(0, 4);
    let month = number(5, 7);
    let days = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29,
        2 => 28,
        _ => return false,
    };
    year != 0
        && (1..=days).contains(&number(8, 10))
        && number(11, 13) < 24
        && number(14, 16) < 60
        && number(17, 19) < 60
}

#[derive(Deserialize)]
struct StreamInfo<'a> {
    #[serde(rename = "type", borrow)]
    kind: &'a str,
    #[serde(borrow)]
    created: &'a str,
    #[serde(borrow)]
    config: StreamConfig<'a>,
}

#[derive(Deserialize)]
#[expect(
    clippy::struct_excessive_bools,
    reason = "immutable literal broker configuration flags"
)]
struct StreamConfig<'a> {
    #[serde(borrow)]
    name: &'a str,
    #[serde(borrow)]
    subjects: Vec<&'a str>,
    storage: &'a str,
    retention: &'a str,
    discard: &'a str,
    num_replicas: u32,
    max_msgs: i64,
    max_bytes: i64,
    max_age: u64,
    max_msg_size: i32,
    duplicate_window: u64,
    #[serde(default)]
    deny_delete: bool,
    #[serde(default)]
    deny_purge: bool,
    #[serde(default)]
    sealed: bool,
    #[serde(default)]
    allow_rollup_hdrs: bool,
    #[serde(default)]
    discard_new_per_subject: bool,
    #[serde(default)]
    allow_msg_ttl: bool,
    #[serde(default)]
    allow_atomic: bool,
    #[serde(default)]
    allow_msg_counter: bool,
    #[serde(default)]
    allow_msg_schedules: bool,
    subject_transform: Option<serde::de::IgnoredAny>,
    republish: Option<serde::de::IgnoredAny>,
    mirror: Option<serde::de::IgnoredAny>,
    sources: Option<serde::de::IgnoredAny>,
}

pub(super) fn validate_response(
    bytes: &[u8],
    qualification: &JetStreamQualification,
    mapping: &TopicMapping,
    config: &NatsConfig,
) -> Result<()> {
    protocol::guard(bytes)?;
    let info: StreamInfo<'_> =
        serde_json::from_slice(bytes).map_err(|_| EventError::Unavailable)?;
    let stream = info.config;
    let expected: Vec<_> = config
        .topics
        .iter()
        .filter(|topic| topic.stream == mapping.stream)
        .map(|topic| topic.subject.as_str())
        .collect();
    // 8192-byte framing bounds decoding before allocation; the admitted
    // request prepays 128 KiB of protocol/descriptor scratch as well as its body.
    if info.kind != "io.nats.jetstream.api.v1.stream_info_response"
        || info.created != qualification.stream_created
        || stream.name != mapping.stream
        || stream.subjects.len() > 16
        || stream
            .subjects
            .iter()
            .any(|subject| !expected.contains(subject))
        || expected
            .iter()
            .any(|subject| !stream.subjects.contains(subject))
        || stream.storage != "file"
        || stream.retention != "limits"
        || stream.discard != "new"
        || stream.num_replicas != 1
        || u64::try_from(stream.max_msgs).ok() != Some(qualification.maximum_messages)
        || u64::try_from(stream.max_bytes).ok() != Some(qualification.maximum_bytes)
        || stream.max_age != qualification.maximum_age_millis * 1_000_000
        || u32::try_from(stream.max_msg_size).ok() != Some(qualification.maximum_message_bytes)
        || stream.duplicate_window != mapping.duplicate_window_millis * 1_000_000
        || !stream.deny_delete
        || !stream.deny_purge
        || stream.sealed
        || stream.allow_rollup_hdrs
        || stream.discard_new_per_subject
        || stream.allow_msg_ttl
        || stream.allow_atomic
        || stream.allow_msg_counter
        || stream.allow_msg_schedules
        || stream.subject_transform.is_some()
        || stream.republish.is_some()
        || stream.mirror.is_some()
        || stream.sources.is_some()
    {
        return Err(EventError::PermissionDenied);
    }
    Ok(())
}

#[cfg(test)]
mod tests;
