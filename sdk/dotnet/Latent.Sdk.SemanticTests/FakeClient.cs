using Latent.Sdk;

namespace Latent.Sdk.SemanticTests;

// Test-only server policy and interface fixture. This is not an SDK transport.
internal sealed class FakeClient : ILatentClient
{
    internal sealed class TransportFailure(string message) : Exception(message) { }
    internal sealed class ServerRejection(string message) : Exception(message) { }

    private static readonly BudgetConsumption Consumption = new(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    private static readonly IReadOnlyDictionary<string, string> Metadata = new Dictionary<string, string>();
    private static readonly PlatformFailure Cancelled = new("cancelled", "fixture cancellation", false, []);

    private sealed class Entry(string id, InvokeRequest request)
    {
        public string Root { get; } = request.RootActivationId ?? id;
        public string? Parent { get; } = request.ParentActivationId;
        public TaskCompletionSource<InvocationOutcome> Response { get; } =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
        public ActivationStatus Status { get; set; } = new(id, "running", null, null, null, 1, null, Metadata);
        public bool CancelRequested { get; set; }
    }

    public List<InvokeRequest> Requests { get; } = [];
    public bool FailNextCancel { get; set; }
    private readonly Dictionary<string, Entry> entries = [];

    public ValueTask<InvocationOutcome> InvokeAsync(InvokeRequest request, CancellationToken cancellationToken = default)
    {
        Requests.Add(request);
        if (request.ActivationId == "" || request.RootActivationId == "" || request.ParentActivationId == ""
            || (request.ParentActivationId is not null && request.RootActivationId is null))
        {
            return ValueTask.FromException<InvocationOutcome>(new ServerRejection("invalid-argument"));
        }
        // Assignment belongs to this fake server after observing the unchanged request.
        var id = request.ActivationId ?? $"server-assigned-{Requests.Count}";
        if (entries.ContainsKey(id))
        {
            return ValueTask.FromException<InvocationOutcome>(new ServerRejection("already-exists"));
        }
        var entry = new Entry(id, request);
        entries.Add(id, entry);
        return new ValueTask<InvocationOutcome>(entry.Response.Task);
    }

    public ValueTask<CancelResponse> CancelAsync(string activationId, string reason,
        CancellationToken cancellationToken = default)
    {
        if (FailNextCancel)
        {
            FailNextCancel = false;
            return ValueTask.FromException<CancelResponse>(new TransportFailure("cancel transport unavailable"));
        }
        if (!entries.TryGetValue(activationId, out var entry))
        {
            return ValueTask.FromResult(new CancelResponse(CancelDisposition.NotFound, null));
        }
        if (entry.Status.TerminalState is not null)
        {
            return ValueTask.FromResult(new CancelResponse(CancelDisposition.AlreadyTerminal, entry.Status.TerminalState));
        }
        entry.CancelRequested = true;
        return ValueTask.FromResult(new CancelResponse(CancelDisposition.Accepted, null));
    }

    public ValueTask<ActivationStatus> GetActivationAsync(string activationId,
        CancellationToken cancellationToken = default) =>
        entries.TryGetValue(activationId, out var entry)
            ? ValueTask.FromResult(entry.Status)
            : ValueTask.FromException<ActivationStatus>(new ServerRejection("not-found"));

    public (string Root, string? Parent) Lineage(string id) => (entries[id].Root, entries[id].Parent);

    public void Finish(string id, bool loseResponse = false)
    {
        var entry = entries[id];
        var terminal = entry.CancelRequested ? "cancelled" : "completed";
        RetainedInvocationOutcome retained = entry.CancelRequested
            ? new RetainedInvocationOutcome.PlatformFailure(Cancelled)
            : new RetainedInvocationOutcome.Succeeded(null, [], Metadata);
        entry.Status = new ActivationStatus(id, entry.CancelRequested ? "running" : "committed",
            terminal, retained, Consumption, 2, 2, Metadata);
        if (loseResponse)
        {
            entry.Response.SetException(new TransportFailure("invoke response lost after completion"));
        }
        else if (entry.CancelRequested)
        {
            entry.Response.SetResult(new InvocationOutcome.PlatformFailure(
                new InvocationReceipt(id, "r", "d", 1, Consumption), Cancelled));
        }
        else
        {
            entry.Response.SetResult(new InvocationOutcome.Succeeded(new InvokeResponse(
                id, "r", "d", 1, ReadOnlyMemory<byte>.Empty, "application/octet-stream",
                null, [], Consumption, Metadata)));
        }
    }
}
