package dev.latent.guest.server.net;
/** Finite literal logical addresses. DNS and reachability are unsupported. */
public final class InetAddress {
    private final byte[] bytes;
    private InetAddress(byte[] bytes) { this.bytes = bytes.clone(); }
    public static InetAddress getLoopbackAddress() { return new InetAddress(new byte[] {127, 0, 0, 1}); }
    public static InetAddress getByAddress(byte[] bytes) {
        if (bytes == null || bytes.length != 4) throw new IllegalArgumentException("logical IPv4 address required");
        return new InetAddress(bytes);
    }
    public static InetAddress getByName(String name) {
        throw new UnsupportedOperationException("DNS requires a qualified network runtime profile");
    }
    public byte[] getAddress() { return bytes.clone(); }
    public String getHostAddress() {
        return (bytes[0] & 255) + "." + (bytes[1] & 255) + "." + (bytes[2] & 255) + "." + (bytes[3] & 255);
    }
    public boolean isAnyLocalAddress() { return bytes[0] == 0 && bytes[1] == 0 && bytes[2] == 0 && bytes[3] == 0; }
    public boolean isLoopbackAddress() { return (bytes[0] & 255) == 127; }
}
