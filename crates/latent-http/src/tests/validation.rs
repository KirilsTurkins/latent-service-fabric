use super::*;
#[test]
fn special_addresses_require_exact_opt_in_even_with_broad_networks() {
    let mut policy = HttpAddressPolicy {
        networks: vec!["0.0.0.0/0".parse().unwrap(), "::/0".parse().unwrap()],
        special_addresses: Vec::new(),
    };
    for value in [
        "0.0.0.0",
        "10.1.1.1",
        "100.64.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "172.16.1.1",
        "192.168.1.1",
        "168.63.129.16",
        "224.0.0.1",
        "::",
        "::1",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "::ffff:169.254.169.254",
        "64:ff9b::a9fe:a9fe",
        "2002:a9fe:a9fe::1",
        "2001:db8::1",
    ] {
        assert!(!policy.permits(value.parse().unwrap()), "{value}");
    }
    assert!(policy.permits("8.8.8.8".parse().unwrap()));
    assert!(policy.permits("2606:4700:4700::1111".parse().unwrap()));
    policy.special_addresses.push("127.0.0.1".parse().unwrap());
    assert!(policy.permits("::ffff:127.0.0.1".parse().unwrap()));
    policy.networks = vec!["10.0.0.0/8".parse().unwrap()];
    assert!(!policy.permits("127.0.0.1".parse().unwrap()));
}
#[test]
fn url_and_header_grammar_rejects_smuggling_and_ambient_credentials() {
    let cfg = config(12345);
    for url in [
        "file:///etc/passwd",
        "ftp://localhost:12345/allowed",
        "http://u:p@localhost:12345/allowed",
        "http://localhost:12345/allowed#fragment",
        "http://localhost:12345/allowed%2fsecret",
        "http://localhost:12345/allowed\\other",
        "http://localhost:12345/allowed\r\nX: evil",
    ] {
        assert!(crate::destination::parse(url, &cfg).is_err());
    }
    let normalized =
        crate::destination::parse("http://localhost:12345/allowed/../forbidden?x=1", &cfg).unwrap();
    assert_eq!(normalized.url.path(), "/forbidden");
    for (name, value) in [
        ("Host", "evil"),
        ("Content-Length", "1"),
        ("Transfer-Encoding", "chunked"),
        ("Authorization", "token"),
        ("Cookie", "token"),
        ("Connection", "x-test"),
        ("X-Test", "bad\r\nheader"),
        ("X-Test", "bad\0value"),
        ("x-unknown", "value"),
    ] {
        let mut input = request(12345, HttpMethod::Get);
        input.headers.push(HttpHeader {
            name: name.into(),
            value: value.into(),
        });
        assert!(
            crate::headers::validate(&input, &cfg.destinations[0], cfg.limits).is_err(),
            "{name}"
        );
    }
    let mut input = request(12345, HttpMethod::Get);
    input.headers = vec![
        HttpHeader {
            name: "x-test".into(),
            value: "one".into(),
        },
        HttpHeader {
            name: "X-Test".into(),
            value: "two".into(),
        },
    ];
    assert!(crate::headers::validate(&input, &cfg.destinations[0], cfg.limits).is_err());
}
