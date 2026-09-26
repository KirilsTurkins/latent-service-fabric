using Lsf.Guest;
using Raw = ServiceWorld.wit.Imports.latent.service.IInvokeImports;
namespace ServiceWorld.wit.Exports.tests.caller;
public class ApiExportsImpl : IApiExports
{
    public static ulong Run(uint which, string text, ulong handle)
    {
        var function = which == 1 ? "fail" : which == 2 ? "spin" : "answer";
        var result = Service.Call(new Raw.Target(null, "callee", "tests:local/api@1.0.0", function, "callee"),
            [91, 93], "application/vnd.latent.wit-values.v1+json", new Raw.CallOptions(null, 0, null, []));
        return result.Tag switch {
            Raw.InvocationOutcome.Tags.Success => Success(result.AsSuccess),
            Raw.InvocationOutcome.Tags.DeclaredError => result.AsDeclaredError.payload.Length > 0 ? 10UL : throw new System.InvalidOperationException("empty declared error"),
            Raw.InvocationOutcome.Tags.PlatformFailure => result.AsPlatformFailure.code switch {
                Raw.PlatformErrorCode.PERMISSION_DENIED => 11,
                Raw.PlatformErrorCode.CANCELLED => 12,
                Raw.PlatformErrorCode.DEADLINE_EXCEEDED => 13,
                Raw.PlatformErrorCode.RESOURCE_EXHAUSTED => 14,
                _ => throw new System.InvalidOperationException("unexpected service failure") },
            _ => throw new System.InvalidOperationException("unknown service outcome") };
    }
    private static ulong Success(Raw.InvocationResult result) =>
        System.Text.Encoding.UTF8.GetString(result.payload) == "[42]" ? 42UL : throw new System.InvalidOperationException("invalid service payload");
}
