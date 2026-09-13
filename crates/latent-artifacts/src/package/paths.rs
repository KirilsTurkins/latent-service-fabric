use super::{invalid, PackageLimits};
use latent_core::PlatformError;
use std::collections::BTreeSet;

pub(super) fn path(value: &str, limits: PackageLimits) -> Result<(), PlatformError> {
    if value.is_empty()
        || value.len() > limits.max_path_bytes
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-' | b'/'))
    {
        return Err(invalid("invalid-package-path"));
    }
    for part in value.split('/') {
        if part.is_empty() || part.len() > 64 || matches!(part, "." | "..") || part.ends_with('.') {
            return Err(invalid("invalid-package-path"));
        }
        let base = part
            .split('.')
            .next()
            .unwrap_or_default()
            .to_ascii_uppercase();
        if matches!(base.as_str(), "CON" | "PRN" | "AUX" | "NUL")
            || base
                .strip_prefix("COM")
                .or_else(|| base.strip_prefix("LPT"))
                .is_some_and(|suffix| {
                    suffix.len() == 1 && matches!(suffix.as_bytes()[0], b'1'..=b'9')
                })
        {
            return Err(invalid("reserved-package-path"));
        }
    }
    Ok(())
}

pub(super) fn unique_paths<'a>(
    paths: impl Iterator<Item = &'a str>,
    limits: PackageLimits,
) -> Result<(), PlatformError> {
    let mut seen = BTreeSet::new();
    let mut previous = None;
    for value in paths {
        path(value, limits)?;
        if previous.is_some_and(|prior| prior >= value) {
            return Err(invalid("unordered-package-layers"));
        }
        previous = Some(value);
        if !seen.insert(value.to_ascii_lowercase()) {
            return Err(invalid("colliding-package-path"));
        }
    }
    for value in &seen {
        for (offset, _) in value.match_indices('/') {
            if seen.contains(&value[..offset]) {
                return Err(invalid("package-file-prefix-collision"));
            }
        }
    }
    Ok(())
}

pub(super) fn name(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.bytes().all(|b| {
            b.is_ascii_lowercase() || b.is_ascii_digit() || matches!(b, b'.' | b'_' | b'-')
        })
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value.as_bytes()[value.len() - 1].is_ascii_alphanumeric()
}

pub(super) fn version(value: &str) -> bool {
    if value.is_empty() || value.len() > 128 {
        return false;
    }
    let (without_build, build) = value
        .split_once('+')
        .map_or((value, None), |(v, b)| (v, Some(b)));
    if build.is_some_and(|b| !identifiers(b, false)) {
        return false;
    }
    let (core, pre) = without_build
        .split_once('-')
        .map_or((without_build, None), |(v, p)| (v, Some(p)));
    if pre.is_some_and(|p| !identifiers(p, true)) {
        return false;
    }
    let mut numbers = core.split('.');
    (0..3).all(|_| numbers.next().is_some_and(numeric)) && numbers.next().is_none()
}
fn numeric(value: &str) -> bool {
    !value.is_empty()
        && value.bytes().all(|b| b.is_ascii_digit())
        && (value.len() == 1 || !value.starts_with('0'))
}
fn identifiers(value: &str, prerelease: bool) -> bool {
    value.split('.').all(|part| {
        !part.is_empty()
            && part.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
            && (!prerelease || !part.bytes().all(|b| b.is_ascii_digit()) || numeric(part))
    })
}

pub(super) fn media_type(value: &str) -> bool {
    if value.len() > 128 {
        return false;
    }
    value.split_once('/').is_some_and(|(a, b)| {
        !a.is_empty()
            && !b.is_empty()
            && a.as_bytes()[0].is_ascii_alphanumeric()
            && b.as_bytes()[0].is_ascii_alphanumeric()
            && a.bytes().chain(b.bytes()).all(|c| {
                c.is_ascii_lowercase()
                    || c.is_ascii_digit()
                    || matches!(c, b'.' | b'+' | b'-' | b'_')
            })
    })
}
