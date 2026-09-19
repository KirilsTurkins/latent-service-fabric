package dev.latent.sdk.transport;

import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URI;

public final class ClientConfig {
    final InetSocketAddress address;
    final String tenant;
    final String authorization;
    final int maximumCalls;
    final int requestBytes;
    final int responseBytes;
    final int timeoutMillis;
    final int connectMillis;
    final int shutdownMillis;

    public ClientConfig(String endpoint, String tenant, String bearerToken, int maximumCalls,
            int requestBytes, int responseBytes, int timeoutMillis, int connectMillis, int shutdownMillis) {
        try {
            URI uri = URI.create(endpoint);
            if (!"http".equals(uri.getScheme()) || uri.getUserInfo() != null || uri.getQuery() != null
                    || uri.getFragment() != null || !uri.getPath().isEmpty() || uri.getPort() < 1
                    || uri.getPort() > 65535) throw new IllegalArgumentException();
            String host = uri.getHost();
            byte[] bytes;
            if ("[::1]".equals(host) || "::1".equals(host)) {
                bytes = new byte[16];
                bytes[15] = 1;
            } else {
                if (host == null || !host.matches("127\\.(0|[1-9][0-9]{0,2})\\.(0|[1-9][0-9]{0,2})\\.(0|[1-9][0-9]{0,2})")) {
                    throw new IllegalArgumentException();
                }
                String[] parts = host.split("\\.");
                bytes = new byte[4];
                for (int index = 0; index < parts.length; index++) {
                    int value = Integer.parseInt(parts[index]);
                    if (value > 255) throw new IllegalArgumentException();
                    bytes[index] = (byte) value;
                }
            }
            address = new InetSocketAddress(InetAddress.getByAddress(bytes), uri.getPort());
            if (tenant == null || tenant.length() > 128 || !tenant.matches("[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")) {
                throw new IllegalArgumentException();
            }
            if (bearerToken == null || bearerToken.isEmpty() || bearerToken.length() > 8192
                    || !bearerToken.chars().allMatch(value -> value >= 33 && value <= 126)) {
                throw new IllegalArgumentException();
            }
            if (maximumCalls < 1 || maximumCalls > 128 || requestBytes < 1 || requestBytes > 4194304
                    || responseBytes < 1 || responseBytes > 4194304 || timeoutMillis < 1 || timeoutMillis > 30000
                    || connectMillis < 1 || connectMillis > timeoutMillis || shutdownMillis < 1 || shutdownMillis > 10000) {
                throw new IllegalArgumentException();
            }
        } catch (Exception failure) {
            throw new IllegalArgumentException("invalid bounded loopback client configuration");
        }
        this.tenant = tenant;
        authorization = "Bearer " + bearerToken;
        this.maximumCalls = maximumCalls;
        this.requestBytes = requestBytes;
        this.responseBytes = responseBytes;
        this.timeoutMillis = timeoutMillis;
        this.connectMillis = connectMillis;
        this.shutdownMillis = shutdownMillis;
    }

    public static ClientConfig loopback(String endpoint, String tenant, String bearerToken) {
        return new ClientConfig(endpoint, tenant, bearerToken, 32, 1048576, 1048576, 30000, 5000, 5000);
    }

    @Override
    public String toString() {
        return "ClientConfig[numeric-loopback, credential=REDACTED, maximumCalls=" + maximumCalls + "]";
    }
}
