// lsf-example-begin: capsule
pub fn count(text: &str) -> Result<u32, String> {
    if text.len() > 4096 {
        return Err("Use text of at most 4096 bytes.".into());
    }
    u32::try_from(text.split_whitespace().count()).map_err(|_| "Too many words.".into())
}

#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "examples/tutorial_word_count", world: "service"});
    struct Capsule;
    impl exports::examples::word_count::api::Guest for Capsule {
        fn count(text: String) -> Result<u32, String> {
            super::count(&text)
        }
    }
    export!(Capsule);
}
// lsf-example-end: capsule

#[cfg(test)]
mod tests {
    #[test]
    fn counts_whitespace_separated_words_including_unicode() {
        assert_eq!(super::count(""), Ok(0));
        assert_eq!(super::count("one\t two\nthree"), Ok(3));
        assert_eq!(super::count("Grüße aus Berlin"), Ok(3));
        assert!(super::count(&"x".repeat(4097)).is_err());
    }
}
