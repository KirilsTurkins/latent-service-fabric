use crate::error;
use latent_core::{PlatformError, PlatformErrorCode};

/// Reads the one next-page relation without splitting commas inside URI/quotes.
/// The transport additionally bounds headers and validates the returned URL scope.
pub(super) fn next(value: &str) -> Result<Option<&str>, PlatformError> {
    if value.len() > 16 * 1024 {
        return Err(error(
            PlatformErrorCode::ResourceExhausted,
            "oci-link-header-limit",
        ));
    }
    let mut remaining = value.trim();
    let mut output = None;
    let mut count = 0;
    while !remaining.is_empty() {
        count += 1;
        if count > 32 {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "oci-link-count-limit",
            ));
        }
        let rest = remaining.strip_prefix('<').ok_or_else(invalid)?;
        let end = rest.find('>').ok_or_else(invalid)?;
        let url = &rest[..end];
        if url.is_empty()
            || url
                .bytes()
                .any(|b| b.is_ascii_control() || b.is_ascii_whitespace())
        {
            return Err(invalid());
        }
        remaining = rest[end + 1..].trim_start();
        let mut relation = None;
        while remaining.starts_with(';') {
            remaining = remaining[1..].trim_start();
            let end = remaining.find(['=', ';', ',']).ok_or_else(invalid)?;
            let name = remaining[..end].trim_end();
            if name.is_empty() || remaining.as_bytes()[end] != b'=' {
                return Err(invalid());
            }
            let (parameter, rest) = parameter(remaining[end + 1..].trim_start())?;
            remaining = rest.trim_start();
            if name.eq_ignore_ascii_case("rel") {
                if relation.replace(parameter).is_some() {
                    return Err(invalid());
                }
            } else if name.eq_ignore_ascii_case("anchor") {
                // An anchor changes the relation context; this profile only
                // follows pagination relative to the requested referrer list.
                return Err(invalid());
            }
        }
        if relation.is_some_and(|rel| rel.split_ascii_whitespace().any(|item| item == "next"))
            && output.replace(url).is_some()
        {
            return Err(invalid());
        }
        if !remaining.is_empty() {
            remaining = remaining
                .strip_prefix(',')
                .ok_or_else(invalid)?
                .trim_start();
            if remaining.is_empty() {
                return Err(invalid());
            }
        }
    }
    Ok(output)
}

fn parameter(value: &str) -> Result<(&str, &str), PlatformError> {
    if let Some(value) = value.strip_prefix('"') {
        let end = value.find('"').ok_or_else(invalid)?;
        let parameter = &value[..end];
        if parameter.contains('\\') || parameter.bytes().any(|b| b.is_ascii_control()) {
            return Err(invalid());
        }
        Ok((parameter, &value[end + 1..]))
    } else {
        let end = value.find([';', ',']).unwrap_or(value.len());
        let parameter = value[..end].trim_end();
        if parameter.is_empty()
            || parameter
                .bytes()
                .any(|b| b.is_ascii_whitespace() || b.is_ascii_control() || b == b'"')
        {
            return Err(invalid());
        }
        Ok((parameter, &value[end..]))
    }
}

fn invalid() -> PlatformError {
    error(
        PlatformErrorCode::InvalidArgument,
        "invalid-oci-pagination-link",
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn relation_parsing_does_not_confuse_quoted_or_uri_commas() {
        assert_eq!(
            next("</v2/r/referrers/sha256:a?last=a,b>; title=\"one,two\"; rel=\"next\"").unwrap(),
            Some("/v2/r/referrers/sha256:a?last=a,b")
        );
        assert_eq!(
            next("</previous>; rel=prev, </next>; rel=\"next alternate\"").unwrap(),
            Some("/next")
        );
        assert_eq!(next("</previous>; rel=prev").unwrap(), None);
        for value in [
            "</one>; rel=next, </two>; rel=next",
            "</one>; rel=next; rel=prev",
            "</one>; rel=next; anchor=\"/another-subject\"",
            "</one>; rel=\"next",
            "</one>; rel=next,",
            "</one>; rel=\"next\"suffix",
        ] {
            assert!(next(value).is_err());
        }
    }
}
