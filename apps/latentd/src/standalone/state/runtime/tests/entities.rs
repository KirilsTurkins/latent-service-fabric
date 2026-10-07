use super::*;

#[tokio::test]
async fn actual_installed_runtime_builds_coordinators_with_one_original_table_without_request_admission(
) {
    let fixture = Fixture::new();
    let (state, mut effects) = fixture.open().await;
    let same_runtime = state.as_ref().clone();
    assert!(Arc::ptr_eq(&state.0.entity, &same_runtime.0.entity));
    let table_references = Arc::strong_count(&state.0.entity);
    let first = state
        .coordinator(AdmissionTime::new(
            state.0.source.clone(),
            state.0.native.clone(),
        ))
        .unwrap();
    let second = same_runtime
        .coordinator(AdmissionTime::new(
            state.0.source.clone(),
            state.0.native.clone(),
        ))
        .unwrap();
    // Both real constructors retain the installed registry directly. They do
    // not allocate a replacement default table, operation or request owner.
    assert_eq!(Arc::strong_count(&state.0.entity), table_references + 2);
    assert_eq!(state.entity_snapshot().unwrap(), Default::default());
    let native = state.0.native.snapshot().unwrap();
    assert_eq!(native.ordinary.slots, 0);
    assert_eq!(native.ordinary.bytes, 0);
    drop((first, second));
    assert_eq!(Arc::strong_count(&state.0.entity), table_references);
    finish(&state, &mut effects).await;
}
