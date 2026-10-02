using State = ServiceWorld.wit.Imports.latent.state.IKeyValueImports;
using Intents = ServiceWorld.wit.Imports.latent.intents.IStagingImports;
namespace ServiceWorld.wit.Exports.tests.transactionContract;

// Compile-definition input using imported owners and the actual managed bridge.
public class ApiExportsImpl : IApiExports
{
    public static ulong Run(uint mode)
    {
        if (mode == 0) {
            using var view = State.AcquireQuery().AsOk;
            var identity = State.QueryInfo(view).AsOk;
            var value = State.GetQuery(view, [107]).AsOk;
            using var page = State.ScanQuery(view, [], 1, null).AsOk;
            var bounds = State.DescribePage(page).AsOk;
            var item = State.PageNext(page).AsOk;
            return (ulong)identity.version.Length + bounds.entryCount
                + (value.HasValue ? 1UL : 0UL) + (item.HasValue ? 1UL : 0UL);
        }
        using var transaction = State.AcquireCommand().AsOk;
        var command = State.Info(transaction).AsOk;
        var existing = State.Get(transaction, [107]).AsOk;
        var payload = new State.Value([], "application/octet-stream", [("present", "")]);
        _ = State.Put(transaction, [107], payload).AsOk;
        _ = State.Delete(transaction, [107]).AsOk;
        using var commandPage = State.Scan(transaction, [], 1, null).AsOk;
        var description = State.DescribePage(commandPage).AsOk;
        var entry = State.PageNext(commandPage).AsOk;
        var intent = new Intents.Intent("approved-mail", "send", payload, ulong.MaxValue);
        var staged = Intents.Stage(transaction, intent).AsOk;
        return staged.sequence + description.entryCount + (ulong)command.commandId.Length
            + (existing.HasValue ? 1UL : 0UL) + (entry.HasValue ? 1UL : 0UL);
    }
}
