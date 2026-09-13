package dev.latent.sdk;
import java.util.Optional;

final class PublicationIdentityTest {
    private PublicationIdentityTest() { }
    private static void check(boolean value) { if (!value) throw new AssertionError("publication model contract"); }
    static void run() {
        String component = "sha256:" + "a".repeat(64);
        var rows = new Models.PublicationIdentity[4];
        for (int i = 0; i < 4; ++i) rows[i] = new Models.PublicationIdentity(
            new Models.PublicationRef("publication:sha256:" + String.format("%064x", i), i < 2 ? "a" : "b"),
            component, "sha256:" + String.format("%064x", i % 2));
        check(rows[0].componentDigest().equals(rows[3].componentDigest()));
        check(rows[0].packageDigest().equals(rows[2].packageDigest()));
        check(!rows[0].packageDigest().equals(rows[1].packageDigest()));
        check(!rows[0].publication().equals(rows[2].publication()));
        var invalid = new Models.ReleaseSelector(Optional.of(""), Optional.of(new Models.PublicationRef("", "b")));
        check(invalid.componentDigest().orElseThrow().isEmpty() && invalid.publication().orElseThrow().id().isEmpty());
        var used = new Models.BudgetConsumption(-1L, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
        var legacy = new Models.InvocationReceipt("known", "revision", component, -1L, used);
        var current = new Models.InvocationReceipt("known", "revision", component, -1L, used,
            Optional.of(rows[1].publication().id()));
        check(legacy.publicationId().isEmpty() && current.publicationId().orElseThrow().equals(rows[1].publication().id()));
        check(current.releaseDigest().equals(component) && Long.toUnsignedString(current.routeGeneration()).equals("18446744073709551615"));
        check(Long.toUnsignedString(current.consumption().cpuFuel()).equals("18446744073709551615"));
    }
}
