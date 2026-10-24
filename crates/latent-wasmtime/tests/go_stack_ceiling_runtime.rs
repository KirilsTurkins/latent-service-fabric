//! Source-only seven-attempt v7 programme; actual compilation/execution pending.
#![cfg(all(
    feature = "development-test-host",
    target_os = "linux",
    target_arch = "x86_64"
))]
#[path = "local_service/component.rs"]
#[allow(dead_code)]
mod component;
#[path = "local_service/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "go_stack_ceiling_runtime/mapping.rs"]
mod mapping;
#[path = "guest_sdk/package.rs"]
#[allow(dead_code)]
mod package;
#[path = "local_service/packages.rs"]
#[allow(dead_code)]
mod packages;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use fixture::Fixture;
use latent_activation::ActivationOutcome;
use latent_artifacts::ArtifactRepository;
use latent_control_store::DeploymentStore;
use latent_core::{DeploymentId, PlatformErrorCode, ResourceBudget, TenantId};
use latent_packaging::PackageBundle;
use latent_signing::{BuildRecipe, GO_CAPSULE_BUILD_TYPE};
use serde_json::{json, Value};
use std::path::Path;

const FUEL: u64 = 1_000_000_000;
const MEMORY: u64 = 64 * 1024 * 1024;
const SOURCE: &[u8] =
    include_bytes!("../../../sdk/go-guest/runtime/stack-ceiling-conformance/main.go");
const WORLD: &[u8] =
    include_bytes!("../../../sdk/go-guest/runtime/stack-ceiling-conformance/world.wit");

struct Variant {
    name: &'static str,
    bundle: PackageBundle,
    observation: latent_signing::BuildObservation,
    mapping: mapping::Mapping,
    budget: ResourceBudget,
}

fn budget(value: &ResourceBudget) -> Value {
    json!({"cpuFuel":value.cpu_fuel,"memoryBytes":value.memory_bytes,
        "wallTimeLimitMillis":value.wall_time_limit_millis,"childCalls":value.child_calls,
        "outboundRequests":value.outbound_requests,"stateReadBytes":value.state_read_bytes,
        "stateWriteBytes":value.state_write_bytes,"blobReadBytes":value.blob_read_bytes,
        "blobWriteBytes":value.blob_write_bytes,"logBytes":value.log_bytes,"effectCount":value.effect_count})
}

