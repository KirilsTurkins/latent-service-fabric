use latent_core::PublisherId;

use super::LocalSigner;
use crate::generate_signing_key;

#[test]
fn signer_does_not_retain_spare_capacity_from_publisher_input() {
    let generated = generate_signing_key().unwrap();
    let public = *generated.public_key();
    let mut publisher = String::with_capacity(8192);
    publisher.push_str("publisher:test");
    let signer =
        LocalSigner::from_pkcs8(generated.into_pkcs8(), PublisherId(publisher), public).unwrap();
    assert_eq!(signer.publisher.0, "publisher:test");
    assert!(signer.publisher.0.capacity() <= 128);
}
