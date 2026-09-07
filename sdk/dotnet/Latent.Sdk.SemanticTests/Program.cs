using Latent.Sdk;

namespace Latent.Sdk.SemanticTests;

internal static class Program
{
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(5);

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static async Task<T> Wait<T>(ValueTask<T> operation) =>
        await operation.AsTask().WaitAsync(Timeout);

    private static async Task Rejects<TException>(Task operation) where TException : Exception
    {
        try
        {
            await operation.WaitAsync(Timeout);
        }
        catch (TException)
        {
            return;
        }
        throw new InvalidOperationException("operation must fail with the expected distinct error");
    }

    private static InvokeRequest Absent()
    {
        var target = new InvocationTarget("tenant", "echo", "example:echo/api@1.0.0", "echo", null);
        var budget = new ResourceBudget(1, 1, null, 0, 0, 0, 0, 0, 0, 0, 0);
        var options = new InvokeOptions(null, 0, "separate-key", budget, new Dictionary<string, string>());
        // The original four-argument construction still leaves identities absent.
        return new InvokeRequest(target, new byte[] { 1 }, "application/octet-stream", options);
    }

    private static InvokeRequest Request(string? id = null, string? root = null, string? parent = null) =>
        Absent() with { ActivationId = id, RootActivationId = root, ParentActivationId = parent };

    private static async Task PendingCancellation()
    {
        var server = new FakeClient();
        ILatentClient client = server;
        var sent = Request(id: "known");
        var pending = client.InvokeAsync(sent).AsTask();
        Check((await Wait(client.GetActivationAsync("known"))).Phase == "running", "status before terminal");
        Check(!pending.IsCompleted, "known identity while invoke remains pending");
        Check(server.Lineage("known") == ("known", null), "server defaults root to the effective ID");
        server.FailNextCancel = true;
        await Rejects<FakeClient.TransportFailure>(client.CancelAsync("known", "stop").AsTask());
        var accepted = await Wait(client.CancelAsync("known", "stop"));
        Check(accepted.Disposition == CancelDisposition.Accepted && accepted.TerminalState is null,
            "accepted disposition is distinct from transport failure");
        Check(!pending.IsCompleted, "cancel acknowledgment is not terminal completion");
        server.Finish("known");
        var outcome = await pending.WaitAsync(Timeout);
        Check(outcome is InvocationOutcome.PlatformFailure { Error.Code: "cancelled" }, "typed cancellation outcome");
        var already = await Wait(client.CancelAsync("known", "again"));
        Check(already.Disposition == CancelDisposition.AlreadyTerminal && already.TerminalState == "cancelled",
            "already-terminal preserves terminal state");
        var missing = await Wait(client.CancelAsync("missing", "stop"));
        Check(missing.Disposition == CancelDisposition.NotFound && missing.TerminalState is null,
            "not-found disposition");
        Check(server.Requests.Count == 1 && ReferenceEquals(server.Requests[0], sent), "no identity rewrite or retry");
    }

    private static async Task LostResponse()
    {
        var server = new FakeClient();
        ILatentClient client = server;
        var pending = client.InvokeAsync(Request(id: "recoverable")).AsTask();
        server.Finish("recoverable", loseResponse: true);
        await Rejects<FakeClient.TransportFailure>(pending);
        var retained = await Wait(client.GetActivationAsync("recoverable"));
        Check(retained.TerminalState == "completed" && retained.TerminalOutcome is RetainedInvocationOutcome.Succeeded,
            "recover retained success by caller-known identity");
        Check(server.Requests.Count == 1, "status recovery must not reinvoke");
    }

    private static async Task OptionalIdentity()
    {
        var server = new FakeClient();
        var absent = Absent();
        var pending = server.InvokeAsync(absent).AsTask();
        Check(absent.ActivationId is null && absent.RootActivationId is null && absent.ParentActivationId is null,
            "absence preserved for server assignment");
        Check(server.Lineage("server-assigned-1") == ("server-assigned-1", null), "fake server root default");
        server.Finish("server-assigned-1");
        Check(await pending.WaitAsync(Timeout) is InvocationOutcome.Succeeded { Response.ActivationId: "server-assigned-1" },
            "server-assigned response identity");
        var explicitLineage = Request("child", "root", "parent");
        var child = server.InvokeAsync(explicitLineage).AsTask();
        Check(ReferenceEquals(server.Requests[1], explicitLineage) && server.Lineage("child") == ("root", "parent"),
            "explicit lineage survives unchanged as claims");
        server.Finish("child");
        await child.WaitAsync(Timeout);
        foreach (var invalid in new[]
        {
            Request(id: ""), Request(root: ""), Request(root: "root", parent: ""), Request(id: "orphan", parent: "parent"),
        })
        {
            await Rejects<FakeClient.ServerRejection>(server.InvokeAsync(invalid).AsTask());
            Check(ReferenceEquals(server.Requests[^1], invalid), "present empty and missing root arrive unchanged");
        }
    }

    public static async Task Main()
    {
        await PendingCancellation();
        await LostResponse();
        await OptionalIdentity();
        Console.WriteLine(".NET invocation identity semantic fixtures passed");
    }
}
