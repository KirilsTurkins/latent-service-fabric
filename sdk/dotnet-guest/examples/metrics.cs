using Lsf.Guest;
using Raw = ServiceWorld.wit.Imports.latent.telemetry.ICustomImports;
namespace ServiceWorld.wit.Exports.tests.metrics;
public class ApiExportsImpl : IApiExports
{
    public static ulong Run(uint which, string text, ulong handle)
    {
        var result = Metrics.Emit(new Raw.Metric(text, (Raw.MetricKind)System.Math.Min(which, 3U), 2, "1", [("region", "east")]));
        if (!result.IsOk) return result.AsErr.Tag switch {
            Raw.TelemetryError.Tags.InvalidName => 10,
            Raw.TelemetryError.Tags.BudgetExhausted => 11,
            Raw.TelemetryError.Tags.Unavailable => 12,
            _ => throw new System.InvalidOperationException("unexpected metric result") };
        return result.AsOk ? 1UL : 0UL;
    }
}
