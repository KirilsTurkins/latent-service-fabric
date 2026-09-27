//! Host-produced CSP from bounded, signed identities; never arbitrary policy text.
use base64::{engine::general_purpose::STANDARD, Engine as _};
use latent_ingress::http::browser;

pub(super) fn policy(hashes: &[String]) -> Result<Option<String>, u16> {
    if hashes.is_empty() {
        return Ok(None);
    }
    if hashes.len() > latent_artifacts::web::MAX_WEB_STYLE_HASHES {
        return Err(502);
    }
    let (prefix, suffix) = browser::CSP.split_once("style-src 'self'").ok_or(502u16)?;
    let mut result = String::new();
    result
        .try_reserve_exact(browser::CSP.len() + hashes.len() * 54)
        .map_err(|_| 503u16)?;
    result.push_str(prefix);
    result.push_str("style-src 'self'");
    for hash in hashes {
        let hex = hash
            .strip_prefix("sha256:")
            .filter(|value| value.len() == 64)
            .ok_or(502u16)?;
        let mut bytes = [0; 32];
        for (target, digits) in bytes.iter_mut().zip(hex.as_bytes().chunks_exact(2)) {
            let digit = |value: u8| match value {
                b'0'..=b'9' => Ok(value - b'0'),
                b'a'..=b'f' => Ok(value - b'a' + 10),
                _ => Err(502u16),
            };
            *target = digit(digits[0])? * 16 + digit(digits[1])?;
        }
        result.push_str(" 'sha256-");
        STANDARD.encode_string(bytes, &mut result);
        result.push('\'');
    }
    result.push_str(suffix);
    Ok(Some(result))
}

#[cfg(test)]
mod tests {
    use super::policy;
    #[test]
    fn signed_style_identities_only_extend_styles_and_reject_policy_text() {
        let value = policy(&[format!("sha256:{}", "00".repeat(32))])
            .unwrap()
            .unwrap();
        assert!(value
            .contains("style-src 'self' 'sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=';"));
        assert!(value.contains("script-src 'self';"));
        assert!(value.contains("base-uri 'none';"));
        assert!(
            !value.contains("unsafe-inline")
                && !value.contains("unsafe-eval")
                && !value.contains("nonce-")
        );
        assert_eq!(policy(&[]).unwrap(), None);
        assert_eq!(policy(&["'unsafe-inline'".into()]).unwrap_err(), 502);
        assert_eq!(
            policy(&vec![format!("sha256:{}", "00".repeat(32)); 65]).unwrap_err(),
            502
        );
    }
}
