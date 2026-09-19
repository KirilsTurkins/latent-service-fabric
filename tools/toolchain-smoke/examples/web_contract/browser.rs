use super::{Header, Profile, Response};

fn header(name: &str, value: &[u8]) -> Header {
    Header {
        name: name.into(),
        value: value.to_vec(),
    }
}

pub(super) fn response(path: &str) -> Option<Response> {
    let mut response = Response {
        profile: Profile::BufferedV1,
        status: 200,
        headers: vec![],
        media_type: Some("text/plain".into()),
        representation_length: None,
        body_base64: String::new(),
    };
    match path {
        "/browser-crlf" => response
            .headers
            .push(header("x-reflected", b"safe\r\nx-injected: true")),
        "/browser-header-bound" => response
            .headers
            .push(header("x-reflected", &vec![b'x'; 16_385])),
        "/browser-csp" => response
            .headers
            .push(header("content-security-policy", b"default-src *")),
        "/browser-cors" => response
            .headers
            .push(header("access-control-allow-origin", b"*")),
        "/browser-compressed" => response.headers.push(header("content-encoding", b"gzip")),
        "/browser-cookie" => response.headers.push(header(
            "set-cookie",
            b"__Host-session=fixture; Secure; HttpOnly; SameSite=Strict; Path=/",
        )),
        "/browser-redirect" => {
            response.status = 302;
            response
                .headers
                .push(header("location", b"https://attacker.invalid/"));
        }
        "/browser-relative" => {
            response.status = 303;
            response
                .headers
                .push(header("location", b"/next?from=fixture"));
        }
        "/browser-charset" => response.media_type = Some("text/html".into()),
        "/browser-utf8" => {
            response.media_type = Some("text/html; charset=utf-8".into());
            response.body_base64 = "/w==".into();
        }
        _ => return None,
    }
    Some(response)
}
