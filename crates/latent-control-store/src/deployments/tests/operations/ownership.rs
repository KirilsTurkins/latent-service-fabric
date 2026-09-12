use super::*;

#[test]
fn response_and_request_leases_hold_finite_owner_charges_without_root_lock() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let limits = DeploymentOperationLimits {
        maximum_read_owners: 1,
        ..DeploymentOperationLimits::default()
    };
    let store = open_limits(&root, &releases, limits);
    let baseline = store.operation_budget.used();
    let reserved = store.reserve_operation_request().unwrap();
    assert!(reserved.retained_bytes() >= MAX_OPERATION_SCRATCH_BYTES);
    assert!(store.operation_budget.used() > baseline);
    assert_code(
        run(store.get_operation(&alice(), "absent")),
        Code::ResourceExhausted,
    );
    let retained = reserved.clone();
    drop(reserved);
    assert_code(store.reserve_operation_request(), Code::ResourceExhausted);
    drop(retained);
    assert_eq!(store.operation_budget.used(), baseline);
    let response = lookup(&store, "absent");
    let (value, lease) = response.into_parts();
    assert!(matches!(value, DeploymentOperationLookup::Unknown { .. }));
    assert_code(store.reserve_operation_request(), Code::ResourceExhausted);
    drop(store);
    // A delayed response owns accounting, not the old catalog's filesystem lock.
    let reopened = open_limits(&root, &releases, limits);
    assert!(reopened.reserve_operation_request().is_ok());
    drop(lease);
}

#[test]
fn bounded_input_and_shared_metadata_reject_before_hashing_or_publication() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("bounds");
    let store = open_limits(
        &root,
        &releases,
        DeploymentOperationLimits {
            maximum_metadata_bytes: MAX_OPERATION_SCRATCH_BYTES,
            ..DeploymentOperationLimits::default()
        },
    );
    assert_code(store.reserve_operation_request(), Code::ResourceExhausted);
    assert_code(
        run(store.prepare_operation(apply("small", 0, "blue", 0, &one))),
        Code::ResourceExhausted,
    );
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 0);
    assert_eq!(store.generation(), RouteGeneration(0));
    assert_eq!(stored(&root)["format_version"], 2);
    drop(store);
    let store = open(&root, &releases);
    for kind in 0..3 {
        let mut request = apply("capacity", 0, "blue", 0, &one);
        let DeploymentOperationRequest::Apply {
            context, manifest, ..
        } = &mut request
        else {
            unreachable!()
        };
        match kind {
            0 => {
                context.operation_id.reserve(MAX_REQUEST_BYTES);
            }
            1 => manifest.placement.zones = Vec::with_capacity(MAX_REQUEST_BYTES),
            2 => manifest.grants = Vec::with_capacity(MAX_REQUEST_BYTES),
            _ => unreachable!(),
        }
        assert_code(
            run(store.prepare_operation(request)),
            Code::ResourceExhausted,
        );
    }
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 0);
    assert_eq!(store.generation(), RouteGeneration(0));
    assert_eq!(stored(&root)["format_version"], 2);
}

#[test]
fn prepared_owner_is_affine_and_cannot_be_committed_by_another_catalog() {
    let first_root = TempRoot::new();
    let second_root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("owner");
    let first = open(&first_root, &releases);
    let second = open(&second_root, &releases);
    let request = apply("owned", 0, "blue", 0, &one);
    let prepared = run(first.prepare_operation(request.clone())).unwrap();
    assert_code(
        run(first.prepare_operation(request.clone())),
        Code::ResourceExhausted,
    );
    assert_code(second.commit_operation(prepared), Code::PermissionDenied);
    assert_eq!(first.generation(), RouteGeneration(0));
    assert_eq!(stored(&first_root)["format_version"], 2);
    assert_eq!(second.generation(), RouteGeneration(0));
    assert_eq!(stored(&second_root)["format_version"], 2);
    drop(execute(&first, request));
}
