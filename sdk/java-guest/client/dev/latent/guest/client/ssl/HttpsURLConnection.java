package dev.latent.guest.client.ssl;

import java.net.HttpURLConnection;
import java.net.URL;
import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.SSLSocketFactory;

/** Canonical HTTPS type checks only; this profile provides no TLS connection. */
public abstract class HttpsURLConnection extends HttpURLConnection {
    protected HttpsURLConnection(URL url) {
        super(url);
        throw unsupported();
    }

    public void setHostnameVerifier(HostnameVerifier verifier) {
        if (verifier == null) throw new IllegalArgumentException("no HostnameVerifier specified");
        throw unsupported();
    }

    public void setSSLSocketFactory(SSLSocketFactory factory) {
        if (factory == null) throw new IllegalArgumentException("no SSLSocketFactory specified");
        throw unsupported();
    }

    private static UnsupportedOperationException unsupported() {
        return new UnsupportedOperationException("java-https-standard-type-not-qualified");
    }
}
