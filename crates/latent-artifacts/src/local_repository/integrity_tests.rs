use latent_core::PlatformError;
use latent_manifest::__serde_json as json;

use super::*;

#[path = "integrity_tests/records.rs"]
mod records;
#[path = "integrity_tests/recovery.rs"]
mod recovery;

const INVALID_RECORD: &str = "invalid catalog completion record";
const LEGACY_RECORD: &str = "legacy catalog completion marker is unsupported";
const ENTRY_FILES: [&str; 4] = [
    "metadata.json",
    "manifest.json",
    "component.wasm",
    "COMPLETE",
];

fn entry_files(path: &Path) -> [Option<Vec<u8>>; 4] {
    ENTRY_FILES.map(|name| match fs::read(path.join(name)) {
        Ok(bytes) => Some(bytes),
        Err(failure) if failure.kind() == std::io::ErrorKind::NotFound => None,
        Err(failure) => panic!("read fixture {name}: {failure}"),
    })
}

fn replace_once(bytes: &[u8], original: &str, replacement: &str) -> Vec<u8> {
    let text = std::str::from_utf8(bytes).expect("JSON fixture is UTF-8");
    assert_eq!(text.matches(original).count(), 1, "unambiguous mutation");
    text.replacen(original, replacement, 1).into_bytes()
}

fn assert_corrupt<T>(result: Result<T, PlatformError>, message: &str) {
    let failure = result
        .err()
        .expect("corrupt persisted entry must be rejected");
    assert_eq!(failure.code, PlatformErrorCode::CorruptArtifact);
    assert_eq!(failure.message, message);
    assert!(!failure.retryable);
}

pub(super) fn assert_fetch_retry_and_reopen_reject(
    repo: DirectoryArtifactRepository,
    expected: &CapsuleArtifact,
    path: &Path,
    message: &str,
) {
    let original_files = entry_files(path);
    let root = repo.root().to_owned();
    assert_corrupt(
        block_on(repo.fetch(&expected.descriptor.release_digest)),
        message,
    );
    assert_corrupt(
        block_on(repo.fetch_verified_metadata(&expected.descriptor.release_digest)),
        message,
    );
    assert_corrupt(block_on(repo.publish(expected.clone())), message);
    assert_eq!(
        entry_files(path),
        original_files,
        "failed reads do not repair data"
    );
    drop(repo);
    assert_corrupt(
        DirectoryArtifactRepository::open(root, DirectoryArtifactRepositoryConfig::default()),
        message,
    );
    assert_eq!(
        entry_files(path),
        original_files,
        "failed recovery preserves data"
    );
}

#[test]
fn completion_record_binds_exact_payloads_without_changing_release_identity() {
    let temp = TempRoot::new();
    let expected = artifact("complete-record", b"abc");
    let repo = repository(temp.path());
    let published = block_on(repo.publish(expected.clone())).expect("publish tiny release");
    assert_eq!(published.release_digest, release_digest(b"abc"));
    let path = release_dir(repo.root(), &published.release_digest);
    let metadata = fs::read(path.join("metadata.json")).unwrap();
    let manifest = fs::read(path.join("manifest.json")).unwrap();
    assert_eq!(
        manifest,
        JsonManifestCodec::default()
            .encode_capsule(&expected.manifest)
            .unwrap()
    );
    let completion = fs::read(path.join("COMPLETE")).unwrap();
    let independently_encoded = format!(
        "{{\"format_version\":1,\"component_digest\":\"{}\",\"component_size_bytes\":3,\"metadata_digest\":\"{}\",\"manifest_digest\":\"{}\"}}",
        published.release_digest.0,
        release_digest(&metadata).0,
        release_digest(&manifest).0,
    );
    assert_eq!(completion, independently_encoded.as_bytes());
    assert!(completion.len() <= 1024);
    let persisted = entry_files(&path);
    block_on(repo.publish(expected.clone())).expect("idempotent duplicate");
    assert_eq!(entry_files(&path), persisted);
    drop(repo);
    let reopened = repository(temp.path());
    assert_eq!(
        block_on(reopened.fetch(&published.release_digest)).unwrap(),
        expected
    );
    assert_eq!(entry_files(&path), persisted);
}

#[derive(Clone, Copy, Debug)]
enum MetadataMutation {
    DescriptorReference,
    ContractDocumentation,
    ContractValueType,
    ManifestLabel,
}

fn mutate_metadata(path: &Path, mutation: MetadataMutation) {
    let (file, original, replacement) = match mutation {
        MetadataMutation::DescriptorReference => (
            "metadata.json",
            "local://tests/metadata-a",
            "local://tests/metadata-b",
        ),
        MetadataMutation::ContractDocumentation => (
            "metadata.json",
            "round-trip function",
            "round-trip functioo",
        ),
        MetadataMutation::ContractValueType => ("metadata.json", "\"String\"", "\"Bytes\""),
        MetadataMutation::ManifestLabel => ("manifest.json", "\"example\"", "\"changed\""),
    };
    let old_bytes = fs::read(path.join(file)).unwrap();
    let mutated = replace_once(&old_bytes, original, replacement);
    json::from_slice::<json::Value>(&mutated).expect("mutation preserves valid JSON");
    if file == "metadata.json" {
        super::super::metadata_codec::decode_metadata(&mutated, 4 * 1024 * 1024)
            .expect("mutated metadata still satisfies the existing bounded codec");
    } else {
        let codec = JsonManifestCodec::default();
        let manifest = codec
            .decode_capsule(&mutated)
            .expect("valid changed manifest");
        Phase1ManifestValidator::new()
            .validate_capsule(&manifest)
            .unwrap();
        assert_eq!(codec.encode_capsule(&manifest).unwrap(), mutated);
    }
    fs::write(path.join(file), mutated).unwrap();
}

#[test]
fn valid_json_descriptor_contract_and_manifest_mutations_are_detected() {
    for mutation in [
        MetadataMutation::DescriptorReference,
        MetadataMutation::ContractDocumentation,
        MetadataMutation::ContractValueType,
        MetadataMutation::ManifestLabel,
    ] {
        let temp = TempRoot::new();
        let expected = artifact("metadata-a", b"unchanged tiny component");
        let repo = repository(temp.path());
        block_on(repo.publish(expected.clone())).unwrap();
        let path = release_dir(repo.root(), &expected.descriptor.release_digest);
        let completion = fs::read(path.join("COMPLETE")).unwrap();
        mutate_metadata(&path, mutation);
        assert_eq!(fs::read(path.join("COMPLETE")).unwrap(), completion);
        let component = fs::read(path.join("component.wasm")).unwrap();
        assert_eq!(component, expected.component_bytes, "mutation {mutation:?}");
        assert_eq!(
            release_digest(&component),
            expected.descriptor.release_digest
        );
        assert_fetch_retry_and_reopen_reject(repo, &expected, &path, INVALID_RECORD);
    }
}
