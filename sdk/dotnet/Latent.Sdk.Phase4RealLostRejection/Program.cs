using System.Text;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;
using Tx = Latent.Sdk.Transactions;

// Explicit lost rejection and fresh-client recovery on a provisioned node.
static string Required(string key) => Environment.GetEnvironmentVariable(key) is { Length: > 0 } value
    ? value : throw new InvalidOperationException("missing live fixture field: " + key);
static void Check(bool value, string label) { if (!value) throw new InvalidOperationException(label); }
static string Hex(ReadOnlyMemory<byte> value) => Convert.ToHexString(value.Span).ToLowerInvariant();
string tenant = Required("LSF_401_TENANT"), key = "dotnet-sdk-lost-rejection";
var ns = new Tx.NamespaceSelector(tenant, Required("LSF_401_NAMESPACE"), Required("LSF_401_INCARNATION"));
var selector = new Tx.CommandSelector(ns, "update", null, key, null);
bool cancellation = Environment.GetEnvironmentVariable("LSF_401_CANCEL_AFTER_DISPATCH") == "1";
var options = new Profile.CallOptions(cancellation ? 15000UL : 5000UL);
var config = new ClientOptions { Endpoint = "http://" + Required("LSF_401_ENDPOINT"), BearerToken = Required("LSF_401_TOKEN"), DefaultTimeout = TimeSpan.FromSeconds(cancellation ? 15 : 5) };
var client = await BoundedClient.ConnectAsync(config);
try
{
    string mode = Required("LSF_401_MODE");
    if (mode == "recover")
    {
        var lookup = new Tx.LookupCommandRequest(Tx.CurrentTransactionProfile.Create(), selector, null, new Profile.PublicationRef(Required("LSF_401_PUBLICATION"), tenant));
        using var recovery = new CancellationTokenSource();
        var c = (await client.LookupCommandAsync(lookup, options, recovery.Token)).Value.Command ?? throw new InvalidOperationException("missing command");
        var rejection = c.BusinessRejection ?? throw new InvalidOperationException("missing rejection");
        Check(c.Outcome == Tx.CommandOutcome.Rejected && c.MetadataDurable && !c.ApplicationStateCommitted && c.Commit is null, "durable rejection");
        Check(c.CommandId == Required("LSF_401_ORIGINAL_ID") && c.AttemptId == Required("LSF_401_ORIGINAL_ATTEMPT") && Hex(c.FingerprintSha256) == Required("LSF_401_ORIGINAL_FINGERPRINT"), "original identity");
        Check(Hex(Encoding.UTF8.GetBytes(rejection.Code)) == Required("LSF_401_REJECTION_CODE") && Hex(rejection.Payload) == Required("LSF_401_REJECTION_PAYLOAD"), "original rejection");
        Console.WriteLine("LOST_REJECTION_RECOVERED");
    }
    else
    {
        Check(mode == "invoke" || mode == "conflict", "mode");
        byte[] version = Convert.FromHexString(Required("LSF_401_EXPECTED_VERSION_HEX")); Check(version.Length > 0, "current key version");
        var target = new Profile.InvocationTarget(tenant, "examples/transaction-java-aggregate", "examples:transactional-aggregate/api@1.0.0", "update", "transaction-java-aggregate");
        var budget = new Profile.ResourceBudget(1000000000, 67108864, 0, 0, 4194304, 2097152, 0, 0, 0, 1, 120000);
        var invocation = new Profile.InvokeRequest(key, null, null, target, Encoding.UTF8.GetBytes(mode == "conflict" ? "[{\"delta\":2,\"reject\":true}]" : "[{\"delta\":1,\"reject\":true}]"),
            "application/vnd.latent.wit-values.v1+json", null, 0, null, budget, new Dictionary<string,string>());
        var request = new Tx.InvokeCommandRequest(Tx.CurrentTransactionProfile.Create(), invocation, selector, "lsf-wit-values-v1", new[] { new Tx.ExpectedVersion(Encoding.UTF8.GetBytes("aggregate/count"), null, version) }, null);
        if (cancellation)
        {
            using var before = new CancellationTokenSource(); before.Cancel();
            Tx.TransactionFailure? early = null;
            try { await client.InvokeCommandAsync(request, options, before.Token); }
            catch (Tx.TransactionCancellationException error) { early = error.Failure; }
            Check(early is not null && early.Transport.Category == Profile.FailureCategory.LocalCancelled && !early.Transport.Dispatched && early.Transport.Outcome == Profile.OutcomeKnowledge.NotDispatched && early.Identity.Command?.ClientKey == key && early.Observed is null, "pre-cancelled call");
            Console.WriteLine("CANCELLED_BEFORE_DISPATCH");
        }
        using var active = new CancellationTokenSource();
        if (cancellation) active.CancelAfter(TimeSpan.FromSeconds(5));
        bool failed = false;
        try { await client.InvokeCommandAsync(request, options, active.Token); }
        catch (Tx.TransactionCancellationException error)
        {
            var failure = error.Failure;
            Check(cancellation && failure.Transport.Category == Profile.FailureCategory.LocalCancelled, "caller cancellation");
            Check(failure.Transport.Dispatched && failure.Transport.Outcome == Profile.OutcomeKnowledge.Unknown, "dispatched unknown");
            Check(failure.Identity.Command?.ClientKey == key && failure.Observed is null, "original identity without fabricated outcome");
            Console.WriteLine("CANCELLED_DISPATCH_UNKNOWN");
            failed = true;
        }
        catch (Tx.TransactionException error)
        {
            var failure = error.Failure;
            Check(!cancellation, "unexpected transaction failure during cancellation");
            Check(failure.Transport.Dispatched && failure.Transport.Outcome == Profile.OutcomeKnowledge.Unknown, "dispatched unknown");
            Check(failure.Identity.Command?.ClientKey == key && failure.Observed is null, "original identity without fabricated outcome");
            if (mode == "conflict") Check(failure.Transport.GrpcStatus == 6, "retained key conflict");
            failed = true;
        }
        Check(failed, "response must be withheld");
        Console.WriteLine(mode == "conflict" ? "CHANGED_INPUT_CONFLICT" : "LOST_REJECTION_UNKNOWN");
    }
}
finally { await client.DisposeAsync(); Check(client.Snapshot().Reaped, "client retirement"); }
