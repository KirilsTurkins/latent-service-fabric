using System.Text;
using Lsf.Guest;
using Raw = ServiceWorld.wit.Imports.latent.events.IPublisherImports;
namespace ServiceWorld.wit.Exports.tests.natsEvents;
public class ApiExportsImpl : IApiExports
{
    public static ulong Run(uint which, string text, ulong handle)
    {
        var result = Events.Publish(new Raw.Event(text, null, Encoding.UTF8.GetBytes("payload"), "text/plain", [], "guest-sdk-" + handle));
        if (!result.IsOk) return result.AsErr.Tag switch {
            Raw.EventError.Tags.PermissionDenied => 10,
            Raw.EventError.Tags.Uncertain => 11,
            _ => throw new System.InvalidOperationException("unexpected event result") };
        return result.AsOk.sequence;
    }
}
