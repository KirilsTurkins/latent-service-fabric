use super::*;

fn data_module(count: u32, bodies: bool) -> wasm_encoder::Module {
    let mut declared = Vec::new();
    count.encode(&mut declared);
    let mut module = wasm_encoder::Module::new();
    module.section(&RawSection {
        id: 12,
        data: &declared,
    });
    let mut data = declared;
    if bodies {
        for _ in 0..count {
            // Passive segment with an empty byte vector; no memory is accessed.
            data.extend_from_slice(&[1, 0]);
        }
    }
    module.section(&RawSection {
        id: 11,
        data: &data,
    });
    module
}

#[test]
fn valid_data_segments_at_the_pinned_parser_ceiling_validate_without_execution() {
    let mut root = Component::new();
    root.section(&ModuleSection(&data_module(100_000, true)));
    let bytes = root.finish();
    assert!(bytes.len() < 256 * 1024);
    validate(&bytes, SemanticLimits::default()).unwrap();
}

#[test]
fn lowering_function_slots_does_not_reclassify_data_segments_as_functions() {
    let limits = SemanticLimits {
        max_core_functions: 1,
        ..SemanticLimits::default()
    };
    let mut root = Component::new();
    root.section(&ModuleSection(&data_module(2, true)));
    validate(&root.finish(), limits).unwrap();

    let mut module = wasm_encoder::Module::new();
    module.section(&RawSection {
        id: 3,
        data: &[2, 0, 0],
    });
    let mut root = Component::new();
    root.section(&ModuleSection(&module));
    assert_eq!(
        validate(&root.finish(), limits).unwrap_err().message,
        "component-vector-limit"
    );
}

#[test]
fn data_segments_still_consume_the_original_aggregate_budget_across_modules() {
    let limits = SemanticLimits {
        max_type_nodes: 3,
        ..SemanticLimits::default()
    };
    let module = data_module(2, true);
    let mut root = Component::new();
    root.section(&ModuleSection(&module));
    root.section(&ModuleSection(&module));
    assert_eq!(
        validate(&root.finish(), limits).unwrap_err().message,
        "component-work-limit"
    );
}

#[test]
fn excess_and_truncated_data_vectors_remain_rejected_before_execution() {
    let mut root = Component::new();
    root.section(&ModuleSection(&data_module(100_001, false)));
    assert_eq!(
        validate(&root.finish(), SemanticLimits::default())
            .unwrap_err()
            .message,
        "component-vector-limit"
    );

    let mut root = Component::new();
    root.section(&ModuleSection(&data_module(2, false)));
    assert_eq!(
        validate(&root.finish(), SemanticLimits::default())
            .unwrap_err()
            .message,
        "invalid-component-binary"
    );

    let mut root = Component::new();
    root.section(&ModuleSection(&data_module(2, true)));
    assert_eq!(
        validate(
            &root.finish(),
            SemanticLimits {
                max_type_nodes: 1,
                ..SemanticLimits::default()
            },
        )
        .unwrap_err()
        .message,
        "component-vector-limit"
    );
}
