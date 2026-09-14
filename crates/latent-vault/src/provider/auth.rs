use super::{Digest, Inner, Result, SecretError, Sha256};
use latent_http::protocol::ProtocolHeader;
use zeroize::Zeroizing;

pub(super) struct Auth {
    pub header: Zeroizing<String>,
    pub stamp: Zeroizing<[u8; 32]>,
}
impl Auth {
    pub fn current(inner: &Inner, index: usize) -> Result<Self> {
        let mut auth = None;
        inner.credential(index).with_current_value(&mut |bytes| {
            if bytes.is_empty()
                || bytes.len() > 4096
                || !bytes.iter().all(|b| (0x21..=0x7e).contains(b))
            {
                return Err(SecretError::PermissionDenied);
            }
            let header = Zeroizing::new(
                std::str::from_utf8(bytes)
                    .map_err(|_| SecretError::PermissionDenied)?
                    .to_owned(),
            );
            auth = Some(Self {
                header,
                stamp: Zeroizing::new(Sha256::digest(bytes).into()),
            });
            Ok(())
        })?;
        auth.ok_or(SecretError::PermissionDenied)
    }
    pub fn headers(self, inner: &Inner) -> (Vec<ProtocolHeader>, Zeroizing<[u8; 32]>) {
        let mut headers = vec![
            ProtocolHeader {
                name: "host".into(),
                value: Zeroizing::new(inner.config.host()),
                sensitive: false,
            },
            ProtocolHeader {
                name: "x-vault-token".into(),
                value: self.header,
                sensitive: true,
            },
        ];
        if let Some(namespace) = &inner.config.namespace {
            headers.push(ProtocolHeader {
                name: "x-vault-namespace".into(),
                value: Zeroizing::new(namespace.clone()),
                sensitive: false,
            });
        }
        (headers, self.stamp)
    }
}
pub(super) fn with_current(
    inner: &Inner,
    index: usize,
    stamp: &[u8; 32],
    action: &mut dyn FnMut() -> Result<()>,
) -> Result<()> {
    inner.credential(index).with_current_value(&mut |bytes| {
        if bytes.is_empty() || bytes.len() > 4096 {
            return Err(SecretError::PermissionDenied);
        }
        let now = Zeroizing::new(<[u8; 32]>::from(Sha256::digest(bytes)));
        if *now != *stamp {
            return Err(SecretError::Unavailable);
        }
        action()
    })
}
