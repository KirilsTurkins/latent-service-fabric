use super::super::metadata::{StoredArtifactDescriptor, StoredContractDescriptor, StoredMetadata};
use super::super::metadata_codec::{MAX_CONTRACT_TYPE_DEPTH, MAX_CONTRACT_TYPE_NODES};
use super::*;
use latent_manifest::__serde_json as serde_json;

#[test]
fn pending_sync_failure_blocks_conflicting_reference_even_after_failed_retry() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let first = artifact("reserved", b"first-content");
    let second = artifact("reserved", b"second-content");
    for _ in 0..2 {
        repo.inject_parent_sync_failure_once();
        assert_eq!(
            block_on(repo.publish(first.clone()))
                .expect_err("sync failure")
                .code,
            PlatformErrorCode::Internal
        );
        assert_eq!(
            block_on(repo.publish(second.clone()))
                .expect_err("pending recovery gate")
                .code,
            PlatformErrorCode::Unavailable
        );
        assert!(!release_dir(temp.path(), &second.descriptor.release_digest).exists());
        assert!(block_on(repo.list(None, 10))
            .expect("no early visibility")
            .entries
            .is_empty());
    }
    block_on(repo.publish(first.clone())).expect("identical retry reconciles pending release");
    assert_eq!(
        block_on(repo.publish(second))
            .expect_err("reference remains unique")
            .code,
        PlatformErrorCode::AlreadyExists
    );
    // Recovery must release the gate, not permanently disable all mutation.
    block_on(repo.publish(artifact("unrelated", b"unrelated"))).expect("gate reopened");
    drop(repo);
    let reopened = repository(temp.path());
    assert_eq!(
        block_on(reopened.fetch(&first.descriptor.release_digest)).expect("reopen"),
        first
    );
    assert_eq!(
        block_on(reopened.list(None, 10))
            .expect("list")
            .entries
            .len(),
        2
    );
}

#[test]
fn pending_sync_failure_preserves_entry_and_byte_capacity_across_reopen() {
    for byte_limit in [false, true] {
        let temp = TempRoot::new();
        let first = artifact("capacity-one", b"capacity-one");
        let second = artifact("capacity-two", b"capacity-two");
        let descriptor_bytes =
            serde_json::to_vec(&StoredArtifactDescriptor::from(&first.descriptor))
                .expect("serialized descriptor")
                .len();
        let accounted = super::super::index_accounted_bytes(descriptor_bytes).expect("accounting");
        let config = DirectoryArtifactRepositoryConfig {
            max_index_entries: if byte_limit { 10 } else { 1 },
            max_index_bytes: if byte_limit {
                accounted
            } else {
                64 * 1024 * 1024
            },
            ..DirectoryArtifactRepositoryConfig::default()
        };
        let repo = DirectoryArtifactRepository::open(temp.path(), config).expect("open");
        repo.inject_parent_sync_failure_once();
        assert_eq!(
            block_on(repo.publish(first.clone()))
                .expect_err("sync failure")
                .code,
            PlatformErrorCode::Internal
        );
        assert_eq!(
            block_on(repo.publish(second.clone()))
                .expect_err("pending blocks mutation")
                .code,
            PlatformErrorCode::Unavailable
        );
        assert_eq!(
            fs::read_dir(temp.path().join("releases"))
                .expect("directories")
                .count(),
            1
        );
        // Recover without an identical retry, using only durable storage.
        drop(repo);
        let reopened =
            DirectoryArtifactRepository::open(temp.path(), config).expect("reopen at limit");
        assert_eq!(
            block_on(reopened.fetch(&first.descriptor.release_digest)).expect("recovered"),
            first
        );
        assert_eq!(
            block_on(reopened.publish(second))
                .expect_err("capacity still enforced")
                .code,
            PlatformErrorCode::ResourceExhausted
        );
        drop(reopened);
        assert!(DirectoryArtifactRepository::open(temp.path(), config).is_ok());
    }
}

#[test]
fn recovery_gate_preserves_reads_of_prior_complete_state() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let prior = artifact("prior", b"prior-component");
    block_on(repo.publish(prior.clone())).expect("prior release");
    repo.inject_parent_sync_failure_once();
    block_on(repo.publish(artifact("pending", b"pending"))).expect_err("sync failure");
    assert_eq!(
        block_on(repo.fetch(&prior.descriptor.release_digest)).expect("prior is readable"),
        prior
    );
    assert_eq!(
        block_on(repo.list(None, 10)).expect("prior list").entries,
        vec![prior.descriptor]
    );
    drop(repo);
    assert_eq!(
        block_on(repository(temp.path()).list(None, 10))
            .expect("recovered list")
            .entries
            .len(),
        2
    );
}

