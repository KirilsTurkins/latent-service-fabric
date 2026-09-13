use super::*;
use sha2::{Digest, Sha256};

#[test]
fn decoded_control_bindings_fail_closed_even_with_recomputed_outer_checksum() {
    for mutation in 0..4 {
        let root = TempRoot::new();
        let releases = Arc::new(Releases::default());
        let store = open(&root, &releases);
        let request = setup(&store, &releases);
        execute(&store, request);
        drop(store);
        let path = root.0.join("catalog.json");
        let mut record: super::super::super::persistence::Record =
            json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        let data = &mut record.payload.control.as_mut().unwrap().rollouts;
        match mutation {
            0 => {
                data.rows[0].status.plan_digest =
                    "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                        .parse()
                        .unwrap();
            }
            1 => data.rows[0].status.state_version = u64::MAX,
            2 => data.receipts[0].sequence += 1,
            3 => data.rows[0].cohort[0].manifest_digest = "invalid-digest".into(),
            _ => unreachable!(),
        }
        record.checksum = format!(
            "sha256:{:x}",
            Sha256::digest(json::to_vec(&record.payload).unwrap())
        );
        std::fs::write(path, json::to_vec(&record).unwrap()).unwrap();
        assert_code(
            run(Store::open(&root.0, releases, Limits::default())),
            Code::CorruptArtifact,
        );
    }
}

#[test]
fn typed_request_measurement_rejects_collection_capacity_before_normalization() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let request = setup(&store, &releases);
    let before = std::fs::read(root.0.join("catalog.json")).unwrap();
    for kind in 0..3 {
        let mut request = request.clone();
        let RolloutRequest::Start { spec, .. } = &mut request else {
            unreachable!()
        };
        match kind {
            0 => spec.candidate.placement.zones = Vec::with_capacity(MAX_REQUEST_BYTES),
            1 => spec.candidate.grants = Vec::with_capacity(1024),
            2 => {
                for index in 0..1024 {
                    spec.candidate
                        .metadata
                        .labels
                        .insert(index.to_string(), String::new());
                }
            }
            _ => unreachable!(),
        }
        assert!(request.retained_bytes() > MAX_REQUEST_BYTES);
        assert_code(run(store.prepare_rollout(request)), Code::ResourceExhausted);
    }
    assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
}

#[test]
fn pages_reject_other_filter_new_transaction_and_reopened_owner() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let first = setup(&store, &releases);
    execute(&store, first);
    execute(&store, change("abort", 1, RolloutCommand::Abort));
    let old = releases.add("second-service-old");
    let next = releases.add("second-service-new");
    for release in [&old, &next] {
        releases
            .values
            .write()
            .unwrap()
            .get_mut(release)
            .unwrap()
            .manifest
            .metadata
            .name = "other-service".into();
    }
    let mut base = deployment("second-base", "alice", &old);
    base.service.0 = "other-service".into();
    run(store.apply(base.clone())).unwrap();
    let generation = store.read_catalog().versions[&base.id];
    let mut candidate = deployment("second-candidate", "alice", &next);
    candidate.service.0 = base.service.0.clone();
    candidate.route_weight = 2500;
    execute(
        &store,
        RolloutRequest::Start {
            context: context("second-start", 0),
            spec: StartRolloutSpec {
                id: RolloutId("other-rollout".into()),
                base: DeploymentExpectation {
                    id: base.id,
                    generation,
                },
                candidate,
                candidate_weights: vec![2500, 10000],
                canary_policy: None,
            },
        },
    );
    let request = RolloutPageRequest {
        tenant: alice(),
        service: None,
        state: None,
        cursor: None,
        limit: 1,
        maximum_bytes: MAX_PAGE_BYTES,
    };
    let page = store.list_rollouts(request.clone()).unwrap();
    let cursor = page.next_cursor.clone().expect("two rows require a cursor");
    let mut continuation = request.clone();
    continuation.cursor = Some(cursor);
    assert_eq!(
        store
            .list_rollouts(continuation.clone())
            .unwrap()
            .rollouts
            .len(),
        1
    );
    let mut wrong = continuation.clone();
    wrong.tenant.0 = "bob".into();
    assert_code(store.list_rollouts(wrong), Code::StateConflict);
    drop(store);
    let store = open(&root, &releases);
    assert_code(store.list_rollouts(continuation), Code::StateConflict);
    let page = store.list_rollouts(request.clone()).unwrap();
    let mut continuation = request;
    continuation.cursor = page.next_cursor;
    execute(
        &store,
        RolloutRequest::Change {
            context: context("second-pause", 1),
            id: RolloutId("other-rollout".into()),
            command: RolloutCommand::Pause,
        },
    );
    assert_code(store.list_rollouts(continuation), Code::StateConflict);
}
