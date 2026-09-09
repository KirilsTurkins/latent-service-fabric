use std::collections::BTreeMap;

use super::lookup_function;

#[test]
fn borrowed_lookup_preserves_exact_contract_and_function_identity_order() {
    let registered: BTreeMap<_, _> = [
        (("b".to_owned(), "identify".to_owned()), 22),
        (("a".to_owned(), "identify".to_owned()), 11),
        (("a".to_owned(), "function-id".to_owned()), 7),
        (("a/b".to_owned(), "c".to_owned()), 33),
        (("a".to_owned(), "b/c".to_owned()), 44),
    ]
    .into();
    let ordered = registered.into_iter().collect::<Vec<_>>();
    for ((contract, function), expected) in &ordered {
        let actual = lookup_function(&ordered, contract, function).unwrap();
        assert!(std::ptr::eq(actual, expected));
    }
    assert_eq!(lookup_function(&ordered, "a", "identify"), Some(&11));
    assert_eq!(lookup_function(&ordered, "b", "identify"), Some(&22));
    assert_eq!(lookup_function(&ordered, "a", "function-id"), Some(&7));
    assert_eq!(lookup_function(&ordered, "a", "exported-name"), None);
    for (contract, function) in [
        ("", "identify"),
        ("a", ""),
        ("c", "identify"),
        ("a", "identifz"),
    ] {
        assert_eq!(lookup_function(&ordered, contract, function), None);
    }
    assert_eq!(lookup_function::<u8>(&[], "a", "identify"), None);
}
