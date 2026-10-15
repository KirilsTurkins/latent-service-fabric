//! Real affine retirement, persisted abort rows and reopened original results.
use latent_commit::atomic::{
    self, AdmissionDecision, AdmissionInput, AdmittedCommand, AtomicError, CommandRecord,
    CommandTime, CompleteEnvelope, DurableResult, Outcome, PreparedAdmission, PreparedDisposition,
    ReplayPolicy, ResultPolicy, SourceIdentity,
};
use latent_core::{
    transaction_contract::{CommandFingerprint, CommandKey, Value},
    PlatformErrorCode, StateNamespaceId, TenantId,
};
use latent_rpc::{phase4 as contract, transaction::v1 as t};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, Family, RowKey, RowMutation, StoreLimits},
    namespace::{
        namespace_record_key, NamespacePins, NamespaceQuota, NamespaceRecord, NamespaceStatus,
        NamespaceVersion,
    },
};
use std::{fs::OpenOptions, path::Path};

pub(super) const KNOWN: [PlatformErrorCode; 17] = [
    PlatformErrorCode::GuestTrap,
    PlatformErrorCode::ResourceExhausted,
    PlatformErrorCode::Cancelled,
    PlatformErrorCode::DeadlineExceeded,
    PlatformErrorCode::StateConflict,
    PlatformErrorCode::Unavailable,
    PlatformErrorCode::PermissionDenied,
    PlatformErrorCode::Unauthenticated,
    PlatformErrorCode::InvalidArgument,
    PlatformErrorCode::NotFound,
    PlatformErrorCode::AlreadyExists,
    PlatformErrorCode::IncompatibleContract,
    PlatformErrorCode::DependencyFailed,
    PlatformErrorCode::CorruptArtifact,
    PlatformErrorCode::RouteUnavailable,
    PlatformErrorCode::AdmissionRejected,
    PlatformErrorCode::Internal,
];
pub(super) const UNKNOWN: [&str; 4] = [
    "future-host-fault",
    "guest_trap",
    "guest-trap-v2",
    "conflict",
];

pub(super) fn time(unix_millis: u64) -> CommandTime {
    CommandTime {
        unix_millis,
        continuity_proven: true,
    }
}
fn schema() -> String {
    format!("sha256:{}", "4".repeat(64))
}
fn open(path: &Path) -> EmbeddedStore {
    EmbeddedStore::open_file(
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)
            .unwrap(),
        StoreLimits {
            maximum_key_bytes: 4096,
            maximum_value_bytes: 2 * 1024 * 1024,
            maximum_batch_rows: 1024,
            ..Default::default()
        },
    )
    .unwrap()
}
pub(super) struct Original {
    directory: tempfile::TempDir,
    pub store: EmbeddedStore,
    pub key: CommandKey,
    pub claim: AdmittedCommand,
}
pub(super) fn pending() -> Original {
    let directory = tempfile::tempdir().unwrap();
    let store = open(&directory.path().join("original.redb"));
    let namespace = NamespaceRecord {
        tenant: TenantId("tenant".into()),
        id: StateNamespaceId("aggregate".into()),
        version: NamespaceVersion {
            incarnation: 1,
            generation: 1,
        },
        state_schema: schema(),
        status: NamespaceStatus::Active,
        quota: NamespaceQuota::default(),
        pins: NamespacePins::default(),
    };
    store
        .apply(AtomicBatch {
            expectations: Vec::new(),
            mutations: vec![RowMutation {
                key: RowKey {
                    family: Family::Namespace,
                    key: namespace_record_key(&namespace.tenant, &namespace.id).unwrap(),
                },
                value: Some(namespace.encode().unwrap()),
            }],
        })
        .unwrap();
    let key = CommandKey {
        tenant: "tenant".into(),
        namespace: "aggregate".into(),
        incarnation: "1".into(),
        recovery_scope: "subject:alice".into(),
        operation: "update".into(),
        entity: None,
        client_key: "original-fault".into(),
    };
    let input = AdmissionInput {
        key: key.clone(),
        fingerprint: CommandFingerprint {
            input_format: "lsf-wit-values-v1".into(),
            input: Value {
                bytes: b"delta=1".to_vec(),
                media_type: "application/octet-stream".into(),
                metadata: Vec::new(),
            },
            expected_versions: Vec::new(),
        },
        source: SourceIdentity {
            publication: "publication".into(),
            revision: "revision-1".into(),
            release_digest: format!("sha256:{}", "1".repeat(64)),
            component_digest: format!("sha256:{}", "2".repeat(64)),
            contract_digest: format!("sha256:{}", "3".repeat(64)),
            route_generation: 1,
            state_schema: schema(),
            input_format: "lsf-wit-values-v1".into(),
            result_format: "lsf-wit-values-v1".into(),
        },
        result_read_policy: "aggregate/read-v1".into(),
        result_policy: ResultPolicy {
            replay: ReplayPolicy::Full,
            maximum_result_bytes: 1024,
            result_millis: 1000,
            identity_millis: 2000,
            maximum_attempts: 3,
        },
        inbox: None,
        owner_epoch: 1,
    };
    let AdmissionDecision::New(prepared) =
        PreparedAdmission::prepare(&store.snapshot().unwrap(), input, time(100), |_, _| Ok(()))
            .unwrap()
    else {
        panic!("original host claim absent");
    };
    let claim = prepared.publish(&store, || Ok(())).unwrap();
    Original {
        directory,
        store,
        key,
        claim,
    }
}
pub(super) struct StoredAbort {
    _directory: tempfile::TempDir,
    pub store: EmbeddedStore,
    pub key: CommandKey,
    pub command: CommandRecord,
    pub result: DurableResult,
}
pub(super) fn aborted(code: &str) -> StoredAbort {
    let Original {
        directory,
        store,
        key,
        claim,
    } = pending();
    let original = claim.record().clone();
    let retirement = claim.retirement();
    let physical = claim.physical_work().unwrap();
    drop(claim);
    assert!(matches!(
        retirement.proven_noncommit(),
        Err(AtomicError::RecoveryRequired)
    ));
    physical.retire();
    let envelope = CompleteEnvelope::technical_abort(
        &store.snapshot().unwrap(),
        retirement.proven_noncommit().unwrap(),
        code.into(),
        time(101),
    )
    .unwrap();
    let PreparedDisposition::Confirmed { command, result } = envelope.publish(&store, |effects| {
        assert!(effects.is_empty());
        Ok(())
    }) else {
        panic!("actual metadata-only abort was not durably confirmed");
    };
    assert_eq!(command.id(), original.id());
    assert_eq!(command.transaction_id(), original.transaction_id());
    assert_eq!(command.source(), original.source());
    assert_eq!(command.outcome(), Outcome::Aborted);
    assert!(command.abort_proof().is_some());
    assert_eq!(result.code(), Some(code));
    result.verify(&command).unwrap();
    drop(store);
    let store = open(&directory.path().join("original.redb"));
    let (reopened, retained) =
        atomic::inspect(&store.snapshot().unwrap(), &key, time(102), |_, _| Ok(())).unwrap();
    let retained = retained.unwrap();
    assert_eq!(reopened, *command);
    assert_eq!(retained, *result);
    retained.verify(&reopened).unwrap();
    StoredAbort {
        _directory: directory,
        store,
        key,
        command: reopened,
        result: retained,
    }
}
pub(super) fn lookup() -> contract::Request {
    t::LookupCommandRequest::default().into()
}
