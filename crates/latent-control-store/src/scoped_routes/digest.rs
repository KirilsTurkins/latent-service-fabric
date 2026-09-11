use latent_core::TenantId;
use latent_routing::RouteSnapshot;
use sha2::{Digest, Sha256};
use std::fmt::Write;

/// All integers/counts/byte lengths are u64 big endian. Strings are UTF-8
/// prefixed by their byte length. Lists retain returned order; attributes use
/// their `BTreeMap` key order. Empty bindings/policies are explicitly included.
pub(super) fn calculate(tenant: &TenantId, snapshot: &RouteSnapshot) -> String {
    let mut hash = Sha256::new();
    string(&mut hash, "latent.scoped-routes.v1");
    string(&mut hash, &tenant.0);
    integer(&mut hash, snapshot.generation.0);
    integer(&mut hash, snapshot.generated_at_unix_millis);
    integer(&mut hash, snapshot.services.len() as u64);
    for service in &snapshot.services {
        string(&mut hash, &service.tenant.0);
        string(&mut hash, &service.service.0);
        string(&mut hash, &service.id.0);
        integer(&mut hash, service.revisions.len() as u64);
        for revision in &service.revisions {
            string(&mut hash, &revision.revision.0);
            string(&mut hash, &revision.release.0);
            integer(&mut hash, u64::from(revision.weight));
            integer(&mut hash, revision.attributes.len() as u64);
            for (key, value) in &revision.attributes {
                string(&mut hash, key);
                string(&mut hash, value);
            }
        }
    }
    integer(&mut hash, 0); // bindings: unsupported in this projection version
    integer(&mut hash, 0); // policy digests: unsupported in this projection version
    let mut encoded = String::with_capacity(71);
    encoded.push_str("sha256:");
    for byte in hash.finalize() {
        write!(encoded, "{byte:02x}").expect("writing to a String is infallible");
    }
    encoded
}

fn integer(hash: &mut Sha256, value: u64) {
    hash.update(value.to_be_bytes());
}
fn string(hash: &mut Sha256, value: &str) {
    integer(hash, value.len() as u64);
    hash.update(value.as_bytes());
}
