//! Ephemeral localhost identity for an explicitly selected disposable TLS peer.
//! The key is private workspace data, never publisher trust or node admission.
use std::path::Path;

use base64::{engine::general_purpose::STANDARD, Engine};
use rcgen::{BasicConstraints, CertificateParams, IsCa, Issuer, KeyPair};

pub(super) fn create(output: &Path) -> Result<(), Box<dyn std::error::Error>> {
    if !output.is_absolute() || output.exists() {
        return Err("fixture TLS requires a fresh absolute private directory".into());
    }
    let ca_key = KeyPair::generate()?;
    let mut params = CertificateParams::new(vec![])?;
    params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
    let ca = params.self_signed(&ca_key)?;
    let issuer = Issuer::new(params, &ca_key);
    let key = KeyPair::generate()?;
    let params = CertificateParams::new(vec!["localhost".into()])?;
    let cert = params.signed_by(&key, &issuer)?;
    super::authoring::directory(output)?;
    super::authoring::write(&output.join("ca.der"), ca.der())?;
    super::authoring::write(
        &output.join("server.pem"),
        pem("CERTIFICATE", cert.der()).as_bytes(),
    )?;
    super::authoring::write(
        &output.join("key.pem"),
        pem("PRIVATE KEY", &key.serialize_der()).as_bytes(),
    )?;
    Ok(())
}

fn pem(kind: &str, der: &[u8]) -> String {
    let encoded = STANDARD.encode(der);
    let mut text = format!("-----BEGIN {kind}-----\n");
    for line in encoded.as_bytes().chunks(64) {
        text.push_str(std::str::from_utf8(line).expect("base64 ASCII"));
        text.push('\n');
    }
    text.push_str(&format!("-----END {kind}-----\n"));
    text
}

#[cfg(test)]
mod tests {
    #[test]
    fn fixture_tls_is_fresh_private_and_never_replaces_an_existing_identity() {
        let root = tempfile::tempdir().unwrap();
        let first = root.path().join("one");
        let second = root.path().join("two");
        super::create(&first).unwrap();
        super::create(&second).unwrap();
        let key = std::fs::read(first.join("key.pem")).unwrap();
        assert_ne!(key, std::fs::read(second.join("key.pem")).unwrap());
        assert!(super::create(&first).is_err());
        assert_eq!(key, std::fs::read(first.join("key.pem")).unwrap());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(&first).unwrap().permissions().mode() & 0o777,
                0o700
            );
            assert_eq!(
                std::fs::metadata(first.join("key.pem"))
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o600
            );
        }
    }
}
