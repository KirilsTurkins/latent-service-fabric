use super::*;

fn inconsistent_records(record: &[u8]) -> Vec<(&'static str, Option<Vec<u8>>)> {
    let value: json::Value = json::from_slice(record).unwrap();
    let changed_digest = release_digest(b"different payload").0;
    let mut cases = vec![
        ("missing", None),
        ("empty", Some(Vec::new())),
        ("truncated", Some(record[..record.len() / 2].to_vec())),
        ("malformed", Some(b"not JSON".to_vec())),
        ("wrong outer type", Some(b"null".to_vec())),
        ("oversized", Some(vec![b' '; 1025])),
        (
            "unsupported version",
            Some(replace_once(
                record,
                "\"format_version\":1",
                "\"format_version\":2",
            )),
        ),
        (
            "missing version",
            Some(replace_once(record, "\"format_version\":1,", "")),
        ),
        (
            "duplicate field",
            Some(replace_once(
                record,
                "\"format_version\":1",
                "\"format_version\":1,\"format_version\":1",
            )),
        ),
        (
            "unknown field",
            Some(replace_once(record, "}", ",\"unknown\":true}")),
        ),
        (
            "noncanonical whitespace",
            Some([b" ".as_slice(), record].concat()),
        ),
        ("trailing data", Some([record, b"{}".as_slice()].concat())),
        (
            "size mismatch",
            Some(replace_once(
                record,
                "\"component_size_bytes\":3",
                "\"component_size_bytes\":4",
            )),
        ),
    ];
    // Exact token replacement preserves the canonical field order, so these
    // fixtures reach digest validation rather than failing JSON canonicality.
    for field in ["component_digest", "metadata_digest", "manifest_digest"] {
        let original = format!("\"{field}\":\"{}\"", value[field].as_str().unwrap());
        let changed = format!("\"{field}\":\"{changed_digest}\"");
        cases.push((field, Some(replace_once(record, &original, &changed))));
    }
    let original = format!(
        "\"component_digest\":\"{}\"",
        value["component_digest"].as_str().unwrap()
    );
    let uppercase = original
        .to_ascii_uppercase()
        .replace("COMPONENT_DIGEST", "component_digest");
    cases.push((
        "noncanonical digest",
        Some(replace_once(record, &original, &uppercase)),
    ));
    cases
}

#[test]
fn damaged_or_inconsistent_completion_records_never_acknowledge_existing_content() {
    let template = TempRoot::new();
    let expected = artifact("record-damage", b"abc");
    let template_repo = repository(template.path());
    block_on(template_repo.publish(expected.clone())).unwrap();
    let record = fs::read(
        release_dir(template_repo.root(), &expected.descriptor.release_digest).join("COMPLETE"),
    )
    .unwrap();
    for (case, replacement) in inconsistent_records(&record) {
        let temp = TempRoot::new();
        let repo = repository(temp.path());
        block_on(repo.publish(expected.clone())).unwrap();
        let path = release_dir(repo.root(), &expected.descriptor.release_digest);
        match replacement {
            Some(bytes) => fs::write(path.join("COMPLETE"), bytes).unwrap(),
            None => fs::remove_file(path.join("COMPLETE")).unwrap(),
        }
        assert_eq!(
            fs::read(path.join("component.wasm")).unwrap(),
            b"abc",
            "{case}"
        );
        assert_fetch_retry_and_reopen_reject(repo, &expected, &path, INVALID_RECORD);
    }
}

