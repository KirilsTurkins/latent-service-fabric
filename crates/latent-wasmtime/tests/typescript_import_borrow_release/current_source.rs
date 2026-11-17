//! Same-workflow input proof. This is not the historical OWN prerequisite.
use serde_json::Value;
use std::path::Path;

use super::{digest, read, PROFILE};

fn bytes_match(value: &Value, bytes: &[u8]) {
    assert_eq!(
        value["bytes"].as_u64(),
        Some(u64::try_from(bytes.len()).unwrap())
    );
    assert_eq!(value["sha256"], digest(bytes));
}

fn git_identity(value: &Value) -> &str {
    let identity = value.as_str().expect("current source identity required");
    assert_eq!(identity.len(), 40);
    assert!(identity
        .bytes()
        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)));
    identity
}

pub(super) fn validate(prepared: &Path, observed: &Value) -> Vec<u8> {
    assert_eq!(observed["profile"], PROFILE);
    assert_eq!(observed["status"], "passed");
    assert_eq!(observed["sourceUnchanged"], true);
    assert_eq!(observed["engineQualificationStatus"], "unknown");
    assert_eq!(
        observed["enginePrerequisiteScope"],
        "same-workflow-source-bound-import-engine"
    );
    assert_eq!(observed["canonicalSignedExecution"], "not-yet-run");
    let directory = prepared.join("engine-qualification");
    let proof_raw = read(&directory.join("CURRENT-ENGINE.json"), 4 * 1024 * 1024);
    let proof: Value = serde_json::from_slice(&proof_raw).unwrap();
    assert_eq!(
        proof["schemaVersion"],
        "latent.typescript.borrow-current-engine.v1"
    );
    assert_eq!(proof["status"], "source-built");
    assert_eq!(proof["scope"], "same-workflow-source-bound-import-engine");
    assert_eq!(proof["qualification"], "unknown");
    assert_eq!(proof["apiSupport"], "not-evaluated");
    let commit = git_identity(&proof["sourceCommit"]);
    let tree = git_identity(&proof["sourceTree"]);
    assert_eq!(observed["sourceCommit"], commit);
    assert_eq!(observed["engineSourceCommit"], commit);
    assert_eq!(observed["sourceTree"], tree);
    assert_eq!(observed["engineEvidenceDigest"], digest(&proof_raw));
    let origin = &proof["workflowOrigin"];
    assert_eq!(
        origin["GITHUB_REPOSITORY"],
        "KirilsTurkins/latent-service-fabric"
    );
    assert_eq!(origin["GITHUB_EVENT_NAME"], "workflow_dispatch");
    assert_eq!(origin["GITHUB_REF"], "refs/heads/development");
    assert_eq!(origin["GITHUB_WORKFLOW_REF"], "KirilsTurkins/latent-service-fabric/.github/workflows/typescript-guest.yml@refs/heads/development");
    assert_eq!(origin["GITHUB_SHA"], commit);
    assert_eq!(origin["GITHUB_WORKFLOW_SHA"], commit);
    assert_eq!(origin["GITHUB_RUN_ATTEMPT"], "1");
    assert_eq!(std::env::var("GITHUB_SHA").as_deref(), Ok(commit));
    let run_id = origin["GITHUB_RUN_ID"]
        .as_str()
        .expect("current workflow run identity required");
    assert!(!run_id.is_empty() && run_id.len() <= 20 && !run_id.starts_with('0'));
    assert!(run_id.bytes().all(|byte| byte.is_ascii_digit()));
    assert_eq!(std::env::var("GITHUB_RUN_ID").as_deref(), Ok(run_id));

    let core = read(
        &prepared.join("selected-runtime-engine/engine.wasm"),
        64 * 1024 * 1024,
    );
    let input = read(&directory.join("engine-input.json"), 65536);
    let splicer = read(&directory.join("splicer-input.json"), 65536);
    let build = read(&directory.join("engine-build.json"), 4 * 1024 * 1024);
    let compilation = read(&directory.join("engine-compilation.json"), 4 * 1024 * 1024);
    let derivation = read(&directory.join("source-derivation.json"), 4 * 1024 * 1024);
    let products = &proof["engineProducts"];
    for (name, bytes) in [
        ("engine.wasm", core.as_slice()),
        ("engine-input.json", input.as_slice()),
        ("engine-build.json", build.as_slice()),
        ("engine-compilation.json", compilation.as_slice()),
        ("source-derivation.json", derivation.as_slice()),
    ] {
        bytes_match(&products[name], bytes);
    }
    assert_eq!(observed["engineInputDigest"], digest(&input));
    assert_eq!(proof["splicer"]["inputDigest"], digest(&splicer));
    let envelope: Value = serde_json::from_slice(&input).unwrap();
    assert_eq!(
        envelope["profile"],
        "spidermonkey-activation-promises-clocks-imports-v1"
    );
    assert_eq!(envelope["coreDigest"], digest(&core));
    assert_eq!(
        envelope["coreBytes"].as_u64(),
        Some(u64::try_from(core.len()).unwrap())
    );
    assert_eq!(envelope["compilerSplicerInputDigest"], digest(&splicer));
    assert_eq!(envelope["buildReceiptDigest"], digest(&compilation));
    assert_eq!(envelope["sourceDerivationDigest"], digest(&derivation));
    assert_eq!(envelope["qualification"], "unknown");
    assert_eq!(envelope["apiSupport"], "not-evaluated");
    assert_eq!(envelope["inputTrust"], "operator-asserted");
    assert_ne!(
        observed["engineInputDigest"],
        "sha256:18557c70748fd27daefa296d7bcc156533f5f943317489c3a256e16b2c78918b"
    );
    proof_raw
}
