package dev.latent.guest.client;

import java.net.HttpURLConnection;
import java.net.URLConnection;
import java.net.URL;
import java.net.Proxy;
import java.io.IOException;

/** Concrete standard members missing from the pinned maintained class library. */
public final class StandardMembers {
    private StandardMembers() { }
    public static URLConnection openConnection(URL url, Proxy proxy) throws IOException {
        if (proxy == null) throw new IllegalArgumentException("proxy is null");
        if (proxy != Proxy.NO_PROXY) {
            throw new UnsupportedOperationException("java-proxy-transport-not-qualified");
        }
        return url.openConnection();
    }
    public static long contentLength(URLConnection connection) {
        return headerLong(connection, "Content-Length", -1L);
    }
    public static long headerLong(URLConnection connection, String name, long defaultValue) {
        String value = connection.getHeaderField(name);
        if (value == null) return defaultValue;
        try { return Long.parseLong(value); }
        catch (NumberFormatException malformed) { return defaultValue; }
    }
    public static void fixedLength(HttpURLConnection connection, long length) {
        if (length < 0) throw new IllegalArgumentException("negative request length");
        if (length > Integer.MAX_VALUE) {
            throw new UnsupportedOperationException("fixed request length exceeds finite HTTP profile");
        }
        connection.setFixedLengthStreamingMode((int) length);
    }
}
