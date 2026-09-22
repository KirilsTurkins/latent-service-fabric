//! Closed, bounded negotiation for static documents. No substring matching.
use super::request::{qvalue, single};

#[derive(Clone, Copy)]
struct Range<'a> {
    kind: &'a str,
    subtype: &'a str,
    quality: u16,
    parameterized: bool,
}

pub(super) struct Accept<'a> {
    ranges: [Option<Range<'a>>; 16],
    present: bool,
}
impl<'a> Accept<'a> {
    pub(super) fn parse(value: Option<&'a str>) -> Result<Self, u16> {
        let mut result = Self {
            ranges: [None; 16],
            present: value.is_some(),
        };
        let Some(value) = value else {
            return Ok(result);
        };
        if value.len() > 2048 {
            return Err(431);
        }
        for (index, entry) in sections(value, b',').enumerate() {
            if index >= result.ranges.len() {
                return Err(431);
            }
            let mut parts = sections(entry?.trim(), b';');
            let (kind, subtype) = parts
                .next()
                .ok_or(400u16)??
                .trim()
                .split_once('/')
                .ok_or(400u16)?;
            let token = |value: &str| {
                !value.is_empty()
                    && value
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&b))
            };
            if !token(kind)
                || !token(subtype)
                || (kind == "*" && subtype != "*")
                || (kind.contains('*') && kind != "*")
                || (subtype.contains('*') && subtype != "*")
            {
                return Err(400);
            }
            let (quality, parameterized) = parameters(parts)?;
            if !parameterized
                && result.ranges[..index].iter().flatten().any(|r| {
                    !r.parameterized
                        && r.kind.eq_ignore_ascii_case(kind)
                        && r.subtype.eq_ignore_ascii_case(subtype)
                })
            {
                return Err(400);
            }
            result.ranges[index] = Some(Range {
                kind,
                subtype,
                quality,
                parameterized,
            });
        }
        Ok(result)
    }
    pub(super) fn allows(&self, media: &str) -> bool {
        if !self.present {
            return true;
        }
        let Some((kind, subtype)) = media.split_once('/') else {
            return false;
        };
        self.ranges
            .iter()
            .flatten()
            // Published media types in this profile contain no parameters.
            // A valid preference for another representation (e.g. Chrome's
            // signed-exchange;v=b3) must not reject an otherwise eligible HTML.
            .filter(|r| !r.parameterized)
            .filter_map(|r| {
                let specificity = if r.kind.eq_ignore_ascii_case(kind)
                    && r.subtype.eq_ignore_ascii_case(subtype)
                {
                    2
                } else if r.kind.eq_ignore_ascii_case(kind) && r.subtype == "*" {
                    1
                } else if r.kind == "*" && r.subtype == "*" {
                    0
                } else {
                    return None;
                };
                Some((specificity, r.quality))
            })
            .max_by_key(|(specificity, _)| *specificity)
            .is_some_and(|(_, q)| q != 0)
    }
    fn explicit_html(&self) -> bool {
        self.ranges.iter().flatten().any(|r| {
            !r.parameterized
                && r.kind.eq_ignore_ascii_case("text")
                && r.subtype.eq_ignore_ascii_case("html")
                && r.quality != 0
        })
    }
}

fn sections(value: &str, delimiter: u8) -> impl Iterator<Item = Result<&str, u16>> {
    let mut remaining = Some(value);
    std::iter::from_fn(move || {
        let value = remaining.take()?;
        let (mut quoted, mut escaped) = (false, false);
        for (index, byte) in value.bytes().enumerate() {
            if (byte < 0x20 && byte != b'\t') || byte == 0x7f {
                return Some(Err(400));
            }
            if escaped {
                escaped = false;
            } else if quoted && byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                quoted = !quoted;
            } else if !quoted && byte == delimiter {
                remaining = Some(&value[index + 1..]);
                return Some(Ok(&value[..index]));
            }
        }
        Some(if quoted || escaped {
            Err(400)
        } else {
            Ok(value)
        })
    })
}

fn quoted_parameter(value: &str) -> bool {
    let Some(inner) = value.strip_prefix('"').and_then(|v| v.strip_suffix('"')) else {
        return false;
    };
    let mut escaped = false;
    for byte in inner.bytes() {
        if escaped {
            escaped = false;
        } else if byte == b'\\' {
            escaped = true;
        } else if byte == b'"' {
            return false;
        }
    }
    !escaped
}

