package dev.latent.sdk.examples;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import dev.latent.sdk.Management;
import dev.latent.sdk.transport.ClientConfig;
import dev.latent.sdk.transport.RpcClient;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermission;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

final class ProviderInput {
    static final String MEDIA = "application/vnd.latent.wit-values.v1+json";
    private final JsonObject document;
    private final String token;

    ProviderInput(Path path) throws Exception {
        document = JsonParser.parseString(new String(read(path, 16384, false), StandardCharsets.UTF_8)).getAsJsonObject();
        require(field("schemaVersion").equals("latent.sdk.provider.workflow.input.v1") && field("language").equals("java"), "input-profile");
        byte[] bytes = read(Path.of(field("credentialFile")), 8192, true);
        for (byte value : bytes) require(value >= 33 && value <= 126, "credential-encoding");
        token = new String(bytes, StandardCharsets.US_ASCII);
        java.util.Arrays.fill(bytes, (byte) 0);
    }

    static byte[] read(Path path, int maximum, boolean secret) throws Exception {
        require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS), "input-file-type");
        if (secret && Files.getFileStore(path).supportsFileAttributeView("posix")) {
            Set<PosixFilePermission> permissions = Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS);
            require(!permissions.contains(PosixFilePermission.GROUP_READ) && !permissions.contains(PosixFilePermission.GROUP_WRITE)
                    && !permissions.contains(PosixFilePermission.OTHERS_READ) && !permissions.contains(PosixFilePermission.OTHERS_WRITE), "credential-file-permissions");
        }
        try (var channel = Files.newByteChannel(path, Set.of(StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS));
                var input = java.nio.channels.Channels.newInputStream(channel)) {
            byte[] bytes = input.readNBytes(maximum + 1);
            require(bytes.length > 0 && bytes.length <= maximum, "input-file-bound");
            return bytes;
        }
    }

    static void require(boolean condition, String reason) { if (!condition) throw new IllegalStateException(reason); }
    static String field(JsonObject object, String name) {
        var value = object.get(name);
        require(value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isString(), "input-field");
        String text = value.getAsString();
        require(!text.isEmpty() && text.length() <= 4096, "input-field-bound");
        return text;
    }
    String field(String name) { return field(document, name); }
    JsonObject target(String name) { return document.getAsJsonObject("targets").getAsJsonObject(name); }
    String target(String name, String field) { return field(target(name), field); }

    RpcClient client(String tenant, boolean denied, boolean limited) {
        return new RpcClient(new ClientConfig(field("endpoint"), tenant, denied ? "LSF-PUBLIC-WRONG-NODE-TOKEN-TEST-ONLY" : token,
                4, 262144, limited ? 64 : 131072, 3000, 2000, 3000));
    }

    Management.InvokeRequest request(String provider, String identity, String function, String tenant, boolean exhaustFuel) {
        boolean callee = provider.equals("callee");
        String text = provider.equals("http") ? field("upstreamUrl") : "";
        byte[] payload = new Gson().toJson(callee ? List.of() : List.of(0, text, "0")).getBytes(StandardCharsets.UTF_8);
        return new Management.InvokeRequest(Optional.of(identity), Optional.empty(), Optional.empty(),
                Optional.of(new Management.InvocationTarget(tenant, target(provider, "service"), target(provider, "contract"),
                        function == null ? target(provider, "function") : function, Optional.of(target(provider, "route")))),
                ByteBuffer.wrap(payload).asReadOnlyBuffer(), MEDIA, Optional.empty(), 0, Optional.empty(),
                Optional.of(new Management.ResourceBudget(exhaustFuel ? 1000 : callee ? 100000000 : 10000000000L,
                        callee ? 4194304 : 16777216, 0, callee ? 0 : 8, 0, 0, provider.equals("blob") ? 65536 : 0,
                        provider.equals("blob") ? 65536 : 0, 0, 0, Optional.of(5000L))), Map.of());
    }

    void identity(Management.InvokeResponse response, String provider, String identity) {
        require(response.activationId().equals(identity) && response.releaseDigest().equals(target(provider, "componentDigest"))
                && response.publicationId().equals(Optional.of(target(provider, "publication"))), "publication-receipt-identity");
    }

    static long guest(Management.InvokeResponse response) {
        var success = response.success().orElseThrow();
        ByteBuffer buffer = success.payload().asReadOnlyBuffer();
        require(buffer.remaining() <= 128 && success.mediaType().equals(MEDIA), "wit-response-frame");
        byte[] bytes = new byte[buffer.remaining()]; buffer.get(bytes);
        var values = JsonParser.parseString(new String(bytes, StandardCharsets.UTF_8)).getAsJsonArray();
        require(values.size() == 1 && values.get(0).isJsonPrimitive() && values.get(0).getAsJsonPrimitive().isString(), "wit-unsigned-value");
        return Management.parseU64Decimal(values.get(0).getAsString());
    }
}
