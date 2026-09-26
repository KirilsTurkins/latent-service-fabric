// lsf-example-begin: capsule
pub fn quote(items: u32, express: bool) -> Result<u32, String> {
    if !(1..=100).contains(&items) {
        return Err("Choose between 1 and 100 items.".into());
    }
    let base_cents = if express { 1200 } else { 500 };
    Ok(base_cents + items * 75)
}

#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "examples/tutorial_shipping", world: "service"});
    struct Capsule;
    impl exports::examples::shipping::api::Guest for Capsule {
        fn quote(items: u32, express: bool) -> Result<u32, String> {
            super::quote(items, express)
        }
    }
    export!(Capsule);
}
// lsf-example-end: capsule

#[cfg(test)]
mod tests {
    #[test]
    fn quotes_standard_and_express_shipping_and_rejects_invalid_quantities() {
        assert_eq!(super::quote(2, false), Ok(650));
        assert_eq!(super::quote(2, true), Ok(1350));
        assert_eq!(super::quote(100, true), Ok(8700));
        assert!(super::quote(0, false).is_err());
        assert!(super::quote(u32::MAX, false).is_err());
    }
}
