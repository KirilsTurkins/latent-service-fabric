using Latent.Sdk;
namespace Latent.Sdk.SemanticTests;
internal static class PublicationIdentityTests
{
    private static void Check(bool value) { if (!value) throw new InvalidOperationException("publication model contract"); }
    public static void Run()
    {
        var component = "sha256:" + new string('a', 64);
        var rows = Enumerable.Range(0, 4).Select(i => new PublicationIdentity(
            new PublicationRef("publication:sha256:" + i.ToString("x").PadLeft(64, '0'), i < 2 ? "a" : "b"),
            component, "sha256:" + (i % 2).ToString("x").PadLeft(64, '0'))).ToArray();
        Check(rows[0].ComponentDigest == rows[3].ComponentDigest && rows[0].PackageDigest == rows[2].PackageDigest);
        Check(rows[0].PackageDigest != rows[1].PackageDigest && rows[0].Publication != rows[2].Publication);
        var invalid = new PublicationRef("", "b");
        Check(invalid.Id == "" && invalid.Tenant == "b");
        var used = new BudgetConsumption(ulong.MaxValue, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
        var unresolved = new InvocationReceipt("known", "revision", component, ulong.MaxValue, used);
        var current = unresolved with { PublicationId = rows[1].Publication.Id };
        Check(unresolved.PublicationId is null && current.PublicationId == rows[1].Publication.Id);
        Check(current.ReleaseDigest == component && current.RouteGeneration == ulong.MaxValue && current.Consumption.CpuFuel == ulong.MaxValue);
    }
}