fn parameters<'a>(parts: impl Iterator<Item = Result<&'a str, u16>>) -> Result<(u16, bool), u16> {
    let (mut quality, mut parameterized) = (1000, false);
    let mut names: [Option<&str>; 8] = [None; 8];
    let token = |value: &str| {
        !value.is_empty()
            && value
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&b))
    };
    for (index, part) in parts.enumerate() {
        if index == names.len() {
            return Err(431);
        }
        let (name, value) = part?.trim().split_once('=').ok_or(400u16)?;
        let (name, value) = (name.trim(), value.trim());
        if !token(name)
            || names[..index]
                .iter()
                .flatten()
                .any(|n| n.eq_ignore_ascii_case(name))
        {
            return Err(400);
        }
        names[index] = Some(name);
        if name.eq_ignore_ascii_case("q") {
            quality = qvalue(value)?;
        } else {
            if !token(value) && !quoted_parameter(value) {
                return Err(400);
            }
            parameterized = true;
        }
    }
    Ok((quality, parameterized))
}

pub(super) fn navigation(
    headers: &[httparse::Header<'_>],
    accept: &Accept<'_>,
) -> Result<bool, u16> {
    let mode = single(headers, "sec-fetch-mode")?;
    let destination = single(headers, "sec-fetch-dest")?;
    let metadata = headers.iter().any(|h| {
        h.name
            .get(..10)
            .is_some_and(|n| n.eq_ignore_ascii_case("sec-fetch-"))
    });
    Ok(if metadata {
        mode == Some("navigate") && destination == Some("document")
    } else {
        accept.explicit_html()
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accept_uses_specific_quality_and_bounded_unambiguous_ranges() {
        let accepted = Accept::parse(Some("text/html;q=0, text/*;q=0.5, */*;q=1")).unwrap();
        assert!(!accepted.allows("text/html"));
        assert!(accepted.allows("text/css"));
        assert!(accepted.allows("application/json"));
        for invalid in [
            "",
            "html",
            "text/html;q=1.001",
            "text/html;q=-1",
            "text/html;q=0.1234",
            "text/html;q=0;q=1",
            "text/html,text/HTML",
            "text/html; charset",
            "*/html",
            "text/ht*ml",
        ] {
            assert!(Accept::parse(Some(invalid)).is_err(), "{invalid}");
        }
        assert!(Accept::parse(Some(&"text/html,".repeat(17))).is_err());
        assert!(Accept::parse(Some(&"x".repeat(2049))).is_err());
        let browser = Accept::parse(Some("text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7")).unwrap();
        assert!(browser.allows("text/html") && browser.explicit_html());
        for range in [
            "text/html;charset=utf-8",
            "text/html;version=one;q=1",
            "text/html;label=\"a,b;c\"",
        ] {
            let accepted = Accept::parse(Some(range)).unwrap();
            assert!(!accepted.allows("text/html") && !accepted.explicit_html());
        }
        for range in [
            "text/html;v=a;V=b",
            "text/html;v=\"unterminated",
            "text/html;v=x;q=0;q=1",
        ] {
            assert!(Accept::parse(Some(range)).is_err());
        }
    }
    #[test]
    fn navigation_requires_complete_fetch_metadata_or_explicit_html() {
        let html = Accept::parse(Some("text/html;q=0.7,application/json")).unwrap();
        let wildcard = Accept::parse(Some("*/*")).unwrap();
        assert!(navigation(&[], &html).unwrap());
        assert!(!navigation(&[], &wildcard).unwrap());
        assert!(!navigation(&[], &Accept::parse(Some("application/json")).unwrap()).unwrap());
        for (mode, destination, expected) in [
            ("navigate", "document", true),
            ("cors", "script", false),
            ("navigate", "image", false),
            ("same-origin", "empty", false),
        ] {
            let headers = [
                httparse::Header {
                    name: "Sec-Fetch-Mode",
                    value: mode.as_bytes(),
                },
                httparse::Header {
                    name: "Sec-Fetch-Dest",
                    value: destination.as_bytes(),
                },
            ];
            assert_eq!(navigation(&headers, &html).unwrap(), expected);
        }
        assert!(!navigation(
            &[httparse::Header {
                name: "Sec-Fetch-Site",
                value: b"same-origin"
            }],
            &html
        )
        .unwrap());
        assert!(navigation(
            &[
                httparse::Header {
                    name: "Sec-Fetch-Dest",
                    value: b"document"
                },
                httparse::Header {
                    name: "sec-fetch-dest",
                    value: b"script"
                }
            ],
            &html
        )
        .is_err());
    }
}
