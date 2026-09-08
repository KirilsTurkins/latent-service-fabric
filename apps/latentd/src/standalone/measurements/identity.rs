//! Bind the bytes loaded by this child to the parent's pre-execution identities.

use serde_json::Value;

use super::Result;

pub(super) fn validate_components(identity: &Value, components: [(&str, &[u8]); 3]) -> Result<()> {
    let rows = identity["fixtures"]
        .as_array()
        .filter(|rows| rows.len() == components.len())
        .ok_or_else(invalid)?;
    for (name, bytes) in components {
        let mut matching = rows.iter().filter(|row| row["name"] == name);
        let row = matching.next().ok_or_else(invalid)?;
        let expected_bytes = bytes.len().to_string();
        if matching.next().is_some()
            || row.as_object().is_none_or(|object| {
                object.len() != 3
                    || !object.contains_key("name")
                    || !object.contains_key("sha256")
                    || !object.contains_key("bytes")
            })
            || row["sha256"] != latent_artifacts::content_digest(bytes).0
            || row["bytes"].as_str() != Some(expected_bytes.as_str())
        {
            return Err(invalid().into());
        }
    }
    Ok(())
}

fn invalid() -> std::io::Error {
    std::io::Error::other("loaded measurement fixture identity mismatch")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn components() -> [(&'static str, &'static [u8]); 3] {
        [
            ("echo", b"echo"),
            ("generic", b"generic"),
            ("capabilities", b"capabilities"),
        ]
    }

    fn identity() -> Value {
        json!({"fixtures":components().map(|(name,bytes)|json!({
            "name":name,"sha256":latent_artifacts::content_digest(bytes).0,
            "bytes":bytes.len().to_string()}))})
    }

    #[test]
    fn loaded_bytes_must_match_even_when_their_length_is_unchanged() {
        let identity = identity();
        validate_components(&identity, components()).unwrap();
        let mut changed = components();
        changed[0].1 = b"Echo";
        assert!(validate_components(&identity, changed).is_err());
    }

    #[test]
    fn required_fixture_names_and_lengths_are_exact() {
        let mut duplicate = identity();
        duplicate["fixtures"][1]["name"] = json!("echo");
        assert!(validate_components(&duplicate, components()).is_err());
        let mut absent = identity();
        absent["fixtures"].as_array_mut().unwrap().pop().unwrap();
        assert!(validate_components(&absent, components()).is_err());
        let mut extra = identity();
        extra["fixtures"]
            .as_array_mut()
            .unwrap()
            .push(json!({"name":"extra"}));
        assert!(validate_components(&extra, components()).is_err());
        let mut padded = identity();
        padded["fixtures"][0]["bytes"] = json!("04");
        assert!(validate_components(&padded, components()).is_err());
    }
}
