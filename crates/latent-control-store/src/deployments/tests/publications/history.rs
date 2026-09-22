use super::*;
use crate::deployments::{persistence::Record, rollouts::table};

#[test]
fn obsolete_envelopes_and_rollout_plans_are_rejected_without_rewriting_history() {
    for format in [3, 4, 5] {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repository = artifacts(&roots[0]);
        let first = publish(&repository, "alice", "base");
        let source = artifact("different-component");
        let component = source.descriptor.release_digest.clone();
        let second = publish_artifact(&repository, "alice", "candidate", source);
        let catalog = store(&roots[1], &repository);
        let mut base = deployment("base", "alice", &release());
        base.publication = Some(first.id);
        run(catalog.apply(base.clone())).unwrap();
        let mut candidate = deployment("candidate", "alice", &component);
        candidate.publication = Some(second.id);
        candidate.route_weight = 5000;
        execute(
            &catalog,
            RolloutRequest::Start {
                context: rollout_context("start", 0),
                spec: StartRolloutSpec {
                    id: RolloutId("obsolete-plan".into()),
                    base: DeploymentExpectation {
                        id: base.id,
                        generation: 1,
                    },
                    candidate,
                    candidate_weights: vec![5000, 10000],
                    canary_policy: None,
                },
            },
        );
        drop(catalog);
        let path = roots[1].0.join("catalog.json");
        let mut value: json::Value = json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        value["format_version"] = json::json!(format);
        if format < 5 {
            value["payload"]
                .as_object_mut()
                .unwrap()
                .remove("publication_pins");
        }
        let mut record: Record = json::from_value(value).unwrap();
        let table = &mut record.payload.control.as_mut().unwrap().rollouts;
        let row = &mut table.rows[0];
        row.plan_version = 1;
        assert!(table::plan_hash(row).is_err());
        // Manufacture a valid old hash solely as rejected input; production has no v1 algorithm.
        let status = &row.status;
        let mut old_plan = json::json!({"version":1,"tenant":status.tenant.0,"rollout":status.id.0,
            "base":row.base_manifest,"candidate":row.candidate_manifest,"weights":status.candidate_weights,
            "basePackage":status.base.package.as_ref().map(latent_core::PackageDigest::as_str),
            "candidatePackage":status.candidate.package.as_ref().map(latent_core::PackageDigest::as_str)});
        if let Some(target) = &status.rollback_target {
            old_plan["rollbackTarget"] = json::to_value(target).unwrap();
        }
        row.status.plan_digest = crate::rollouts::codec::hash(&json::to_vec(&old_plan).unwrap());
        for stored in &mut table.receipts {
            stored.receipt.plan_digest = row.status.plan_digest.clone();
            stored.receipt.receipt_digest = table::receipt_hash(&stored.receipt).unwrap();
        }
        record.checksum =
            latent_artifacts::content_digest(&json::to_vec(&record.payload).unwrap()).0;
        let bytes = json::to_vec(&record).unwrap();
        std::fs::write(&path, &bytes).unwrap();
        assert!(run(Store::open_with_catalog(
            &roots[1].0,
            repository.clone(),
            Limits::default(),
            repository.lifecycle_authority(),
            super::super::lifecycle::profile("47.0.4")
        ))
        .is_err());
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
}
