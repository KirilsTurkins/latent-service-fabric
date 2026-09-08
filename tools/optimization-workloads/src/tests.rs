use super::*;

#[test]
fn exact_canonical_frames_match_the_pure_workloads() {
    assert_eq!(invoke("echo", br#"["hello"]"#).unwrap(), br#"["hello"]"#);
    assert_eq!(invoke("echo", br#"[""]"#).unwrap(), br#"[""]"#);
    let unicode = "snowman \u{2603}\n\"quoted\"".to_owned();
    let payload = serde_json::to_vec(&(unicode.clone(),)).unwrap();
    assert_eq!(invoke("echo", &payload).unwrap(), payload);
    assert_eq!(echo(unicode.clone()).unwrap(), unicode);

    let input = br#"[{"values":[0,1,4294967295],"bytes":[0,255,7],"label":"item"}]"#;
    let expected = br#"[{"label":"item","bytes":[7,255,0],"values":[0,512,4294967295]}]"#;
    assert_eq!(invoke("transform", input).unwrap(), expected);
}

#[test]
fn compute_has_stable_wrapping_vectors_and_a_zero_round_identity() {
    for (seed, rounds, expected) in [
        (0, 0, 0),
        (u32::MAX, 0, u32::MAX),
        (0, 1, 2_638_104_198),
        (1, 3, 942_667_341),
        (u32::MAX, 7, 3_702_961_415),
    ] {
        assert_eq!(compute(seed, rounds).unwrap(), expected);
        let input = serde_json::to_vec(&(seed, rounds)).unwrap();
        assert_eq!(
            invoke("compute", &input).unwrap(),
            serde_json::to_vec(&(expected,)).unwrap()
        );
    }
}

#[test]
fn invalid_inputs_are_rejected_without_echoing_payloads() {
    for payload in [
        b"null".as_slice(),
        b"[]",
        br#"["secret",3]"#,
        b"[1.5]",
        b"[1] garbage",
    ] {
        assert_eq!(
            invoke("echo", payload).unwrap_err(),
            "optimization-invalid-frame"
        );
    }
    for payload in [b"[0,1000001]".as_slice(), b"[4294967295,4294967295]"] {
        assert_eq!(
            invoke("compute", payload).unwrap_err(),
            "optimization-round-limit"
        );
    }
    for payload in [
        br#"[{"label":"x","bytes":[],"values":[],"extra":true}]"#.as_slice(),
        br#"[{"label":"x","label":"y","bytes":[],"values":[]}]"#,
        br#"[{"label":"x","bytes":[256],"values":[]}]"#,
        br#"[{"label":"x","bytes":[],"values":[4294967296]}]"#,
    ] {
        assert_eq!(
            invoke("transform", payload).unwrap_err(),
            "optimization-invalid-frame"
        );
    }
    assert_eq!(
        invoke("unknown-secret", b"[]").unwrap_err(),
        "optimization-unknown-function"
    );
}

#[test]
fn collection_and_frame_limits_reject_before_execution() {
    let value = TransformValue {
        label: "bounded".to_owned(),
        bytes: vec![1; MAX_COLLECTION_ITEMS + 1],
        values: Vec::new(),
    };
    let frame = serde_json::to_vec(&(value.clone(),)).unwrap();
    assert_eq!(transform(value), Err(WorkloadError::CollectionLimit));
    assert_eq!(
        invoke("transform", &frame).unwrap_err(),
        "optimization-collection-limit"
    );
    assert_eq!(
        echo("x".repeat(MAX_TEXT_BYTES + 1)),
        Err(WorkloadError::TextLimit)
    );
    assert_eq!(
        invoke("echo", &vec![b' '; MAX_PAYLOAD_BYTES + 1]).unwrap_err(),
        "optimization-payload-limit"
    );
    assert_eq!(
        compute(0, MAX_COMPUTE_ROUNDS + 1),
        Err(WorkloadError::RoundLimit)
    );
}
