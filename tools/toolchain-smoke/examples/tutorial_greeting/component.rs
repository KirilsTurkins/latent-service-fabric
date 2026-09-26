// lsf-example-begin: capsule
pub fn greet(name: String) -> Result<String, String> {
    let name = name.trim();
    if name.is_empty() {
        return Err("Please enter a name.".into());
    }
    if name.len() > 100 {
        return Err("Use a name of at most 100 bytes.".into());
    }
    Ok(format!("Hello, {name}!"))
}

#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "examples/tutorial_greeting", world: "service"});
    struct Capsule;
    impl exports::examples::greeting::api::Guest for Capsule {
        fn greet(name: String) -> Result<String, String> {
            super::greet(name)
        }
    }
    export!(Capsule);
}
// lsf-example-end: capsule

#[cfg(test)]
mod tests {
    #[test]
    fn greets_trimmed_names_and_explains_invalid_input() {
        assert_eq!(super::greet("  Ada  ".into()), Ok("Hello, Ada!".into()));
        assert_eq!(
            super::greet("  ".into()),
            Err("Please enter a name.".into())
        );
        assert!(super::greet("a".repeat(101)).is_err());
    }
}
