use super::*;
use latent_core::{
    ActivationBudget, BudgetProfile, ClockSample, EffectiveActivationBudget, ResourceBudget,
};
use std::time::Instant;
#[allow(dead_code)]
mod generated {
    include!(concat!(
        env!("OUT_DIR"),
        "/result-message-reference/latent.invocation.v1.rs"
    ));
}
fn original() -> ActivationBudget {
    let limits = ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 4096,
        wall_time_limit_millis: Some(1000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &limits,
        &limits,
        &limits,
        None,
        ClockSample::new(1000, Instant::now()),
    )
    .unwrap();
    ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap()
}
fn compare_success(bytes: &[u8]) {
    let generated = generated::Success::decode(bytes);
    let owned = Success::decode(bytes);
    match (generated, owned) {
        (Ok(old), Ok(new)) => {
            assert_eq!(old.payload.as_slice(), new.payload.as_ref());
            assert_eq!(old.media_type, new.media_type);
            assert_eq!(old.committed_state_version, new.committed_state_version);
            assert_eq!(old.effect_ids, new.effect_ids);
            assert_eq!(old.metadata, new.metadata);
            assert_eq!(new.encoded_len(), new.encode_to_vec().len());
            assert_eq!(
                old,
                generated::Success::decode(new.encode_to_vec().as_slice()).unwrap()
            );
            assert_eq!(
                new,
                Success::decode(old.encode_to_vec().as_slice()).unwrap()
            );
        }
        (Err(old), Err(new)) => assert_eq!(old.to_string(), new.to_string()),
        _ => panic!("generated and owned decode disagree"),
    }
}
fn compare_error(bytes: &[u8]) {
    let generated = generated::DeclaredError::decode(bytes);
    let owned = DeclaredError::decode(bytes);
    match (generated, owned) {
        (Ok(old), Ok(new)) => {
            assert_eq!(old.payload.as_slice(), new.payload.as_ref());
            assert_eq!(old.code, new.code);
            assert_eq!(old.message, new.message);
            assert_eq!(old.media_type, new.media_type);
            assert_eq!(old.metadata, new.metadata);
            assert_eq!(new.encoded_len(), new.encode_to_vec().len());
            assert_eq!(
                old,
                generated::DeclaredError::decode(new.encode_to_vec().as_slice()).unwrap()
            );
            assert_eq!(
                new,
                DeclaredError::decode(old.encode_to_vec().as_slice()).unwrap()
            );
        }
        (Err(old), Err(new)) => assert_eq!(old.to_string(), new.to_string()),
        _ => panic!("generated and owned decode disagree"),
    }
}
#[test]
fn original_generated_results_cross_encode_defaults_and_all_fields() {
    compare_success(&[]);
    compare_error(&[]);
    let old = generated::Success {
        payload: b"binary\0value".to_vec(),
        media_type: "application/octet-stream".into(),
        committed_state_version: Some(String::new()),
        effect_ids: vec!["one".into(), "two".into()],
        metadata: HashMap::from([("key".into(), "value".into())]),
    };
    compare_success(&old.encode_to_vec());
    let new = Success::decode(old.encode_to_vec().as_slice()).unwrap();
    assert_eq!(old.encode_to_vec(), new.encode_to_vec()); // single-map entry order fixed
    for code in [
        "declared-error",
        "business-rejection",
        "",
        "unknown-future-code",
    ] {
        let old = generated::DeclaredError {
            code: code.into(),
            message: "domain message".into(),
            payload: b"{\"err\":null}".to_vec(),
            media_type: "application/json".into(),
            metadata: HashMap::from([("key".into(), "value".into())]),
        };
        compare_error(&old.encode_to_vec());
        assert_eq!(
            old.encode_to_vec(),
            DeclaredError::decode(old.encode_to_vec().as_slice())
                .unwrap()
                .encode_to_vec()
        );
    }
}
#[test]
fn original_generated_results_repeated_singular_unknown_and_malformed_fields() {
    // Duplicate singular bytes/string fields are last-one-wins; effect_ids append.
    let mut success = generated::Success {
        payload: vec![1; 512],
        media_type: "first".into(),
        committed_state_version: Some("first".into()),
        effect_ids: vec!["first".into()],
        metadata: HashMap::new(),
    }
    .encode_to_vec();
    success.extend(
        generated::Success {
            payload: vec![2],
            media_type: "last".into(),
            committed_state_version: Some("last".into()),
            effect_ids: vec!["last".into()],
            metadata: HashMap::new(),
        }
        .encode_to_vec(),
    );
    success.extend_from_slice(&[0xa0, 0x06, 0x01]); // unknown varint tag100
    compare_success(&success);
    let mut error = generated::DeclaredError {
        code: "first".into(),
        message: "first".into(),
        payload: vec![1; 512],
        media_type: "first".into(),
        metadata: HashMap::new(),
    }
    .encode_to_vec();
    error.extend(
        generated::DeclaredError {
            code: "last".into(),
            message: "last".into(),
            payload: vec![2],
            media_type: "last".into(),
            metadata: HashMap::new(),
        }
        .encode_to_vec(),
    );
    error.extend_from_slice(&[0xaa, 0x06, 0x02, 0x42, 0x43]); // unknown bytes
    compare_error(&error);
    for bytes in [
        &[0x0a, 4, 1][..],
        &[0x08, 1],
        &[0x12, 1, 0xff],
        &[0x28, 1],
        &[0x2a, 2, 0x0a, 4],
        &[0],
        &[0xff],
    ] {
        compare_success(bytes);
    }
    for bytes in [
        &[0x1a, 4, 1][..],
        &[0x18, 1],
        &[0x0a, 1, 0xff],
        &[0x28, 1],
        &[0x2a, 2, 0x0a, 4],
        &[0],
        &[0xff],
    ] {
        compare_error(bytes);
    }
}
#[test]
fn result_message_local_clones_capacity_clear_and_transport_keep_original_owner() {
    let budget = original();
    let mut bytes = Vec::with_capacity(512);
    bytes.extend_from_slice(b"one");
    let pointer = bytes.as_ptr();
    let memory = budget.reserve_host_memory(512).unwrap();
    let payload = ResultPayload::from_reserved(bytes, memory, &budget).unwrap();
    let mut success = Success {
        payload,
        ..Success::default()
    };
    let clone = success.clone();
    assert_eq!(clone.payload.capacity(), 512);
    assert_eq!(clone.payload.as_ptr(), pointer);
    let charged = budget.host_memory_bytes();
    let encoded = success.encode_to_vec();
    assert_eq!(budget.host_memory_bytes(), charged);
    success.clear();
    assert_eq!(success, Success::default());
    assert_eq!(budget.host_memory_bytes(), charged);
    drop(clone);
    assert_eq!(budget.host_memory_bytes(), 0);
    let decoded = Success::decode(encoded.as_slice()).unwrap();
    assert_eq!(decoded.payload.as_ref(), b"one");
    assert!(decoded.payload.capacity() >= 3);
    assert!(decoded.payload.capacity() < 512);
}
#[test]
fn external_sliced_wire_backing_is_copied_before_capacity_validation() {
    let original = generated::Success {
        payload: vec![42],
        ..Default::default()
    }
    .encode_to_vec();
    let mut large = vec![0u8; 1024 * 1024];
    large[..original.len()].copy_from_slice(&original);
    let transport = prost::bytes::Bytes::from(large);
    let sliced = transport.slice(..original.len());
    let decoded = Success::decode(sliced).unwrap();
    assert_eq!(decoded.payload.as_ref(), &[42]);
    let old = generated::Success::decode(original.as_slice()).unwrap();
    assert_eq!(decoded.payload.capacity(), old.payload.capacity()); // real Vec capacity, including allocator spare
    assert!(decoded.payload.capacity() < 512);
    assert_ne!(decoded.payload.as_ptr(), transport.as_ptr());
    let mut over = Vec::with_capacity(512);
    over.push(42);
    let over: ResultPayload = over.into();
    assert_eq!(over.capacity(), 512);
}
