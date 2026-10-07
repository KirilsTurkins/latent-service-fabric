package dev.latent.guest;

import java.util.List;

/** Pure early inspection of buffered-v1/same-origin-v1 output. No IO or authority. */
public final class BufferedWebResponseValidator {
    private BufferedWebResponseValidator() { }
    public static final String PROFILE = "latent.browser.response-ownership.v1";
    public static final int MAX_HEADERS = 64, MAX_HEADER_BYTES = 16384, MAX_HEADER_NAME_BYTES = 64,
        MAX_HEADER_VALUE_BYTES = 4096, MAX_BODY_BYTES = 262144, MAX_MEDIA_TYPE_BYTES = 256,
        MAX_LOCATION_BYTES = 8192, MAX_COOKIES = 16, MAX_COOKIE_BYTES = 4096,
        MAX_COOKIE_NAME_BYTES = 64, MAX_COOKIE_VALUE_BYTES = 1024;
    public enum Method { GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS }
    public enum Scheme { HTTP, HTTPS }
    public record Header(String name, byte[] value) { }
    public enum Reason {
        NONE, INVALID_SHAPE, HEADER_BUDGET, BODY_BUDGET, HEADER_GRAMMAR, HOST_RESERVED,
        FORBIDDEN_IDENTITY, FORBIDDEN_HOP_BY_HOP, INVALID_STATUS, BODY_STATUS,
        MEDIA_TYPE, HTML_ENCODING, LOCATION, CONTENT_ENCODING, COOKIE_POLICY
    }
    public enum Ownership {
        HostSecurity, HostTransport, ForbiddenHopByHop, ForbiddenIdentity,
        ForbiddenPlatform, ForbiddenBrowserPolicy, Conditional, HostCacheInput,
        CredentialSensitiveAllowed, GuestAllowed
    }
    private static final String[] SECURITY = {"content-security-policy", "x-content-type-options", "x-frame-options", "referrer-policy", "cross-origin-opener-policy", "cross-origin-resource-policy", "permissions-policy", "strict-transport-security"};
    private static final String[] TRANSPORT = {"host", "content-length", "content-type", "server", "date", "via", "alt-svc"};
    private static final String[] HOP = {"connection", "keep-alive", "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade"};
    private static final String[] IDENTITY = {"authorization", "proxy-authorization", "forwarded", "traceparent", "tracestate", "baggage", "x-real-ip", "remote-user", "x-remote-user", "x-original-url", "x-rewrite-url"};
    private static final String[] IDENTITY_PREFIX = {"x-forwarded-", "x-auth-request-", "x-authenticated-"};
    private static final String[] BROWSER = {"refresh", "content-location", "link", "clear-site-data", "report-to", "nel", "content-security-policy-report-only", "cross-origin-embedder-policy"};
    private static final String[] CONDITIONAL = {"location", "content-encoding", "set-cookie", "vary"};
    private static final String[] CACHE = {"cache-control", "age"};
    private static final String[] SENSITIVE = {"cookie", "www-authenticate", "proxy-authenticate", "authentication-info", "proxy-authentication-info"};
    private static boolean contains(String[] values, String name) {
        for (String value : values) if (name.length() == value.length() && prefix(name, value)) return true;
        return false;
    }
    private static boolean prefix(String name, String prefix) {
        if (name.length() < prefix.length()) return false;
        for (int i = 0; i < prefix.length(); i++) {
            char c = name.charAt(i);
            if (c >= 'A' && c <= 'Z') c += 32;
            if (c != prefix.charAt(i)) return false;
        }
        return true;
    }
    public static Ownership ownership(String name) {
        if (name == null) throw new IllegalArgumentException("buffered-web-response-INVALID_SHAPE");
        if (contains(SECURITY, name)) return Ownership.HostSecurity;
        if (contains(TRANSPORT, name)) return Ownership.HostTransport;
        if (contains(HOP, name)) return Ownership.ForbiddenHopByHop;
        if (contains(IDENTITY, name)) return Ownership.ForbiddenIdentity;
        for (String value : IDENTITY_PREFIX) if (prefix(name, value)) return Ownership.ForbiddenIdentity;
        if (prefix(name, "x-lsf-")) return Ownership.ForbiddenPlatform;
        if (contains(BROWSER, name) || prefix(name, "access-control-")) return Ownership.ForbiddenBrowserPolicy;
        if (contains(CONDITIONAL, name)) return Ownership.Conditional;
        if (contains(CACHE, name)) return Ownership.HostCacheInput;
        if (contains(SENSITIVE, name)) return Ownership.CredentialSensitiveAllowed;
        return Ownership.GuestAllowed;
    }
    public static void requireValid(Method method, Scheme scheme, int status, List<Header> headers,
                                    String mediaType, byte[] body, Unsigned64 representationLength) {
        Reason reason = validate(method, scheme, status, headers, mediaType, body, representationLength);
        if (reason != Reason.NONE) throw new IllegalArgumentException("buffered-web-response-" + reason.name());
    }
    public static Reason validate(Method method, Scheme scheme, int status, List<Header> headers,
                                  String mediaType, byte[] body, Unsigned64 representationLength) {
        if (method == null || scheme == null || headers == null || body == null) return Reason.INVALID_SHAPE;
        if (headers.size() > MAX_HEADERS) return Reason.HEADER_BUDGET;
        if (body.length > MAX_BODY_BYTES) return Reason.BODY_BUDGET;
        if (status < 200 || status > 599) return Reason.INVALID_STATUS;
        if ((method == Method.HEAD || status == 204 || status == 205 || status == 304) && body.length != 0
            || representationLength != null && (method != Method.HEAD && status != 304 || status == 204 || status == 205)) return Reason.BODY_STATUS;
        int headerBytes = 0, cookieBytes = 0, cookieCount = 0;
        String[] cookieNames = new String[MAX_COOKIES];
        boolean location = false, encoding = false;
        for (Header header : headers) {
            if (header == null || header.name() == null || header.value() == null) return Reason.INVALID_SHAPE;
            String name = header.name(); byte[] value = header.value();
            if (name.length() > MAX_HEADER_NAME_BYTES || value.length > MAX_HEADER_VALUE_BYTES) return Reason.HEADER_BUDGET;
            headerBytes += name.length() + value.length;
            if (headerBytes > MAX_HEADER_BYTES) return Reason.HEADER_BUDGET;
            Ownership owner = ownership(name);
            if (owner == Ownership.HostSecurity || owner == Ownership.HostTransport || owner == Ownership.ForbiddenPlatform || owner == Ownership.ForbiddenBrowserPolicy) return Reason.HOST_RESERVED;
            if (owner == Ownership.ForbiddenIdentity) return Reason.FORBIDDEN_IDENTITY;
            if (owner == Ownership.ForbiddenHopByHop) return Reason.FORBIDDEN_HOP_BY_HOP;
            if (name.isEmpty()) return Reason.HEADER_GRAMMAR;
            for (int i = 0; i < name.length(); i++) if (!token(name.charAt(i)) || name.charAt(i) >= 'A' && name.charAt(i) <= 'Z') return Reason.HEADER_GRAMMAR;
            for (byte item : value) if ((item & 255) < 32 || (item & 255) == 127) return Reason.HEADER_GRAMMAR;
            if (value.length > 0 && (value[0] == 32 || value[value.length - 1] == 32)) return Reason.HEADER_GRAMMAR;
            if (name.equals("content-encoding")) {
                if (encoding || !asciiEquals(value, "identity", true)) return Reason.CONTENT_ENCODING;
                encoding = true;
            } else if (name.equals("location")) {
                if (location || !safeLocation(value)) return Reason.LOCATION;
                location = true;
            } else if (name.equals("set-cookie")) {
                cookieBytes += value.length;
                if (scheme != Scheme.HTTPS || cookieBytes > MAX_COOKIE_BYTES || cookieCount == MAX_COOKIES) return Reason.COOKIE_POLICY;
                String cookieName = cookie(value);
                if (cookieName == null) return Reason.COOKIE_POLICY;
                for (int i = 0; i < cookieCount; i++) if (cookieNames[i].equals(cookieName)) return Reason.COOKIE_POLICY;
                cookieNames[cookieCount++] = cookieName;
            }
        }
        boolean redirect = status == 301 || status == 302 || status == 303 || status == 307 || status == 308;
        if (redirect != location && !(status == 201 && location)) return Reason.LOCATION;
        if (mediaType != null) {
            if (!media(mediaType)) return Reason.MEDIA_TYPE;
            String kind = mediaType.split(";", 2)[0];
            if (kind.equalsIgnoreCase("text/html") && (!mediaType.equalsIgnoreCase("text/html; charset=utf-8") || !utf8(body))) return Reason.HTML_ENCODING;
        }
        return Reason.NONE;
    }
    private static boolean token(int value) {
        return value >= '0' && value <= '9' || value >= 'a' && value <= 'z' || value >= 'A' && value <= 'Z' || "!#$%&'*+-.^_`|~".indexOf(value) >= 0;
    }
    private static boolean asciiEquals(byte[] bytes, String text, boolean insensitive) {
        if (bytes.length != text.length()) return false;
        for (int i = 0; i < bytes.length; i++) {
            int value = bytes[i] & 255;
            if (insensitive && value >= 'A' && value <= 'Z') value += 32;
            if (value != text.charAt(i)) return false;
        }
        return true;
    }
    private static String ascii(byte[] bytes) {
        char[] result = new char[bytes.length];
        for (int i = 0; i < bytes.length; i++) { if ((bytes[i] & 255) > 127) return null; result[i] = (char) bytes[i]; }
        return new String(result);
    }
    private static String cookie(byte[] bytes) {
        String value = ascii(bytes); if (value == null) return null;
        String[] fields = value.split(";", -1);
        int equal = fields[0].indexOf('='); if (equal < 1 || equal > MAX_COOKIE_NAME_BYTES) return null;
        String name = fields[0].substring(0, equal);
        if (!name.startsWith("__Host-") || name.length() == 7 || fields[0].length() - equal - 1 > MAX_COOKIE_VALUE_BYTES) return null;
        for (int i = 0; i < name.length(); i++) if (!token(name.charAt(i))) return null;
        for (int i = equal + 1; i < fields[0].length(); i++) {
            int c = fields[0].charAt(i);
            if (!(c == 0x21 || c >= 0x23 && c <= 0x2b || c >= 0x2d && c <= 0x3a || c >= 0x3c && c <= 0x5b || c >= 0x5d && c <= 0x7e)) return null;
        }
        int flags = 0;
        for (int i = 1; i < fields.length; i++) {
            String field = fields[i].startsWith(" ") ? fields[i].substring(1) : fields[i];
            int bit = switch (field) { case "Secure" -> 1; case "HttpOnly" -> 2; case "SameSite=Strict" -> 4; case "Path=/" -> 8; case "Max-Age=0" -> 16; default -> 0; };
            if (bit == 0 || (flags & bit) != 0) return null;
            flags |= bit;
        }
        return (flags & 15) == 15 ? name : null;
    }
    private static boolean media(String value) {
        if (value.length() > MAX_MEDIA_TYPE_BYTES) return false;
        for (int i = 0; i < value.length(); i++) if (value.charAt(i) > 127) return false;
        String[] fields = value.split(";", -1), kind = fields[0].split("/", -1);
        if (kind.length != 2 || !tokens(kind[0]) || !tokens(kind[1]) || fields.length > 17) return false;
        String[] names = new String[16];
        for (int i = 1; i < fields.length; i++) {
            String field = fields[i]; int leading = 0;
            while (leading < field.length() && field.charAt(leading) == ' ') leading++;
            field = field.substring(leading);
            int equal = field.indexOf('='); if (equal < 1) return false;
            String name = field.substring(0, equal), parameter = field.substring(equal + 1);
            if (!tokens(name)) return false;
            for (int j = 0; j < i - 1; j++) if (name.equalsIgnoreCase(names[j])) return false;
            names[i - 1] = name;
            if (parameter.length() >= 2 && parameter.startsWith("\"") && parameter.endsWith("\"")) {
                for (int j = 1; j < parameter.length() - 1; j++) { char c = parameter.charAt(j); if (c < 32 || c >= 127 || c == '"' || c == '\\' || c == ',') return false; }
            } else if (!tokens(parameter)) return false;
        }
        return true;
    }
    private static boolean tokens(String value) {
        if (value.isEmpty()) return false;
        for (int i = 0; i < value.length(); i++) if (!token(value.charAt(i))) return false;
        return true;
    }
    private static boolean unreserved(int c) {
        return c >= '0' && c <= '9' || c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || "-._~".indexOf(c) >= 0;
    }
    private static boolean safeLocation(byte[] value) {
        if (value.length == 0 || value.length > MAX_LOCATION_BYTES) return false;
        String location = ascii(value); if (location == null || !location.startsWith("/")) return false;
        int query = location.indexOf('?'); String path = query < 0 ? location : location.substring(0, query);
        if (path.contains("//")) return false;
        for (String part : path.split("/", -1)) if (part.equals(".") || part.equals("..")) return false;
        for (int i = 0; i < location.length(); i++) {
            int c = location.charAt(i); boolean inQuery = query >= 0 && i > query;
            if (i == query) continue;
            if (c == '%') {
                if (i + 2 >= location.length()) return false;
                char a = location.charAt(i + 1), b = location.charAt(i + 2);
                int hi = "0123456789ABCDEF".indexOf(a), lo = "0123456789ABCDEF".indexOf(b);
                if (hi < 0 || lo < 0) return false;
                int decoded = hi * 16 + lo;
                if (decoded < 32 || decoded == 127 || unreserved(decoded) || !inQuery && (decoded == '/' || decoded == '\\' || decoded == '%')) return false;
                i += 2;
            } else if (!(unreserved(c) || "!$&'()*+,;=:@/".indexOf(c) >= 0 || inQuery && c == '?')) return false;
        }
        return true;
    }
    private static boolean utf8(byte[] value) {
        for (int i = 0; i < value.length; i++) {
            int first = value[i] & 255; if (first < 128) continue;
            int count = first >= 0xc2 && first <= 0xdf ? 1 : first >= 0xe0 && first <= 0xef ? 2 : first >= 0xf0 && first <= 0xf4 ? 3 : -1;
            if (count < 0 || i + count >= value.length) return false;
            int second = value[i + 1] & 255;
            if (first == 0xe0 && second < 0xa0 || first == 0xed && second >= 0xa0 || first == 0xf0 && second < 0x90 || first == 0xf4 && second >= 0x90) return false;
            for (int j = 1; j <= count; j++) if ((value[i + j] & 0xc0) != 0x80) return false;
            i += count;
        }
        return true;
    }
}