fn load(name: &'static str, initializer_cap: bool) -> Variant {
    let path = package::input(name);
    let mut expected = SOURCE.to_vec();
    if initializer_cap {
        let text = std::str::from_utf8(SOURCE).unwrap();
        assert_eq!(
            text.matches("const initializerDepth uint32 = 2\n").count(),
            1
        );
        expected = text
            .replace(
                "const initializerDepth uint32 = 2\n",
                "const initializerDepth uint32 = 96\n",
            )
            .into_bytes();
    }
    let app = path.parent().unwrap().join("applications").join(name);
    assert_eq!(std::fs::read(app.join("src/main.go")).unwrap(), expected);
    assert_eq!(std::fs::read(app.join("wit/world.wit")).unwrap(), WORLD);
    let bundle = package::bundle(&path);
    let observation = package::observation(name);
    assert_eq!(observation.build_type, GO_CAPSULE_BUILD_TYPE);
    let BuildRecipe::GoCapsule(recipe) = &observation.parameters else {
        panic!("actual Go builder observation required")
    };
    assert_eq!(recipe.runtime, "go-component-activation-v7");
    assert!(recipe.locked && !recipe.ambient_wasi);
    let component = std::fs::read(path.join("component.wasm")).unwrap();
    assert_eq!(bundle.blob("component.wasm").unwrap(), component);
    assert_eq!(
        observation.component_digest,
        latent_artifacts::package::artifact_blob_digest(&component).as_str()
    );
    let mapping = mapping::inspect(&component);
    let document: Value = serde_json::from_slice(bundle.blob("capsule.json").unwrap()).unwrap();
    let limits = &document["execution"]["limits"];
    assert_eq!(limits["cpuFuel"], FUEL);
    assert_eq!(limits["memoryBytes"], MEMORY);
    assert_eq!(limits["wallTimeLimitMillis"], 120_000);
    for key in [
        "childCalls",
        "outboundRequests",
        "stateReadBytes",
        "stateWriteBytes",
        "blobReadBytes",
        "blobWriteBytes",
        "logBytes",
        "effectCount",
    ] {
        assert_eq!(limits[key], 0);
    }
    let budget = ResourceBudget {
        cpu_fuel: FUEL,
        memory_bytes: MEMORY,
        wall_time_limit_millis: Some(120_000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    println!(
        "GO_STACK_VARIANT {}",
        json!({"name":name,"initializerCap":initializer_cap,
        "sourceDigest":latent_artifacts::package::artifact_blob_digest(&expected).as_str(),
        "componentDigest":observation.component_digest,"sourceInputsDigest":observation.source.snapshot_digest,
        "budget":crate::budget(&budget),"mapping":mapping})
    );
    Variant {
        name,
        bundle,
        observation,
        mapping,
        budget,
    }
}

async fn configured(root: &Path, caller: &Variant, ordinary: &Variant) -> Fixture {
    let signers = package::Signers::new(GO_CAPSULE_BUILD_TYPE);
    let caller_bundle = package::bundle(&package::input(caller.name));
    let ordinary_bundle = package::bundle(&package::input(ordinary.name));
    assert_eq!(
        caller_bundle.layout().digest(),
        caller.bundle.layout().digest()
    );
    assert_eq!(
        ordinary_bundle.layout().digest(),
        ordinary.bundle.layout().digest()
    );
    // New source-matched native signer decodes/signs the NORMAL Go build
    // observation, including its newly closed v7 recipe. The catalog is fresh;
    // the same ordinary package is admitted only once in the first two cases.
    let mut uploads = vec![signers.upload_for_tenant(
        &caller_bundle,
        &caller.observation,
        &TenantId("tests".into()),
    )];
    if caller_bundle.layout().digest() != ordinary_bundle.layout().digest() {
        uploads.push(signers.upload_for_tenant(
            &ordinary_bundle,
            &ordinary.observation,
            &TenantId("tests".into()),
        ));
    }
    let catalog = package::catalog(root, signers.policy, Some(MEMORY));
    for upload in uploads {
        catalog
            .admit_package(&TenantId("tests".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    Fixture::with_go_stack_ceiling_runtime((catalog, caller_bundle, ordinary_bundle)).await
}

fn number(raw: &str) -> u64 {
    assert!(!raw.is_empty() && raw.len() <= 20 && raw.bytes().all(|byte| byte.is_ascii_digit()));
    let value: u64 = raw.parse().unwrap();
    assert_eq!(value.to_string(), raw);
    value
}

async fn call(f: &Fixture, variant: &Variant, label: &str, mode: u32, cap: bool) {
    let before = f.backend.resource_snapshot().stores_created;
    let mut request = f.request(label, mode);
    request.budget = variant.budget.clone();
    // The package and normal deployment ALSO hold this exact1b ceiling. The
    // generic fixture/factory10b upper ceiling is not relabelled1b.
    assert_eq!(request.budget.cpu_fuel, FUEL);
    let guard = cap.then(|| f.backend.arm_development_trap_observation().unwrap());
    let receipt = f.manager.start(request).unwrap().await;
    let resolved = receipt
        .resolved_revision
        .as_ref()
        .expect("actual resolved release/publication");
    assert_eq!(resolved.release, packages::release(&variant.bundle));
    let selected = f
        .catalog
        .execution_eligibility_selected(&resolved.release, None)
        .unwrap()
        .unwrap();
    assert_eq!(resolved.publication.as_ref(), Some(selected.publication()));
    let resolved_release = resolved.release.0.clone();
    let resolved_publication = resolved.publication.as_ref().unwrap().as_str().to_owned();
    let (result, consumption, frames) = match receipt.outcome {
        ActivationOutcome::Succeeded(success) if !cap => {
            assert!(guard.is_none());
            let values: Vec<String> = serde_json::from_slice(&success.output).unwrap();
            assert_eq!(values.len(), 1);
            assert!(values[0].len() <= 256);
            let parts: Vec<_> = values[0].split('|').collect();
            assert_eq!(parts.len(), 8);
            assert_eq!(
                &parts[..4],
                ["stack", "fresh=1", "init=3133440", "checksum=17756160"]
            );
            let before = number(parts[4].strip_prefix("before=").unwrap());
            let live = number(parts[5].strip_prefix("live=").unwrap());
            let before_gc = number(parts[6].strip_prefix("beforeGC=").unwrap());
            let gc = number(parts[7].strip_prefix("gc=").unwrap());
            assert!(live >= before + 17 * 8192 && gc > before_gc);
            (
                json!({"typedResult":values[0],"fresh":1,"beforeStack":before,"liveStack":live,
                "beforeGC":before_gc,"GC":gc,"checksum":17756160}),
                success.consumption,
                None,
            )
        }
        ActivationOutcome::Failed {
            error, consumption, ..
        } if cap => {
            assert_eq!(error.code, PlatformErrorCode::GuestTrap);
            let snapshot = guard.as_ref().unwrap().snapshot().unwrap();
            mapping::require_cap(&variant.mapping, &snapshot);
            (
                json!({"code":"GuestTrap","attribution":"actual-private-v7-cap-frame"}),
                consumption,
                Some(snapshot),
            )
        }
        other => panic!("unexpected stack outcome: {other:?}"),
    };
    drop(guard);
    assert!(consumption.cpu_fuel > 0 && consumption.cpu_fuel <= FUEL);
    assert!(consumption.peak_memory_bytes > 0 && consumption.peak_memory_bytes <= MEMORY);
    assert_eq!(consumption.outbound_requests, 0);
    assert_eq!(consumption.effect_count, 0);
    println!(
        "GO_STACK_CASE {}",
        json!({"case":label,"variant":variant.name,"mode":mode,"cap":cap,
        "resolvedRelease":resolved_release,"resolvedPublication":resolved_publication,
        "result":result,"numericObservation":frames,"cpuFuel":consumption.cpu_fuel,
        "peakMemoryBytes":consumption.peak_memory_bytes,"outboundRequests":consumption.outbound_requests,
        "reportedEffectCount":consumption.effect_count,"effectiveRequestBudget":budget(&variant.budget)})
    );
    f.idle().await;
    let state = f.backend.resource_snapshot();
    assert_eq!(state.stores_created, before + 1);
    assert_eq!(state.live_stores, 0);
    assert_eq!(state.live_component_instances, 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    assert_eq!(f.quotas.usage().unwrap().reserved_cpu_fuel, 0);
    assert_eq!(f.quotas.usage().unwrap().reserved_memory_bytes, 0);
    println!(
        "GO_STACK_OWNER {}",
        json!({"case":label,"stores":0,"instances":0,"reservations":0,
        "reservedFuel":0,"reservedMemory":0,"newStores":state.stores_created-before,
        "kernelRetirementQualified":false})
    );
}

#[tokio::test]
#[ignore = "requires two fresh normal v7 Go components and configured original numeric observer"]
async fn signed_go_v7_stack_cap_gc_initializer_and_fresh_state_keep_original_budgets() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let ordinary = load("go-stack-ordinary", false);
    let initializer = load("go-stack-initializer-cap", true);
    assert_ne!(
        ordinary.mapping.component_digest,
        initializer.mapping.component_digest
    );
    {
        println!(
            "GO_STACK_FACTORY {}",
            json!({"scenario":"growth","observerReset":false})
        );
        let root = tempfile::tempdir().unwrap();
        let f = configured(root.path(), &ordinary, &ordinary).await;
        call(&f, &ordinary, "below-cap-GC", 0, false).await;
        call(&f, &ordinary, "growth-cap", 1, true).await;
        call(&f, &ordinary, "fresh-after-growth", 0, false).await;
    }
    {
        println!(
            "GO_STACK_FACTORY {}",
            json!({"scenario":"raised-limit","observerReset":false})
        );
        let root = tempfile::tempdir().unwrap();
        let f = configured(root.path(), &ordinary, &ordinary).await;
        call(&f, &ordinary, "raised-limit-cap", 2, true).await;
        call(&f, &ordinary, "fresh-after-raised-limit", 0, false).await;
    }
    {
        println!(
            "GO_STACK_FACTORY {}",
            json!({"scenario":"initializer","observerReset":false})
        );
        let root = tempfile::tempdir().unwrap();
        let f = configured(root.path(), &initializer, &ordinary).await;
        call(&f, &initializer, "initializer-cap", 0, true).await;
        // Full retirement precedes a normal deployment publication change.
        // No failed Store, module globals or observer is reset/retried.
        let selected = f
            .catalog
            .execution_eligibility_selected(&packages::release(&ordinary.bundle), None)
            .unwrap()
            .unwrap();
        let mut deployment = f
            .store
            .get(&DeploymentId("caller".into()))
            .await
            .unwrap()
            .unwrap();
        let prior_release = deployment.release.clone();
        let prior_publication = deployment.publication.clone().unwrap();
        deployment.release = packages::release(&ordinary.bundle);
        deployment.publication = Some(selected.publication().clone());
        assert_eq!(deployment.resources, ordinary.budget);
        f.store.apply(deployment).await.unwrap();
        println!(
            "GO_STACK_REPOINT {}",
            json!({"oldRelease":prior_release.0,
            "oldPublication":prior_publication.as_str(),"newRelease":packages::release(&ordinary.bundle).0,
            "newPublication":selected.publication().as_str(),"sameBackend":true,
            "originalOwnersZeroBeforeChange":true,"retryFailedInitializer":false})
        );
        call(&f, &ordinary, "fresh-after-initializer", 0, false).await;
    }
    println!(
        "GO_STACK_COMPLETE {}",
        json!({"attempts":7,"components":2,"factories":3,
        "capFrames":3,"freshAfterFailures":3,"observerReset":false,
        "effectiveFuel":FUEL,"effectiveMemory":MEMORY,"queuedWork":16,
        "wholeGoCostQualification":false,"kernelRetirementQualified":false})
    );
}
