use latent_wire::invocation::proto;

pub const NAMES: [&str; 8] = [
    "success",
    "declared-error",
    "malformed-json",
    "absolute-deadline",
    "zero-memory",
    "zero-fuel",
    "missing-route",
    "foreign-tenant",
];

pub fn request(index: usize, id: &str) -> proto::InvokeRequest {
    let mut value = proto::InvokeRequest {
        activation_id: Some(id.to_owned()),
        root_activation_id: Some("parity-root".to_owned()),
        parent_activation_id: Some("parity-parent".to_owned()),
        target: Some(proto::InvocationTarget {
            tenant: "examples".to_owned(),
            service: super::fixture::SHARED.to_owned(),
            contract: "examples:echo/api@0.1.0".to_owned(),
            function: "echo".to_owned(),
            route: None,
        }),
        payload: br#"["parity"]"#.to_vec(),
        media_type: latent_wasmtime::WIT_VALUES_MEDIA_TYPE.to_owned(),
        budget: Some(proto::ResourceBudget {
            cpu_fuel: 1_000_000,
            memory_bytes: 4 * 1024 * 1024,
            wall_time_limit_millis: Some(4000),
            log_bytes: 16384,
            ..proto::ResourceBudget::default()
        }),
        ..proto::InvokeRequest::default()
    };
    match index {
        0 => {}
        1 => value.payload = br#"[""]"#.to_vec(),
        2 => value.payload = b"[".to_vec(),
        3 => value.deadline_unix_millis = Some(1),
        4 => value.budget.as_mut().unwrap().memory_bytes = 0,
        5 => value.budget.as_mut().unwrap().cpu_fuel = 0,
        6 => "examples/missing".clone_into(&mut value.target.as_mut().unwrap().service),
        7 => "other".clone_into(&mut value.target.as_mut().unwrap().tenant),
        _ => unreachable!("fixed eight-case profile"),
    }
    value
}

pub fn compare(
    index: usize,
    direct: &proto::InvokeResponse,
    rpc: &proto::InvokeResponse,
) -> serde_json::Value {
    let normalize = |result: &Option<proto::invoke_response::Result>| {
        let mut result = result.clone();
        if let Some(proto::invoke_response::Result::Success(value)) = &mut result {
            let cell = value
                .metadata
                .remove("cell-id")
                .expect("actual selected cell");
            assert_eq!(cell, super::fixture::CELL);
            assert_eq!(
                value.metadata.get("cell-disposition").map(String::as_str),
                Some("released")
            );
        }
        result
    };
    assert_eq!(
        normalize(&direct.result),
        normalize(&rpc.result),
        "typed outcome parity: {}",
        NAMES[index]
    );
    assert_eq!(direct.revision_id, rpc.revision_id);
    assert_eq!(direct.release_digest, rpc.release_digest);
    assert_eq!(direct.route_generation, rpc.route_generation);
    let left = direct.consumption.as_ref().expect("direct consumption");
    let right = rpc.consumption.as_ref().expect("RPC consumption");
    assert_eq!(left.cpu_fuel, right.cpu_fuel);
    assert_eq!(left.peak_memory_bytes, right.peak_memory_bytes);
    assert_eq!(left.log_bytes, right.log_bytes);
    assert!(left.cpu_fuel <= 1_000_000 && right.cpu_fuel <= 1_000_000);
    assert!(
        left.peak_memory_bytes <= 4 * 1024 * 1024 && right.peak_memory_bytes <= 4 * 1024 * 1024
    );
    let kind = match direct.result.as_ref().expect("typed result") {
        proto::invoke_response::Result::Success(value) => {
            assert_eq!(index, 0);
            assert_eq!(
                serde_json::from_slice::<serde_json::Value>(&value.payload).unwrap(),
                serde_json::json!([{"ok":"parity"}])
            );
            "success"
        }
        proto::invoke_response::Result::DeclaredError(_) => {
            assert_eq!(index, 1);
            "declared-error"
        }
        proto::invoke_response::Result::PlatformFailure(_) => {
            assert!((2..=6).contains(&index));
            "platform-failure"
        }
    };
    serde_json::json!({"name":NAMES[index],"classification":kind,
        "cpu_fuel":left.cpu_fuel.to_string(),"peak_memory_bytes":left.peak_memory_bytes.to_string(),
        "log_bytes":left.log_bytes.to_string(),"receipt_pin_equal":true})
}
