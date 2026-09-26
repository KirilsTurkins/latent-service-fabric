//! `SigV4` over the exact path/query sent. No ambient credentials or token refresh.
use super::{sha, text, BlobError, Result};
use latent_capabilities::broker::secrets::{ProviderCredential, SecretError};
use latent_http::protocol::ProtocolHeader;
use ring::hmac;
use zeroize::Zeroizing;

pub(super) fn encode(value: &str, slash: bool) -> String {
    let mut out = String::new();
    for b in value.bytes() {
        if b.is_ascii_alphanumeric() || b"-._~".contains(&b) || (slash && b == b'/') {
            out.push(char::from(b));
        } else {
            use std::fmt::Write;
            let _ = write!(out, "%{b:02X}");
        }
    }
    out
}
pub(super) fn query(values: &[(&str, &str)]) -> String {
    let mut pairs: Vec<_> = values
        .iter()
        .map(|(k, v)| (encode(k, false), encode(v, false)))
        .collect();
    pairs.sort();
    pairs
        .into_iter()
        .map(|(k, v)| format!("{k}={v}"))
        .collect::<Vec<_>>()
        .join("&")
}
pub(super) fn timestamp() -> Result<String> {
    let now = time::OffsetDateTime::now_utc();
    if !(2020..=9999).contains(&now.year()) {
        return Err(BlobError::Unavailable);
    }
    now.format(time::macros::format_description!(
        "[year][month][day]T[hour][minute][second]Z"
    ))
    .map_err(|_| BlobError::Unavailable)
}
/// Tuple format: access key, secret key, optional session token separated by LF.
/// All fields belong to one protected reference and therefore rotate atomically.
pub(super) fn headers(
    credential: &dyn ProviderCredential,
    input: Input<'_>,
    extra: &[(&str, &str)],
) -> Result<Vec<ProtocolHeader>> {
    let mut result = Err(BlobError::PermissionDenied);
    credential
        .with_current_value(&mut |bytes| {
            result = sign(bytes, &input, extra);
            if result.is_ok() {
                Ok(())
            } else {
                Err(SecretError::PermissionDenied)
            }
        })
        .map_err(|_| BlobError::PermissionDenied)?;
    result
}
#[derive(Clone, Copy)]
pub(super) struct Input<'a> {
    pub method: &'a str,
    pub path: &'a str,
    pub query: &'a str,
    pub host: &'a str,
    pub region: &'a str,
    pub time: &'a str,
    pub payload_sha: &'a str,
}
fn sign(bytes: &[u8], input: &Input<'_>, extra: &[(&str, &str)]) -> Result<Vec<ProtocolHeader>> {
    if bytes.len() > 8192
        || input.time.len() != 16
        || !super::hex(input.payload_sha, 64)
        || extra.len() > 8
    {
        return Err(BlobError::PermissionDenied);
    }
    let value = std::str::from_utf8(bytes).map_err(|_| BlobError::PermissionDenied)?;
    let mut fields = value.split('\n');
    let access = fields.next().unwrap_or("");
    let secret = fields.next().unwrap_or("");
    let token = fields.next();
    if !text(access, 128)
        || !access.bytes().all(|b| b.is_ascii_alphanumeric())
        || !text(secret, 256)
        || !secret.bytes().all(|b| (33..=126).contains(&b))
        || token.is_some_and(|t| !text(t, 4096) || !t.bytes().all(|b| (33..=126).contains(&b)))
        || fields.next().is_some()
    {
        return Err(BlobError::PermissionDenied);
    }
    let mut values = vec![
        ("host", input.host),
        ("x-amz-content-sha256", input.payload_sha),
        ("x-amz-date", input.time),
    ];
    if let Some(token) = token {
        values.push(("x-amz-security-token", token));
    }
    values.extend_from_slice(extra);
    values.sort_by_key(|v| v.0);
    let mut canonical = Zeroizing::new(String::new());
    let mut names = String::new();
    let mut headers = Vec::with_capacity(values.len() + 1);
    for (i, (name, value)) in values.iter().enumerate() {
        if name.len() > 64
            || !name
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
            || !text(value, 4096)
            || value.trim() != *value
            || value.bytes().any(|b| b.is_ascii_whitespace())
            || (i > 0 && values[i - 1].0 == *name)
        {
            return Err(BlobError::InvalidRange);
        }
        canonical.push_str(name);
        canonical.push(':');
        canonical.push_str(value);
        canonical.push('\n');
        if i > 0 {
            names.push(';');
        }
        names.push_str(name);
        headers.push(ProtocolHeader {
            name: (*name).into(),
            value: Zeroizing::new((*value).into()),
            sensitive: *name == "x-amz-security-token",
        });
    }
    let canonical = Zeroizing::new(format!(
        "{}\n{}\n{}\n{}\n{}\n{}",
        input.method, input.path, input.query, *canonical, names, input.payload_sha
    ));
    let date = &input.time[..8];
    let scope = format!("{date}/{}/s3/aws4_request", input.region);
    let to_sign = format!(
        "AWS4-HMAC-SHA256\n{}\n{}\n{}",
        input.time,
        scope,
        sha(canonical.as_bytes())
    );
    let key = Zeroizing::new(format!("AWS4{secret}"));
    let dated = mac(key.as_bytes(), date.as_bytes());
    let regional = mac(&*dated, input.region.as_bytes());
    let service = mac(&*regional, b"s3");
    let signing = mac(&*service, b"aws4_request");
    let signature = mac(&*signing, to_sign.as_bytes());
    let signature = super::hex_bytes(&*signature);
    headers.push(ProtocolHeader {
        name: "authorization".into(), sensitive: true,
        value: Zeroizing::new(format!("AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={names}, Signature={signature}")),
    });
    Ok(headers)
}
fn mac(key: &[u8], input: &[u8]) -> Zeroizing<[u8; 32]> {
    let value = hmac::sign(&hmac::Key::new(hmac::HMAC_SHA256, key), input);
    let mut result = Zeroizing::new([0; 32]);
    result.copy_from_slice(value.as_ref());
    result
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn aws_published_get_vector_and_encoded_query() {
        let input = Input {
            method: "GET",
            path: "/test.txt",
            query: "",
            host: "examplebucket.s3.amazonaws.com",
            region: "us-east-1",
            time: "20130524T000000Z",
            payload_sha: &sha(b""),
        };
        let result = sign(
            b"AKIAIOSFODNN7EXAMPLE\nwJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            &input,
            &[("range", "bytes=0-9")],
        )
        .unwrap();
        assert!(result.last().unwrap().value.ends_with(
            "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
        ));
        assert_eq!(
            query(&[("uploadId", "a+/= ?"), ("partNumber", "1")]),
            "partNumber=1&uploadId=a%2B%2F%3D%20%3F"
        );
        assert_eq!(encode("a//b/../c", true), "a//b/../c");
    }
}
