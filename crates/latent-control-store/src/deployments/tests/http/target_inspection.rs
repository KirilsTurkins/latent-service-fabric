use super::*;
use crate::target_inspection::TargetInspectionRequest;

#[test]
fn inspection_reads_actual_http_object_generations_without_replaying_original_operations() {
    let (_roots, _repo, store, _publication) = setup();
    execute(
        &store,
        request(
            &store,
            "original-bind",
            definition(&store, "alice", "http-route", "web", "/", "prefix"),
            0,
        ),
    );
    let snapshot = get(&store, "alice", "http-route");
    let object = snapshot.value().trigger.as_ref().unwrap();
    let target = object.manifest.target.application().unwrap();
    let query = TargetInspectionRequest {
        target: latent_routing::InvocationTarget {
            tenant: TenantId("alice".into()),
            service: target.service.clone(),
            contract: target.contract.clone(),
            function: FunctionId(target.function.clone()),
            route: target.route.clone(),
        },
        revision: None,
        publication: None,
        routing_key: None,
    };
    let observed = store.inspect_target(query).unwrap();
    assert_eq!(observed.catalog_transaction, snapshot.value().state_version);
    assert_eq!(observed.candidates.len(), 1);
    let binding = &observed.candidates[0].http_bindings[0];
    assert_eq!(binding.id.0, "http-route");
    assert_eq!(binding.generation, object.generation);
    assert!(binding.current);
    assert!(observed.candidates[0].http_compatible);
    let after = get(&store, "alice", "http-route");
    assert_eq!(after.value().trigger, snapshot.value().trigger);
    assert_eq!(after.value().state_version, snapshot.value().state_version);
    assert_eq!(
        after.value().route_generation,
        snapshot.value().route_generation
    );
    let receipt = store
        .get_trigger_operation(&TenantId("alice".into()), "original-bind")
        .unwrap();
    let TriggerOperationLookup::Found(receipt) = receipt.value() else {
        panic!("original receipt must remain retained");
    };
    assert_eq!(receipt.object_generation, binding.generation);
}
