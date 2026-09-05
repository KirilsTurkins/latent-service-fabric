use latent_manifest::{JsonManifestCodec, ManifestCodec, ManifestResult};
use serde::Deserialize;

const CASES: &str = include_str!("fixtures/integer-dialect-cases.json");
const CAPSULE: &str = include_str!("../../../examples/echo-contract/capsule.json");
const DEPLOYMENT: &str = include_str!("../../../examples/echo-contract/deployment.json");

#[derive(Debug, Deserialize)]
struct IntegerDialectCase {
    name: String,
    target: String,
    lexeme: String,
    valid: bool,
}

#[test]
fn runtime_integer_semantics_match_the_shared_draft_2020_12_cases() {
    let cases: Vec<IntegerDialectCase> = serde_json::from_str(CASES).expect("case fixture");
    let codec = JsonManifestCodec::default();

    for case in cases {
        let first = evaluate(&codec, &case);
        assert_eq!(
            first.is_ok(),
            case.valid,
            "{}: runtime result was {first:#?}",
            case.name
        );
        let second = evaluate(&codec, &case);
        assert_eq!(first, second, "{}: result must be deterministic", case.name);
    }
}

fn evaluate(codec: &JsonManifestCodec, case: &IntegerDialectCase) -> ManifestResult<()> {
    let (template, anchor, replacement) = match case.target.as_str() {
        "deployment-weight" => (
            DEPLOYMENT,
            "\"weight\": 10000",
            format!("\"weight\": {}", case.lexeme),
        ),
        "capsule-host-call-depth" => (
            CAPSULE,
            "\"hostCallDepthMaximum\": 8",
            format!("\"hostCallDepthMaximum\": {}", case.lexeme),
        ),
        "capsule-memory-bytes" => (
            CAPSULE,
            "\"memoryBytes\": 4194304",
            format!("\"memoryBytes\": {}", case.lexeme),
        ),
        target => panic!("unsupported integer-dialect target `{target}`"),
    };
    assert!(template.contains(anchor), "test anchor must remain present");
    let document = template.replacen(anchor, &replacement, 1);

    match case.target.as_str() {
        "deployment-weight" => codec.decode_deployment(document.as_bytes()).map(|_| ()),
        "capsule-host-call-depth" | "capsule-memory-bytes" => {
            codec.decode_capsule(document.as_bytes()).map(|_| ())
        }
        _ => unreachable!("target was checked while constructing the document"),
    }
}
