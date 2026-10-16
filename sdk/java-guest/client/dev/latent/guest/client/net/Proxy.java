package dev.latent.guest.client.net;

/** Only the standard direct marker is supported; no proxy or DNS authority. */
public class Proxy {
    public enum Type { DIRECT, HTTP, SOCKS }

    public static final Proxy NO_PROXY = new Proxy();

    private Proxy() { }

    public Proxy(Type type, SocketAddress address) {
        if (type == null || address == null || type == Type.DIRECT) {
            throw new IllegalArgumentException("invalid proxy type or address");
        }
        throw new UnsupportedOperationException("java-proxy-transport-not-qualified");
    }

    public Type type() { return Type.DIRECT; }
    public SocketAddress address() { return null; }
    @Override public String toString() { return "DIRECT"; }
}
