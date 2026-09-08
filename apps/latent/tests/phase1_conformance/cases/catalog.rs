use super::{idle, payload};
use crate::{
    evidence::Evidence,
    fixtures::{path, Fixtures},
    harness::Harness,
};
use latent_testkit::conformance::ProcessSample;
use serde_json::json;

pub async fn empty(harness: &mut Harness, evidence: &mut Evidence) -> ProcessSample {
    evidence.begin("empty-readiness");
    harness.start().await;
    let ready = harness.ready().await;
    assert_eq!(ready["cacheSummary"]["entries"], "0");
    let releases = harness
        .call("tests", &["release", "list"], 0, "success")
        .await;
    assert_eq!(releases["data"]["releases"], json!([]));
    let deployments = harness
        .call("tests", &["deployment", "list"], 0, "success")
        .await;
    assert_eq!(deployments["data"]["deployments"], json!([]));
    let sample = harness.sample("empty").await;
    idle(&sample);
    evidence.passed(
        harness,
        json!({"ready":ready,"releases":releases,
        "deployments":deployments,"sample":sample}),
    );
    sample
}

pub async fn dormant(
    harness: &mut Harness,
    evidence: &mut Evidence,
    fixtures: &Fixtures,
    empty: &ProcessSample,
) {
    evidence.begin("dormant-catalog");
    let mut results = Vec::new();
    for (id, package) in ["generic", "echo", "capabilities", "dormant"]
        .into_iter()
        .zip(fixtures.packages())
    {
        let release = harness
            .call(
                package.profile(),
                &[
                    "release",
                    "publish",
                    "--manifest",
                    path(&package.manifest),
                    "--component",
                    path(&package.component),
                    "--contracts",
                    path(&package.contracts),
                ],
                0,
                "success",
            )
            .await;
        assert_eq!(release["data"]["release"]["digest"], package.digest);
        let deployment = package.deployment(id);
        let applied = harness
            .call(
                package.profile(),
                &[
                    "deployment",
                    "apply",
                    path(&deployment),
                    "--expected-generation",
                    "0",
                ],
                0,
                "success",
            )
            .await;
        results.push(json!({"release":release,"deployment":applied}));
    }
    let sample = harness.sample("dormant").await;
    idle(&sample);
    for field in [
        "entries",
        "sourceBytes",
        "metadataBytes",
        "compiledImageBytes",
        "preparing",
        "misses",
    ] {
        assert_eq!(
            sample.inventory["cacheSummary"][field], "0",
            "no preparation during catalog work: {field}"
        );
    }
    assert_eq!(
        sample.process.task_count, empty.process.task_count,
        "small dormant catalog adds no helper threads"
    );
    assert_eq!(sample.process.identity, empty.process.identity);
    let observed = json!({"releaseCount":4,"deploymentCount":4,"results":results,"sample":sample});
    // The first observation remains the actual empty child, not the test runner.
    evidence.report.samples.push(ProcessSample {
        sequence: empty.sequence,
        node_instance: empty.node_instance,
        phase: empty.phase.clone(),
        process: empty.process.clone(),
        inventory: empty.inventory.clone(),
        sample_started_micros: empty.sample_started_micros,
        sample_finished_micros: empty.sample_finished_micros,
    });
    evidence.report.samples.push(sample);
    evidence.passed(harness, observed);
}

pub async fn tenants(harness: &mut Harness, evidence: &mut Evidence, fixtures: &Fixtures) {
    evidence.begin("tenant-isolation");
    assert_eq!(fixtures.generic.service, fixtures.echo.service);
    assert_ne!(fixtures.generic.digest, fixtures.echo.digest);
    let input = fixtures.echo.input("echo.json", &json!(["other tenant"]));
    let echo = harness
        .invoke(
            &fixtures.echo,
            "echo",
            "examples-completed",
            &input,
            &[],
            (0, "success"),
        )
        .await;
    assert_eq!(payload(&echo), json!([{"ok":"other tenant"}]));
    assert_eq!(
        echo["data"]["resolvedRevision"]["releaseDigest"],
        fixtures.echo.digest
    );
    let hidden_status = harness
        .call(
            "tests",
            &["activation", "get", "examples-completed"],
            6,
            "not-found",
        )
        .await;
    let hidden_cancel = harness
        .call(
            "examples",
            &["activation", "cancel", "fresh-first"],
            6,
            "not-found",
        )
        .await;
    let own_status = harness
        .call(
            "examples",
            &["activation", "get", "examples-completed"],
            0,
            "success",
        )
        .await;
    assert_eq!(own_status["data"]["terminalState"], "completed");
    let mut scopes = Vec::new();
    for package in [&fixtures.generic, &fixtures.echo] {
        let routes = harness
            .call(package.profile(), &["route", "get"], 0, "success")
            .await;
        let snapshot = &routes["data"]["snapshot"];
        assert_eq!(snapshot["tenant"], package.tenant);
        let rows = snapshot["services"].as_array().expect("scoped routes");
        assert!(rows.iter().all(|row| row["tenant"] == package.tenant));
        let shared = rows
            .iter()
            .filter(|row| row["service"] == package.service)
            .collect::<Vec<_>>();
        assert!(!shared.is_empty());
        assert!(shared.iter().all(|row| row["revisions"]
            .as_array()
            .expect("revisions")
            .iter()
            .all(|revision| revision["releaseDigest"] == package.digest)));
        let other = if package.tenant == "tests" {
            &fixtures.echo
        } else {
            &fixtures.generic
        };
        let foreign_release = harness
            .call(
                package.profile(),
                &["release", "get", &other.digest],
                6,
                "not-found",
            )
            .await;
        scopes.push(json!({"routes":routes,"foreignRelease":foreign_release}));
    }
    evidence.passed(
        harness,
        json!({"echo":echo,"hiddenStatus":hidden_status,
        "hiddenCancel":hidden_cancel,"ownStatus":own_status,"scopes":scopes}),
    );
}
