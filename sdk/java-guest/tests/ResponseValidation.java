package dev.latent.guest;

import dev.latent.guest.BufferedWebResponseValidator.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/** JVM authoring contract tests; signed component/browser qualification is separate. */
public final class ResponseValidation {
    private ResponseValidation() { }
    private static byte[] bytes(String value) { return value.getBytes(StandardCharsets.UTF_8); }
    private static Header header(String name, String value) { return new Header(name, bytes(value)); }
    private static Reason inspect(int status, Scheme scheme, Header... headers) {
        return BufferedWebResponseValidator.validate(Method.GET, scheme, status, List.of(headers), "text/plain", new byte[0], null);
    }
    private static void expect(Reason actual, Reason expected) {
        if (actual != expected) throw new AssertionError("response-validator-reason");
    }
    public static void run(String[] arguments) {
        if (arguments.length > 1) throw new AssertionError("response-validator-vector-arguments");
        if (arguments.length == 1) {
            try {
                List<String> lines = Files.readAllLines(Path.of(arguments[0]), StandardCharsets.UTF_8);
                if (lines.size() < 100 || lines.size() > 256) throw new AssertionError("response-validator-vector-bound");
                for (String line : lines) {
                    String[] row = line.split("\t", -1);
                    if (row.length != 2) throw new AssertionError("response-validator-contract-parity");
                    if (row[0].startsWith("limit:")) {
                        int actual = switch (row[0].substring(6)) {
                            case "fields" -> BufferedWebResponseValidator.MAX_HEADERS;
                            case "aggregateNameValueBytes" -> BufferedWebResponseValidator.MAX_HEADER_BYTES;
                            case "nameBytes" -> BufferedWebResponseValidator.MAX_HEADER_NAME_BYTES;
                            case "valueBytes" -> BufferedWebResponseValidator.MAX_HEADER_VALUE_BYTES;
                            case "responseBodyBytes" -> BufferedWebResponseValidator.MAX_BODY_BYTES;
                            case "mediaTypeBytes" -> BufferedWebResponseValidator.MAX_MEDIA_TYPE_BYTES;
                            case "locationBytes" -> BufferedWebResponseValidator.MAX_LOCATION_BYTES;
                            case "cookies" -> BufferedWebResponseValidator.MAX_COOKIES;
                            case "cookieAggregateValueBytes" -> BufferedWebResponseValidator.MAX_COOKIE_BYTES;
                            case "cookieNameBytes" -> BufferedWebResponseValidator.MAX_COOKIE_NAME_BYTES;
                            case "cookieValueBytes" -> BufferedWebResponseValidator.MAX_COOKIE_VALUE_BYTES;
                            default -> throw new AssertionError("response-validator-contract-limit");
                        };
                        if (!Integer.toString(actual).equals(row[1])) throw new AssertionError("response-validator-contract-limit");
                    } else if (!BufferedWebResponseValidator.ownership(row[0]).name().equals(row[1])) throw new AssertionError("response-validator-contract-parity");
                }
            } catch (java.io.IOException error) { throw new AssertionError("response-validator-vectors-unavailable"); }
        }
        expect(inspect(200, Scheme.HTTP, header("x-app-result", "ok")), Reason.NONE);
        if (BufferedWebResponseValidator.ownership("\u212Aeep-alive") != BufferedWebResponseValidator.Ownership.GuestAllowed)
            throw new AssertionError("response-validator-ascii-case");
        expect(inspect(200, Scheme.HTTP, header("\u212Aeep-alive", "ok")), Reason.HEADER_GRAMMAR);
        expect(inspect(200, Scheme.HTTPS, header("cache-control", "public, max-age=60"), header("age", "123")), Reason.NONE);
        expect(inspect(200, Scheme.HTTPS, header("cache-control", "public"), header("cache-control", "private")), Reason.NONE);
        expect(inspect(200, Scheme.HTTPS, header("x-app-result", "a"), header("x-app-result", "b")), Reason.NONE);
        for (String name : List.of("Referrer-Policy", "CONTENT-SECURITY-POLICY", "content-length", "content-type", "ACCESS-CONTROL-ALLOW-ORIGIN", "x-lsf-result", "link")) expect(inspect(200, Scheme.HTTPS, header(name, "synthetic-token")), Reason.HOST_RESERVED);
        for (String name : List.of("authorization", "proxy-authorization", "X-Authenticated-Subject")) expect(inspect(200, Scheme.HTTPS, header(name, "synthetic-token")), Reason.FORBIDDEN_IDENTITY);
        for (String name : List.of("connection", "TRANSFER-ENCODING", "trailer")) expect(inspect(200, Scheme.HTTPS, header(name, "synthetic-token")), Reason.FORBIDDEN_HOP_BY_HOP);
        for (String value : List.of("a\r\nx-injected: synthetic-token", "a\nb", "a\tb", " value", "value ", "a\u007fb")) expect(inspect(200, Scheme.HTTPS, header("x-output", value)), Reason.HEADER_GRAMMAR);
        expect(inspect(200, Scheme.HTTPS, header("X-Output", "ok")), Reason.HEADER_GRAMMAR);
        expect(inspect(200, Scheme.HTTPS, header("", "ok")), Reason.HEADER_GRAMMAR);
        expect(inspect(200, Scheme.HTTPS, header("x".repeat(65), "ok")), Reason.HEADER_BUDGET);
        expect(inspect(200, Scheme.HTTPS, header("x-output", "x".repeat(4097))), Reason.HEADER_BUDGET);
        ArrayList<Header> many = new ArrayList<>();
        for (int i = 0; i < 65; i++) many.add(header("x-output", ""));
        expect(BufferedWebResponseValidator.validate(Method.GET, Scheme.HTTP, 200, many, null, new byte[0], null), Reason.HEADER_BUDGET);
        many.clear(); for (int i = 0; i < 4; i++) many.add(header("x-output", "x".repeat(4096)));
        expect(BufferedWebResponseValidator.validate(Method.GET, Scheme.HTTP, 200, many, null, new byte[0], null), Reason.HEADER_BUDGET);
        expect(inspect(199, Scheme.HTTP), Reason.INVALID_STATUS);
        expect(inspect(600, Scheme.HTTP), Reason.INVALID_STATUS);
        expect(inspect(200, Scheme.HTTP, header("content-encoding", "IDENTITY")), Reason.NONE);
        expect(inspect(200, Scheme.HTTP, header("content-encoding", "gzip")), Reason.CONTENT_ENCODING);
        expect(inspect(200, Scheme.HTTP, header("content-encoding", "identity"), header("content-encoding", "identity")), Reason.CONTENT_ENCODING);
        for (String path : List.of("/next?view=public", "/", "/next?encoded=%2F", "/%C3%A9")) expect(inspect(303, Scheme.HTTPS, header("location", path)), Reason.NONE);
        for (String path : List.of("https://foreign.invalid/", "//foreign.invalid/", "/../next", "/%2e%2e/next", "/%41", "/%2F", "/%252F", "/next#fragment", "/next?token=%00", "/next?x=%2f")) expect(inspect(303, Scheme.HTTPS, header("location", path)), Reason.LOCATION);
        expect(inspect(303, Scheme.HTTPS), Reason.LOCATION);
        expect(inspect(200, Scheme.HTTPS, header("location", "/next")), Reason.LOCATION);
        expect(inspect(201, Scheme.HTTPS, header("location", "/next")), Reason.NONE);
        expect(inspect(303, Scheme.HTTPS, header("location", "/next"), header("location", "/other")), Reason.LOCATION);
        String cookie = "__Host-session=value; Secure; HttpOnly; SameSite=Strict; Path=/";
        expect(inspect(200, Scheme.HTTPS, header("set-cookie", cookie)), Reason.NONE);
        expect(inspect(200, Scheme.HTTP, header("set-cookie", cookie)), Reason.COOKIE_POLICY);
        expect(inspect(200, Scheme.HTTPS, header("set-cookie", cookie + "; Max-Age=0")), Reason.NONE);
        expect(inspect(200, Scheme.HTTPS, header("set-cookie", cookie), header("set-cookie", cookie)), Reason.COOKIE_POLICY);
        for (String value : List.of("session=value", cookie + "; Domain=foreign.invalid", cookie + "; Expires=now", cookie + "; Max-Age=1", cookie + "; Secure", cookie.replace("SameSite=Strict", "SameSite=None"), cookie.replace("HttpOnly; ", ""))) expect(inspect(200, Scheme.HTTPS, header("set-cookie", value)), Reason.COOKIE_POLICY);
        for (int status : List.of(204, 205, 304)) expect(BufferedWebResponseValidator.validate(Method.GET, Scheme.HTTP, status, List.of(), null, bytes("body"), null), Reason.BODY_STATUS);
        expect(BufferedWebResponseValidator.validate(Method.HEAD, Scheme.HTTP, 200, List.of(), null, bytes("body"), null), Reason.BODY_STATUS);
        expect(BufferedWebResponseValidator.validate(Method.HEAD, Scheme.HTTP, 200, List.of(), null, new byte[0], new Unsigned64(-1)), Reason.NONE);
        expect(BufferedWebResponseValidator.validate(Method.GET, Scheme.HTTP, 304, List.of(), null, new byte[0], Unsigned64.ZERO), Reason.NONE);
        expect(BufferedWebResponseValidator.validate(Method.GET, Scheme.HTTP, 200, List.of(), null, new byte[0], Unsigned64.ZERO), Reason.BODY_STATUS);
        expect(BufferedWebResponseValidator.validate(Method.GET, Scheme.HTTP, 200, List.of(), null, new byte[262145], null), Reason.BODY_BUDGET);
        for (String media : List.of("text/html", "text/html;charset=utf-8", "text/html; charset=ascii")) expect(BufferedWebResponseValidator.validate(Method.GET, Scheme.HTTP, 200, List.of(), media, bytes("hello"), null), Reason.HTML_ENCODING);
        expect(BufferedWebResponseValidator.validate(Method.GET, Scheme.HTTP, 200, List.of(), "TEXT/HTML; CHARSET=UTF-8", bytes("snowman \u2603"), null), Reason.NONE);
        for (byte[] body : List.of(new byte[]{(byte) 255}, new byte[]{(byte) 0xc0, (byte) 0x80}, new byte[]{(byte) 0xed, (byte) 0xa0, (byte) 0x80}, new byte[]{(byte) 0xf4, (byte) 0x90, (byte) 0x80, (byte) 0x80})) expect(BufferedWebResponseValidator.validate(Method.GET, Scheme.HTTP, 200, List.of(), "text/html; charset=utf-8", body, null), Reason.HTML_ENCODING);
        for (String media : List.of("text/plain, application/json", "text/plain; charset=utf-8; CHARSET=utf-8", "text/plain; x=\"a,b\"", "text/plain; x=\"a\\b\"")) expect(BufferedWebResponseValidator.validate(Method.GET, Scheme.HTTP, 200, List.of(), media, new byte[0], null), Reason.MEDIA_TYPE);
        try {
            BufferedWebResponseValidator.requireValid(Method.GET, Scheme.HTTP, 200, List.of(header("referrer-policy", "synthetic-private-token")), null, new byte[0], null);
            throw new AssertionError("response-validator-accepted-reserved");
        } catch (IllegalArgumentException failure) {
            if (!failure.getMessage().equals("buffered-web-response-HOST_RESERVED") || failure.getMessage().contains("synthetic")) throw new AssertionError("response-validator-disclosure");
        }
        System.out.println("Java buffered response validation passed; runtime remains authoritative");
    }
}
