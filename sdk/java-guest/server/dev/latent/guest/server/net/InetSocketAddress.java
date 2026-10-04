package dev.latent.guest.server.net;
/** Wildcard and explicit IPv4 loopback inputs; no source DNS or bound socket. */
public final class InetSocketAddress extends SocketAddress {
    private final InetAddress address;
    private final int port;
    public InetSocketAddress(int port) { this(InetAddress.getByAddress(new byte[4]), port); }
    public InetSocketAddress(InetAddress address, int port) {
        if (port <= 0 || port > 65535) throw new IllegalArgumentException("positive logical port required");
        InetAddress selected = address == null ? InetAddress.getByAddress(new byte[4]) : address;
        if (!selected.isAnyLocalAddress() && !selected.isLoopbackAddress()) {
            throw new UnsupportedOperationException("non-loopback source address is outside simple server profile");
        }
        this.address = selected;
        this.port = port;
    }
    public InetSocketAddress(String host, int port) { this(literal(host), port); }
    private static InetAddress literal(String host) {
        if ("0.0.0.0".equals(host)) return InetAddress.getByAddress(new byte[4]);
        if ("127.0.0.1".equals(host)) return InetAddress.getLoopbackAddress();
        throw new UnsupportedOperationException("source DNS or arbitrary address requires another profile");
    }
    public int getPort() { return port; }
    public InetAddress getAddress() { return address; }
    public boolean isUnresolved() { return false; }
    public String getHostString() { return address.getHostAddress(); }
    public String getHostName() { throw new UnsupportedOperationException("DNS introspection is unsupported"); }
    public static InetSocketAddress createUnresolved(String host, int port) {
        throw new UnsupportedOperationException("unresolved addresses have no simple server profile mapping");
    }
}
