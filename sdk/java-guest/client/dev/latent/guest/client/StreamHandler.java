package dev.latent.guest.client;

import java.io.IOException;
import java.net.URL;
import java.net.URLConnection;
import java.net.URLStreamHandler;

/** Automatically selected below the maintained URL parser, never an app factory. */
public final class StreamHandler extends URLStreamHandler {
    @Override protected URLConnection openConnection(URL url) throws IOException {
        if (!"http".equals(url.getProtocol())) {
            // The provider's TLS is not a replacement for the JDK HTTPS type,
            // certificate/pinning APIs, or an application SSL socket factory.
            throw new IOException("java-https-standard-type-not-qualified");
        }
        return new Connection(url);
    }
    @Override protected int getDefaultPort() { return 80; }
}
