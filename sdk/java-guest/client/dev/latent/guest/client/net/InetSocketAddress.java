package dev.latent.guest.client.net;

/** Explicit boundary for a library's optional proxy-address construction. */
public final class InetSocketAddress extends SocketAddress {
    public InetSocketAddress(String hostname, int port) {
        if (hostname == null) throw new IllegalArgumentException("hostname is null");
        if (port < 0 || port > 65535) throw new IllegalArgumentException("port outside range");
        throw new UnsupportedOperationException("java-proxy-address-resolution-not-qualified");
    }
}