fn nested_type(kind: &str, wrappers: usize) -> ValueType {
    let mut value = ValueType::String;
    for _ in 0..wrappers {
        value = match kind {
            "list" => ValueType::List(Box::new(value)),
            "option" => ValueType::Option(Box::new(value)),
            "result-ok" => ValueType::Result {
                ok: Some(Box::new(value)),
                error: None,
            },
            "result-error" => ValueType::Result {
                ok: None,
                error: Some(Box::new(value)),
            },
            "tuple" => ValueType::Tuple(vec![value]),
            "future" => ValueType::Future(Box::new(value)),
            "stream" => ValueType::Stream(Box::new(value)),
            _ => unreachable!(),
        };
    }
    value
}

#[test]
fn contract_type_depth_boundary_round_trips_or_rejects_before_persistence() {
    for kind in [
        "list",
        "option",
        "result-ok",
        "result-error",
        "tuple",
        "future",
        "stream",
    ] {
        for wrappers in [
            MAX_CONTRACT_TYPE_DEPTH - 2,
            MAX_CONTRACT_TYPE_DEPTH - 1,
            MAX_CONTRACT_TYPE_DEPTH,
            256,
        ] {
            let temp = TempRoot::new();
            let repo = repository(temp.path());
            let mut value = artifact(kind, b"nested-component");
            let function = &mut value.contracts[0].interfaces[0].functions[0];
            function.parameters[0].value_type = nested_type(kind, wrappers);
            function.results[0].value_type = nested_type(kind, wrappers);
            let digest = value.descriptor.release_digest.clone();
            if wrappers < MAX_CONTRACT_TYPE_DEPTH {
                block_on(repo.publish(value.clone())).expect("supported boundary publishes");
                assert_eq!(
                    block_on(repo.fetch(&digest)).expect("fetch boundary"),
                    value
                );
                drop(repo);
                assert_eq!(
                    block_on(repository(temp.path()).fetch(&digest)).expect("reopen boundary"),
                    value
                );
            } else {
                assert_eq!(
                    block_on(repo.publish(value)).expect_err("depth limit").code,
                    PlatformErrorCode::ResourceExhausted
                );
                assert!(block_on(repo.list(None, 10))
                    .expect("list")
                    .entries
                    .is_empty());
                assert!(!release_dir(temp.path(), &digest).exists());
                assert_eq!(
                    fs::read_dir(temp.path().join(".tmp"))
                        .expect("staging")
                        .count(),
                    0
                );
                drop(repo);
                assert!(block_on(repository(temp.path()).list(None, 10))
                    .expect("empty reopen")
                    .entries
                    .is_empty());
            }
        }
    }
}

#[test]
fn contract_type_node_budget_covers_aggregate_parameters_and_results() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let mut value = artifact("many-nodes", b"many-nodes");
    let function = &mut value.contracts[0].interfaces[0].functions[0];
    function.parameters[0].value_type =
        ValueType::Tuple(vec![ValueType::String; MAX_CONTRACT_TYPE_NODES]);
    let digest = value.descriptor.release_digest.clone();
    assert_eq!(
        block_on(repo.publish(value)).expect_err("node budget").code,
        PlatformErrorCode::ResourceExhausted
    );
    assert!(!release_dir(temp.path(), &digest).exists());
    assert!(block_on(repo.list(None, 10))
        .expect("list")
        .entries
        .is_empty());
}

#[test]
fn persisted_contract_types_obey_the_same_structural_limit() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let mut value = artifact("persisted-depth", b"persisted-depth");
    block_on(repo.publish(value.clone())).expect("valid publish");
    drop(repo);
    value.contracts[0].interfaces[0].functions[0].parameters[0].value_type =
        nested_type("option", MAX_CONTRACT_TYPE_DEPTH);
    // Bypass the production encoder only to model corrupt persisted input.
    let stored = StoredMetadata {
        descriptor: StoredArtifactDescriptor::from(&value.descriptor),
        contracts: value
            .contracts
            .iter()
            .map(StoredContractDescriptor::from)
            .collect(),
    };
    let bytes = serde_json::to_vec(&stored).expect("serialize corrupt fixture");
    fs::write(
        release_dir(temp.path(), &value.descriptor.release_digest).join("metadata.json"),
        bytes,
    )
    .expect("replace persisted metadata");
    assert_eq!(
        DirectoryArtifactRepository::open(
            temp.path(),
            DirectoryArtifactRepositoryConfig::default()
        )
        .expect_err("bounded reopen rejects unsupported type depth")
        .code,
        PlatformErrorCode::ResourceExhausted
    );
}
