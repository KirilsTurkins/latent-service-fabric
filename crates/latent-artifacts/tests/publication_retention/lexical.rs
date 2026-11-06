use crate::support::{mutate, publish, request, Root};
use latent_artifacts::{
    DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig, PublicationRetentionAction,
};
use latent_core::PlatformErrorCode;
use std::fs;

#[test]
fn excessive_lexical_resources_refuse_before_cleanup() {
    let cases = [
        format!("{}0{}", "[".repeat(17), "]".repeat(17)),
        format!("\"{}\"", "x".repeat(4097)),
        format!("[{}0]", "0,".repeat(131_072)),
    ];
    for bytes in cases {
        let root = Root::new();
        let repo = root.open();
        let publication = publish(&repo, "lexical");
        mutate(
            &repo,
            request(
                &repo,
                &[publication],
                "pin",
                PublicationRetentionAction::Pin,
            ),
        )
        .unwrap();
        drop(repo);
        fs::write(root.path().join("lifecycle/retention/HEAD"), bytes).unwrap();
        let pending = root.path().join(".tmp/must-survive");
        fs::write(&pending, b"pending protected bytes").unwrap();
        let error = DirectoryArtifactRepository::open(
            root.path(),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .err()
        .expect("oversized lexical structure must refuse");
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(fs::read(pending).unwrap(), b"pending protected bytes");
    }
}
