use super::{invalid, Failure};
use crate::args::Cli;
use latent_artifacts::package::{validate_package_path, PackageLimits};
use latent_oci::{OciReference, RegistryConfig, RegistryCredentials, RegistryLimits};
use serde::{Deserialize, Deserializer};
use std::{net::SocketAddr, path::Path, time::Duration};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Profile {
    format_version: u32,
    origin: String,
    repository: String,
    addresses: Vec<SocketAddr>,
    #[serde(default)]
    allow_insecure_loopback: bool,
    #[serde(default, deserialize_with = "present")]
    credential_file: Option<String>,
    #[serde(default)]
    root_certificates: Vec<String>,
}
#[derive(Deserialize)]
#[serde(tag = "mode", rename_all = "kebab-case", deny_unknown_fields)]
enum Credentials {
    Basic { username: String, password: String },
    Bearer { token: String },
}
pub(super) struct Configured {
    pub config: RegistryConfig,
    pub reference: OciReference,
}

fn present<'de, D: Deserializer<'de>, T: Deserialize<'de>>(d: D) -> Result<Option<T>, D::Error> {
    T::deserialize(d).map(Some)
}
fn profile_error() -> Failure {
    invalid(
        "registry-profile",
        "The explicit registry profile or credential file is invalid.",
    )
}
fn selected(path: &Path, maximum: u64) -> Result<Vec<u8>, Failure> {
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(profile_error)?;
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    latent_packaging::read_package_file(parent, name, maximum).map_err(|_| profile_error())
}
fn decode(bytes: &[u8]) -> Result<Profile, Failure> {
    if bytes.len() > 16 * 1024 {
        return Err(profile_error());
    }
    let profile: Profile = serde_json::from_slice(bytes).map_err(|_| profile_error())?;
    if profile.format_version != 1
        || profile.origin.len() > 512
        || profile.repository.len() > 255
        || profile.addresses.len() > 16
        || profile.root_certificates.len() > 8
    {
        return Err(profile_error());
    }
    for path in profile
        .root_certificates
        .iter()
        .chain(profile.credential_file.iter())
    {
        validate_package_path(path, PackageLimits::default()).map_err(|_| profile_error())?;
        if path.len() > 240 {
            return Err(profile_error());
        }
    }
    Ok(profile)
}
fn credential(bytes: &[u8]) -> Result<RegistryCredentials, Failure> {
    if bytes.len() > 16 * 1024 {
        return Err(profile_error());
    }
    Ok(
        match serde_json::from_slice::<Credentials>(bytes).map_err(|_| profile_error())? {
            Credentials::Basic { username, password } => {
                if username.is_empty()
                    || username.len() > 256
                    || username.contains(':')
                    || password.len() > 4096
                    || username
                        .chars()
                        .chain(password.chars())
                        .any(char::is_control)
                {
                    return Err(profile_error());
                }
                RegistryCredentials::Basic { username, password }
            }
            Credentials::Bearer { token } => {
                if token.is_empty()
                    || token.len() > 8192
                    || !token.bytes().all(|byte| byte.is_ascii_graphic())
                {
                    return Err(profile_error());
                }
                RegistryCredentials::Bearer(token)
            }
        },
    )
}
pub(super) fn load(path: &Path, cli: &Cli, duration: Duration) -> Result<Configured, Failure> {
    let profile = decode(&selected(path, 16 * 1024)?)?;
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let credentials = match profile.credential_file {
        Some(path) => {
            let mut bytes = latent_packaging::read_package_file(parent, &path, 16 * 1024)
                .map_err(|_| profile_error())?;
            let parsed = credential(&bytes);
            bytes.fill(0);
            parsed?
        }
        None => RegistryCredentials::Anonymous,
    };
    let roots = profile
        .root_certificates
        .iter()
        .map(|path| {
            latent_packaging::read_package_file(parent, path, 64 * 1024)
                .map_err(|_| profile_error())
        })
        .collect::<Result<Vec<_>, _>>()?;
    let authority = profile
        .origin
        .split_once("://")
        .ok_or_else(profile_error)?
        .1
        .trim_end_matches('/')
        .to_owned();
    let reference = OciReference {
        registry: authority,
        repository: profile.repository.clone(),
        reference: String::new(),
    };
    let limits = RegistryLimits {
        package: super::super::limits().package,
        max_in_flight: 1,
        max_retained_packages: 2,
        max_retained_bytes: 48 * 1024 * 1024,
        max_referrers: 24,
        max_referrer_pages: 4,
        max_referrer_total_bytes: 256 * 1024,
        connect_timeout: Duration::from_millis(cli.connect_timeout_ms.unwrap_or(5000))
            .min(Duration::from_secs(30))
            .min(duration),
        request_timeout: duration.min(Duration::from_mins(2)),
        operation_timeout: duration,
        cleanup_timeout: Duration::from_secs(2),
    };
    Ok(Configured {
        reference,
        config: RegistryConfig {
            origin: profile.origin,
            repository: profile.repository,
            credentials,
            addresses: profile.addresses,
            additional_root_certificates: roots,
            allow_insecure_loopback: profile.allow_insecure_loopback,
            limits,
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn closed_profile_rejects_null_duplicates_escapes_and_excess_entries() {
        let valid = r#"{"formatVersion":1,"origin":"https://registry.example","repository":"repo","addresses":["127.0.0.1:443"]}"#;
        assert!(decode(valid.as_bytes()).is_ok());
        for addition in [
            r#", "credentialFile":null"#,
            r#", "credentialFile":"../secret"#,
            r#", "rootCertificates":null"#,
            r#", "allowInsecureLoopback":null"#,
            r#", "formatVersion":1"#,
            r#", "token":"private"#,
        ] {
            assert!(
                decode(format!("{}{addition}}}", &valid[..valid.len() - 1]).as_bytes()).is_err()
            );
        }
        let mut value: serde_json::Value = serde_json::from_str(valid).unwrap();
        value["addresses"] = serde_json::json!(vec!["127.0.0.1:443"; 17]);
        assert!(decode(&serde_json::to_vec(&value).unwrap()).is_err());
        assert!(credential(br#"{"mode":"bearer","token":"secret","password":"hidden"}"#).is_err());
        let failure = credential(br#"{"mode":"bearer","token":"private","token":"other"}"#)
            .err()
            .unwrap();
        assert!(!format!("{failure:?}").contains("private"));
    }
    #[cfg(unix)]
    #[test]
    fn selected_profile_file_rejects_a_symlink() {
        let root = tempfile::tempdir().unwrap();
        std::fs::write(root.path().join("real"), b"secret").unwrap();
        std::os::unix::fs::symlink("real", root.path().join("link")).unwrap();
        assert!(selected(&root.path().join("link"), 100).is_err());
    }
}
