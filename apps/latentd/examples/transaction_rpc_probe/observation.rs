use latent_wire::{invocation::proto as i, phase4::transaction as t};
use serde::Deserialize;

pub(super) struct Aggregate {
    pub count: u64,
    pub view_version: Vec<u8>,
    pub key_version: Option<Vec<u8>>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Frame {
    ok: Value,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Value {
    count: String,
    #[serde(rename = "view-version")]
    view: Vec<u8>,
    #[serde(rename = "key-version")]
    key: OptionalVersion,
}
#[derive(Deserialize)]
#[serde(rename_all = "lowercase")]
enum OptionalVersion {
    None(()),
    Some(Vec<u8>),
}
pub(super) fn aggregate(value: &i::InvokeResponse) -> Aggregate {
    let Some(i::invoke_response::Result::Success(success)) = value.result.as_ref() else {
        panic!("actual successful aggregate invocation required");
    };
    assert_eq!(
        success.media_type,
        "application/vnd.latent.wit-values.v1+json"
    );
    assert!(success.payload.len() <= 65_536);
    let [frame]: [Frame; 1] = serde_json::from_slice(&success.payload).unwrap();
    let count = frame.ok.count.parse::<u64>().unwrap();
    assert_eq!(count.to_string(), frame.ok.count);
    assert_eq!(frame.ok.view.len(), 67);
    assert!(frame.ok.view.starts_with(b"NV\x02"));
    let key_version = match frame.ok.key {
        OptionalVersion::None(()) => None,
        OptionalVersion::Some(bytes) => {
            assert_eq!(bytes.len(), 67);
            assert!(bytes.starts_with(b"SV\x02"));
            Some(bytes)
        }
    };
    Aggregate {
        count,
        view_version: frame.ok.view,
        key_version,
    }
}
pub(super) fn input(delta: u32, reject: bool) -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!([{"delta":delta,"reject":reject}])).unwrap()
}
pub(super) fn precondition(version: Option<Vec<u8>>) -> t::ExpectedVersion {
    t::ExpectedVersion {
        key: b"aggregate/count".to_vec(),
        expectation: Some(match version {
            Some(bytes) => t::expected_version::Expectation::Version(bytes),
            None => t::expected_version::Expectation::Absent(true),
        }),
    }
}
pub(super) fn check_command<'a>(
    response: &'a t::InvokeCommandResponse,
    publication: &str,
    component: &str,
) -> &'a t::CommandInspection {
    let record = response.command.as_ref().unwrap();
    assert_eq!(record.outcome, t::CommandOutcome::Committed as i32);
    assert!(record.metadata_durable && record.application_state_committed);
    assert!(record.proven_abort.is_none() && record.cleanup_failure.is_none());
    let source = record.source.as_ref().unwrap();
    assert_eq!(source.publication_id, publication);
    assert_eq!(source.component_digest, component);
    let commit = record.commit.as_ref().unwrap();
    assert_eq!(commit.command_id, record.command_id);
    assert_eq!(commit.attempt_id, record.attempt_id);
    assert_eq!(commit.committed_version.len(), 67);
    assert!(commit.committed_version.starts_with(b"NV\x02"));
    assert_eq!(commit.effect_ids.len(), 1);
    record
}

pub(super) fn same_original(original: &t::CommandInspection, recovered: &t::CommandInspection) {
    assert_eq!(recovered.key, original.key);
    assert_eq!(recovered.command_id, original.command_id);
    assert_eq!(recovered.attempt_id, original.attempt_id);
    assert_eq!(recovered.fingerprint_sha256, original.fingerprint_sha256);
    assert_eq!(recovered.outcome, original.outcome);
    assert_eq!(recovered.metadata_durable, original.metadata_durable);
    assert_eq!(
        recovered.application_state_committed,
        original.application_state_committed
    );
    assert_eq!(recovered.source, original.source);
    assert_eq!(recovered.commit, original.commit);
    assert_eq!(recovered.proven_abort, original.proven_abort);
    assert_eq!(recovered.retention, original.retention);
    let (
        Some(t::command_inspection::RetainedResult::Success(first)),
        Some(t::command_inspection::RetainedResult::Success(second)),
    ) = (&original.retained_result, &recovered.retained_result)
    else {
        panic!("actual original and recovered successful results");
    };
    assert_eq!(second.payload, first.payload);
    assert_eq!(second.media_type, first.media_type);
    assert_eq!(
        second.committed_state_version,
        first.committed_state_version
    );
    assert_eq!(second.effect_ids, first.effect_ids);
}