#[test]
fn valid_completion_records_cannot_be_swapped_between_equal_sized_components() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let first = artifact("first", b"one");
    let second = artifact("second", b"two");
    block_on(repo.publish(first.clone())).unwrap();
    block_on(repo.publish(second.clone())).unwrap();
    let first_path = release_dir(repo.root(), &first.descriptor.release_digest);
    let second_path = release_dir(repo.root(), &second.descriptor.release_digest);
    let first_record = fs::read(first_path.join("COMPLETE")).unwrap();
    let second_record = fs::read(second_path.join("COMPLETE")).unwrap();
    fs::write(first_path.join("COMPLETE"), &second_record).unwrap();
    fs::write(second_path.join("COMPLETE"), &first_record).unwrap();
    assert_corrupt(
        block_on(repo.fetch(&second.descriptor.release_digest)),
        INVALID_RECORD,
    );
    let second_files = entry_files(&second_path);
    assert_fetch_retry_and_reopen_reject(repo, &first, &first_path, INVALID_RECORD);
    assert_eq!(entry_files(&second_path), second_files);
}

#[test]
fn a_complete_entry_cannot_be_adopted_under_a_different_final_directory() {
    for digest_named in [true, false] {
        let temp = TempRoot::new();
        let repo = repository(temp.path());
        let expected = artifact("directory-binding", b"original component");
        block_on(repo.publish(expected.clone())).unwrap();
        let source = release_dir(repo.root(), &expected.descriptor.release_digest);
        let destination = if digest_named {
            release_dir(repo.root(), &release_digest(b"different component"))
        } else {
            repo.root().join("releases/complete-but-not-a-digest")
        };
        drop(repo);
        fs::rename(source, &destination).unwrap();
        let persisted = entry_files(&destination);
        assert_corrupt(
            DirectoryArtifactRepository::open(
                temp.path(),
                DirectoryArtifactRepositoryConfig::default(),
            ),
            "release directory does not match its digest",
        );
        assert_eq!(entry_files(&destination), persisted);
    }
}

fn assert_nonregular_record_rejected(
    repo: DirectoryArtifactRepository,
    expected: &CapsuleArtifact,
) {
    let root = repo.root().to_owned();
    let path = release_dir(&root, &expected.descriptor.release_digest);
    let completion_path = path.join("COMPLETE");
    let kind = fs::symlink_metadata(&completion_path).unwrap().file_type();
    let payloads = ["metadata.json", "manifest.json", "component.wasm"]
        .map(|name| (name, fs::read(path.join(name)).unwrap()));
    assert_corrupt(
        block_on(repo.fetch(&expected.descriptor.release_digest)),
        INVALID_RECORD,
    );
    assert_corrupt(block_on(repo.publish(expected.clone())), INVALID_RECORD);
    drop(repo);
    assert_corrupt(
        DirectoryArtifactRepository::open(root, DirectoryArtifactRepositoryConfig::default()),
        INVALID_RECORD,
    );
    assert_eq!(
        fs::symlink_metadata(completion_path).unwrap().file_type(),
        kind
    );
    for (name, bytes) in payloads {
        assert_eq!(fs::read(path.join(name)).unwrap(), bytes);
    }
}

#[test]
fn directory_completion_records_are_rejected_without_reading_them_as_files() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let expected = artifact("directory-record", b"tiny component");
    block_on(repo.publish(expected.clone())).unwrap();
    let record = release_dir(repo.root(), &expected.descriptor.release_digest).join("COMPLETE");
    fs::remove_file(&record).unwrap();
    fs::create_dir(&record).unwrap();
    assert_nonregular_record_rejected(repo, &expected);
    assert_eq!(fs::read_dir(record).unwrap().count(), 0);
}

#[cfg(unix)]
#[test]
fn symlinks_to_otherwise_valid_completion_records_are_rejected() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let expected = artifact("symlink-record", b"tiny component");
    block_on(repo.publish(expected.clone())).unwrap();
    let record = release_dir(repo.root(), &expected.descriptor.release_digest).join("COMPLETE");
    let valid_bytes = fs::read(&record).unwrap();
    let target = repo.root().join("valid-record-target");
    fs::write(&target, &valid_bytes).unwrap();
    fs::remove_file(&record).unwrap();
    std::os::unix::fs::symlink(&target, &record).unwrap();
    assert_nonregular_record_rejected(repo, &expected);
    assert_eq!(fs::read(target).unwrap(), valid_bytes);
}
