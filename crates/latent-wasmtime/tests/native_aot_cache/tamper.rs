use super::support::{publish, Fixture, KEY, OUTPUT};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
};

fn one_receipt(root: &Path) -> PathBuf {
    let mut matches = fs::read_dir(root).unwrap().filter_map(|entry| {
        let entry = entry.unwrap();
        entry
            .file_name()
            .to_str()
            .unwrap()
            .starts_with("r-")
            .then(|| entry.path())
    });
    let only = matches.next().unwrap();
    assert!(matches.next().is_none());
    only
}

fn replace_bytes_and_unkeyed_claims(fixture: &Fixture) {
    let receipt_path = one_receipt(&fixture.receipts());
    let receipt_bytes = fs::read(&receipt_path).unwrap();
    assert!(receipt_bytes.len() <= 8192);
    let mut receipt: Value = serde_json::from_slice(&receipt_bytes).unwrap();
    let old_digest = receipt["outputDigest"].as_str().unwrap();
    let old_path = fixture
        .blobs()
        .join("objects")
        .join(format!("b-{}", &old_digest[7..]));
    let original = fs::read(old_path.join("data")).unwrap();
    assert!(!original.is_empty() && original.len() <= OUTPUT);
    // Deliberately not native code. The adversary also supplies the correct SHA
    // and size, so raw-cache integrity recovery alone cannot reject this object.
    let substituted = vec![0xa5; original.len()];
    let hex = format!("{:x}", Sha256::digest(&substituted));
    let key = format!("b-{hex}");
    let replacement = old_path.parent().unwrap().join(&key);
    fs::write(old_path.join("data"), &substituted).unwrap();
    fs::write(
        old_path.join("ENTRY.json"),
        serde_json::to_vec(&json!({
            "formatVersion": 1, "key": key, "sizeBytes": substituted.len(),
        }))
        .unwrap(),
    )
    .unwrap();
    fs::rename(old_path, replacement).unwrap();
    receipt["outputDigest"] = json!(format!("sha256:{hex}"));
    receipt["outputSize"] = json!(substituted.len());
    // Keep the expected compiler/compatibility assertions and old MAC. The
    // attacker cannot turn their self-asserted byte provenance into approval.
    fs::write(receipt_path, serde_json::to_vec(&receipt).unwrap()).unwrap();
}

#[tokio::test(flavor = "current_thread")]
async fn replaced_bytes_with_matching_sha_and_wrong_host_key_never_reach_the_loader() {
    for replace_bytes in [true, false] {
        let fixture = Fixture::new();
        let repository = fixture.catalog();
        let release = publish(&repository, false).await;
        let first = fixture.session(repository.clone(), KEY);
        drop(first.prepare(repository.clone(), &release).await.unwrap());
        first.idle();
        assert_eq!(first.snapshot().receipts.entries, 1);
        drop(first);
        if replace_bytes {
            replace_bytes_and_unkeyed_claims(&fixture);
        }
        let key = if replace_bytes { KEY } else { [91; 32] };
        let reopened = fixture.session(repository.clone(), key);
        assert_eq!(reopened.snapshot().images.loader_attempts, 0);
        let ready = reopened
            .prepare(repository.clone(), &release)
            .await
            .unwrap();
        let snapshot = reopened.snapshot();
        assert_eq!(snapshot.cache_rejections, 1);
        assert_eq!(snapshot.cache_hits, 0);
        assert_eq!(snapshot.isolated_compilations, 1);
        // Exactly one loader call, for the newly authenticated real output.
        // Attempting to load attacker bytes first would make this two or fail.
        assert_eq!(snapshot.images.loader_attempts, 1);
        reopened.answer(ready).await;
        reopened.idle();
    }
}
