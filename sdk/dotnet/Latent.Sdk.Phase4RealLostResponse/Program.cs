using System.Text;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;
using Tx = Latent.Sdk.Transactions;

// Explicit lost response and fresh-client recovery on a provisioned node.
static string Required(string key) => Environment.GetEnvironmentVariable(key) is { Length: > 0 } value
    ? value : throw new InvalidOperationException("missing live fixture field: " + key);
static void Check(bool value, string label) { if (!value) throw new InvalidOperationException(label); }
static string Hex(ReadOnlyMemory<byte> value) => Convert.ToHexString(value.Span).ToLowerInvariant();
string tenant = Required("LSF_401_TENANT"), key = "dotnet-sdk-lost-response";
var ns = new Tx.NamespaceSelector(tenant, Required("LSF_401_NAMESPACE"), Required("LSF_401_INCARNATION"));
var selector = new Tx.CommandSelector(ns, "update", null, key, null);
bool cancellation = Environment.GetEnvironmentVariable("LSF_401_CANCEL_AFTER_DISPATCH") == "1";
var options = new Profile.CallOptions(cancellation ? 15000UL : 5000UL);
var config = new ClientOptions { Endpoint = "http://" + Required("LSF_401_ENDPOINT"), BearerToken = Required("LSF_401_TOKEN"), DefaultTimeout = TimeSpan.FromSeconds(cancellation ? 15 : 5) };
var client = await BoundedClient.ConnectAsync(config);
try
{
    if (Required("LSF_401_MODE") == "recover")
    {
        var lookup = new Tx.LookupCommandRequest(Tx.CurrentTransactionProfile.Create(), selector, null, new Profile.PublicationRef(Required("LSF_401_PUBLICATION"), tenant));
        var c = (await client.LookupCommandAsync(lookup, options)).Value.Command ?? throw new InvalidOperationException("missing command");
        var receipt = c.Commit ?? throw new InvalidOperationException("missing receipt");
        Check(c.Outcome == Tx.CommandOutcome.Committed && c.MetadataDurable && c.ApplicationStateCommitted, "durable commit");
        Check(c.CommandId == Required("LSF_401_ORIGINAL_ID") && c.AttemptId == Required("LSF_401_ORIGINAL_ATTEMPT") && Hex(c.FingerprintSha256) == Required("LSF_401_ORIGINAL_FINGERPRINT"), "original identity");
        Check(receipt.ReceiptId == Required("LSF_401_ORIGINAL_RECEIPT") && receipt.EffectIds.SequenceEqual(new[] { Required("LSF_401_ORIGINAL_EFFECT") }), "original receipt");
        Console.WriteLine("LOST_COMMIT_RECOVERED");
    }
    else
    {
        Check(Required("LSF_401_MODE") == "invoke", "mode");
        byte[] version = Convert.FromHexString(Required("LSF_401_EXPECTED_VERSION_HEX")); Check(version.Length > 0, "current key version");
        var target = new Profile.InvocationTarget(tenant, "examples/transaction-java-aggregate", "examples:transactional-aggregate/api@1.0.0", "update", "transaction-java-aggregate");
        var budget = new Profile.ResourceBudget(1000000000, 67108864, 0, 0, 4194304, 2097152, 0, 0, 0, 1, 120000);
        var invocation = new Profile.InvokeRequest(key, null, null, target, Encoding.UTF8.GetBytes("[{\"delta\":1,\"reject\":false}]"),
            "application/vnd.latent.wit-values.v1+json", null, 0, null, budget, new Dictionary<string,string>());
        var request = new Tx.InvokeCommandRequest(Tx.CurrentTransactionProfile.Create(), invocation, selector, "lsf-wit-values-v1", new[] { new Tx.ExpectedVersion(Encoding.UTF8.GetBytes("aggregate/count"), null, version) }, null);
        bool failed = false;
        using var active = new CancellationTokenSource();
        if (cancellation) active.CancelAfter(TimeSpan.FromSeconds(5));
        try { await client.InvokeCommandAsync(request, options, active.Token); }
        catch (Tx.TransactionCancellationException error)
        {
            var failure = error.Failure;
            Check(cancellation && failure.Transport.Category == Profile.FailureCategory.LocalCancelled, "caller cancellation");
            Check(failure.Transport.Dispatched && failure.Transport.Outcome == Profile.OutcomeKnowledge.Unknown, "dispatched unknown");
            Check(failure.Identity.Command?.ClientKey == key && failure.Observed is null, "original identity without fabricated outcome");
            Console.WriteLine("CANCELLED_COMMIT_UNKNOWN");
            failed = true;
        }
        catch (Tx.TransactionException error)
        {
            var failure = error.Failure;
            Check(!cancellation, "unexpected transaction failure during cancellation");
            Check(failure.Transport.Dispatched && failure.Transport.Outcome == Profile.OutcomeKnowledge.Unknown, "dispatched unknown");
            Check(failure.Identity.Command?.ClientKey == key && failure.Observed is null, "original identity without fabricated outcome");
            failed = true;
        }
        Check(failed, "response must be withheld");
        Console.WriteLine("LOST_RESPONSE_UNKNOWN");
    }
}
finally { await client.DisposeAsync(); Check(client.Snapshot().Reaped, "client retirement"); }
