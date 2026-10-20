package dev.latent.guest.client;

import dev.latent.generated.Bindings;
import java.net.HttpURLConnection;
import java.net.URL;
import java.lang.reflect.Modifier;
import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.SSLSocketFactory;
import dev.latent.guest.client.ssl.HttpsURLConnection;

/** Native type/exception control; it does not perform or qualify TLS. */
public final class HttpsType {
    private static void require(boolean value) { if (!value) throw new AssertionError(); }
    private static final class Selected extends HttpsURLConnection {
        Selected(URL url) { super(url); }
        @Override public void connect() { throw new AssertionError("unsupported construction escaped"); }
        @Override public void disconnect() { throw new AssertionError("unsupported construction escaped"); }
        @Override public boolean usingProxy() { throw new AssertionError("unsupported construction escaped"); }
    }
    public static void main(String[] arguments) throws Exception {
        Bindings.reset();
        HttpURLConnection ordinary = new Connection(new URL("http://must-not-contact.invalid/"));
        require(!(ordinary instanceof HttpsURLConnection));
        require(!(ordinary instanceof javax.net.ssl.HttpsURLConnection));
        require(Modifier.isAbstract(HttpsURLConnection.class.getModifiers()));
        require(HttpsURLConnection.class.getSuperclass() == HttpURLConnection.class);
        require(HttpsURLConnection.class.getMethod("setHostnameVerifier", HostnameVerifier.class).getReturnType() == void.class);
        require(HttpsURLConnection.class.getMethod("setSSLSocketFactory", SSLSocketFactory.class).getReturnType() == void.class);
        for (String protocol : new String[]{"http", "https"}) {
            try { new Selected(new URL(protocol + "://must-not-contact.invalid/")); throw new AssertionError(); }
            catch (UnsupportedOperationException expected) {
                require(expected.getMessage().equals("java-https-standard-type-not-qualified"));
            }
        }
        try { new StreamHandler().openConnection(new URL("https://must-not-contact.invalid/")); throw new AssertionError(); }
        catch (java.io.IOException expected) { require(expected.getMessage().equals("java-https-standard-type-not-qualified")); }
        require(Bindings.opens == 0 && Bindings.finishes == 0);
        System.out.println("HTTPS_TYPE_MODEL_CONTROLS=5; COMPONENT_QUALIFICATION=pending; TLS_QUALIFICATION=unsupported");
    }
}
