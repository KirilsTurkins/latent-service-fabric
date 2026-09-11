use super::super::Result;

const NAME: &[u8] = b"latent-artifact-identity-padding-v1";

fn leb(mut value: usize) -> Vec<u8> {
    let mut result = Vec::with_capacity(5);
    loop {
        let byte = u8::try_from(value & 127).expect("seven bits fit in u8");
        value >>= 7;
        result.push(byte | if value == 0 { 0 } else { 128 });
        if value == 0 {
            return result;
        }
    }
}

pub(super) fn pad(mut source: Vec<u8>, target: Option<usize>) -> Result<Vec<u8>> {
    let Some(target) = target else {
        return Ok(source);
    };
    let available = target.checked_sub(source.len()).ok_or("padding-target")?;
    let name_length = leb(NAME.len());
    let body = (1..=5)
        .filter_map(|width| available.checked_sub(1 + width).map(|body| (width, body)))
        .find(|(width, body)| leb(*body).len() == *width && *body >= name_length.len() + NAME.len())
        .map(|(_, body)| body)
        .ok_or("padding-target")?;
    source
        .try_reserve_exact(available)
        .map_err(|_| "padding-allocation")?;
    source.push(0);
    source.extend(leb(body));
    source.extend(name_length);
    source.extend_from_slice(NAME);
    source.resize(target, 0);
    Ok(source)
}

pub(super) fn validate(bytes: &[u8]) -> Result<()> {
    if !bytes.starts_with(b"\0asm\x0d\0\x01\0") {
        return Err("input-not-component");
    }
    wasmparser::Validator::new()
        .validate_all(bytes)
        .map_err(|_| "invalid-component")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{pad, validate};

    #[test]
    fn exact_padding_preserves_executable_sections_and_validates_at_leb_boundaries() {
        let original = b"\0asm\x0d\0\x01\0".to_vec();
        for target in [127, 128, 129, 16_383, 16_384, 16_385] {
            let padded = pad(original.clone(), Some(target)).unwrap();
            assert_eq!(padded.len(), target);
            assert!(padded.starts_with(&original));
            validate(&padded).unwrap();
            assert_eq!(padded[8], 0, "only a custom section is appended");
        }
    }

    #[test]
    fn rejects_truncation_invalid_component_and_too_small_custom_section() {
        let original = b"\0asm\x0d\0\x01\0".to_vec();
        assert!(pad(original.clone(), Some(7)).is_err());
        assert!(pad(original, Some(12)).is_err());
        assert!(validate(b"\0asm\x01\0\0\0").is_err());
        assert!(validate(b"\0asm\x0d\0\x01\0\x01\xff").is_err());
    }
}
