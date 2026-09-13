use super::*;
use crate::deployment_operations::{DeploymentOperationContext, DeploymentOperationRequest};
use crate::deployments::{persistence::Record, rollouts::table};

/// Freeze the old typed envelope, plan algorithm and receipt algorithm. Neither
/// the original manifests nor their request hashes contain a publication field.
fn old_history(root: &TempRoot, format: u32) -> Vec<RolloutOperationReceipt> {
    let path = root.0.join("catalog.json");
    let mut value: json::Value = json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    value["format_version"] = json::json!(format);
    value["payload"]
        .as_object_mut()
        .unwrap()
        .remove("publication_pins");
    for service in value["payload"]["snapshot"]["services"]
        .as_array_mut()
        .unwrap()
    {
        for revision in service["revisions"].as_array_mut().unwrap() {
            revision.as_object_mut().unwrap().remove("publication");
            revision["attributes"]
                .as_object_mut()
                .unwrap()
                .remove("lsf.publication");
        }
    }
    let mut record: Record = json::from_value(value).unwrap();
    let rows = &mut record.payload.control.as_mut().unwrap().rollouts;
    for row in &mut rows.rows {
        row.plan_version = 1;
        row.status.base.publication = None;
        row.status.candidate.publication = None;
        row.status.plan_digest = table::plan_hash(row).unwrap();
        for stored in &mut rows.receipts {
            stored.receipt.plan_digest = row.status.plan_digest.clone();
            stored.receipt.receipt_digest = table::receipt_hash(&stored.receipt).unwrap();
        }
    }
    let receipts = rows
        .receipts
        .iter()
        .map(|stored| stored.receipt.clone())
        .collect();
    record.checksum = latent_artifacts::content_digest(&json::to_vec(&record.payload).unwrap()).0;
    std::fs::write(path, json::to_vec(&record).unwrap()).unwrap();
    receipts
}

#[test]
fn v3_and_v4_recovery_keep_legacy_receipts_cas_and_exact_rollback_after_coexistence() {
    for format in [3, 4] {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repository = artifacts(&roots[0]);
        let first = publish(&repository, "alice", "base");
        let candidate_value = artifact("different-legacy-component");
        let candidate_release = candidate_value.descriptor.release_digest.clone();
        let second = publish_artifact(&repository, "alice", "candidate", candidate_value);
        let catalog = store(&roots[1], &repository);
        let base = deployment("base", "alice", &release());
        let managed = DeploymentOperationRequest::Apply {
            context: DeploymentOperationContext {
                tenant: TenantId("alice".into()),
                actor: actor(),
                operation_id: "base-apply".into(),
                expected_state_version: 0,
            },
            manifest: base.clone(),
            expected_generation: 0,
        };
        let original_managed = if format == 4 {
            let prepared = run(catalog.prepare_operation(managed.clone())).unwrap();
            let committed = catalog.commit_operation(prepared).unwrap();
            committed.value().durability.as_ref().unwrap();
            Some(committed.value().receipt.clone())
        } else {
            run(catalog.apply(base.clone())).unwrap();
            None
        };
        let mut candidate = deployment("candidate", "alice", &candidate_release);
        candidate.route_weight = 5000;
        let id = RolloutId("legacy-publications".into());
        let start = RolloutRequest::Start {
            context: rollout_context("start", 0),
            spec: StartRolloutSpec {
                id: id.clone(),
                base: DeploymentExpectation {
                    id: base.id.clone(),
                    generation: 1,
                },
                candidate,
                candidate_weights: vec![5000, 10000],
                canary_policy: None,
            },
        };
        execute(&catalog, start.clone());
        execute(
            &catalog,
            RolloutRequest::Change {
                context: rollout_context("complete", 1),
                id: id.clone(),
                command: RolloutCommand::Advance { next_step: 1 },
            },
        );
        let original_selection = catalog.resolve(&target("alice", None), None).unwrap();
        drop(catalog);
        let receipts = old_history(&roots[1], format);

        let catalog = store(&roots[1], &repository);
        assert_eq!(
            catalog.resolve(&target("alice", None), None).unwrap(),
            original_selection
        );
        let stored = catalog
            .get_rollout(&TenantId("alice".into()), &id)
            .unwrap()
            .unwrap();
        assert_eq!(stored.base.publication.as_ref(), Some(&first.id));
        assert_eq!(stored.candidate.publication.as_ref(), Some(&second.id));
        assert_eq!(stored.plan_digest, receipts[0].plan_digest);
        let replay = execute(&catalog, start.clone());
        assert!(replay.replayed);
        assert_eq!(
            replay.receipt.canonical_bytes().unwrap(),
            receipts[0].canonical_bytes().unwrap()
        );
        if let Some(expected) = original_managed {
            let prepared = run(catalog.prepare_operation(managed)).unwrap();
            let replay = catalog.commit_operation(prepared).unwrap();
            assert!(replay.value().replayed);
            assert_eq!(replay.value().receipt, expected);
        }
        let upgraded: json::Value =
            json::from_slice(&std::fs::read(roots[1].0.join("catalog.json")).unwrap()).unwrap();
        assert_eq!(upgraded["format_version"], 5);
        publish(&repository, "alice", "later-base-inventory");
        revoke(&repository, &second);
        drop(catalog);
        drop(repository);

        let repository = artifacts(&roots[0]);
        let catalog = store(&roots[1], &repository);
        let replay = execute(&catalog, start);
        assert!(replay.replayed);
        assert_eq!(
            replay.receipt.canonical_bytes().unwrap(),
            receipts[0].canonical_bytes().unwrap()
        );
        assert_eq!(replay.receipt.base_publication.as_ref(), Some(&first.id));
        assert_eq!(
            replay.receipt.candidate_publication.as_ref(),
            Some(&second.id)
        );
        let rollback = execute(
            &catalog,
            RolloutRequest::Change {
                context: rollout_context("rollback", 2),
                id,
                command: RolloutCommand::Rollback {
                    target_generation: RouteGeneration(1),
                },
            },
        );
        assert_eq!(rollback.receipt.state, RolloutState::RolledBack);
        assert_eq!(
            catalog
                .resolve(&target("alice", None), None)
                .unwrap()
                .publication,
            Some(first.id)
        );
        assert_eq!(run(catalog.list()).unwrap(), vec![base]);
    }
}
