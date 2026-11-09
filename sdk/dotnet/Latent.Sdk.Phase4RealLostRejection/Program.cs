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
var options = new Profile.CallOptions(5000);
var config = new ClientOptions { Endpoint = "http://" + Required("LSF_401_ENDPOINT"), BearerToken = Required("LSF_401_TOKEN") };
var client = await BoundedClient.ConnectAsync(config);
try
{
    if (Required("LSF_401_MODE") == "recover")
    {
        var lookup = new Tx.LookupCommandRequest(Tx.CurrentTransactionProfile.Create(), selector, null, new Profile.PublicationRef(Required("LSF_401_PUBLICATION"), tenant));
        var c = (await client.LookupCommandAsync(lookup, options)).Value.Command ?? throw new InvalidOperationException("missing command");
        var rejection = c.BusinessRejection ?? throw new InvalidOperationException("missing rejection");
        Check(c.Outcome == Tx.CommandOutcome.Rejected && c.MetadataDurable && !c.ApplicationStateCommitted && c.Commit is null, "durable rejection");
        Check(c.CommandId == Required("LSF_401_ORIGINAL_ID") && c.AttemptId == Required("LSF_401_ORIGINAL_ATTEMPT") && Hex(c.FingerprintSha256) == Required("LSF_401_ORIGINAL_FINGERPRINT"), "original identity");
        Check(Hex(Encoding.UTF8.GetBytes(rejection.Code)) == Required("LSF_401_REJECTION_CODE") && Hex(rejection.Payload) == Required("LSF_401_REJECTION_PAYLOAD"), "original rejection");
        Console.WriteLine("LOST_REJECTION_RECOVERED");
    }
    else
    {
        Check(Required("LSF_401_MODE") == "invoke", "mode");
        byte[] version = Convert.FromHexString(Required("LSF_401_EXPECTED_VERSION_HEX")); Check(version.Length > 0, "current key version");
        var target = new Profile.InvocationTarget(tenant, "examples/transaction-java-aggregate", "examples:transactional-aggregate/api@1.0.0", "update", "transaction-java-aggregate");
        var budget = new Profile.ResourceBudget(1000000000, 67108864, 0, 0, 4194304, 2097152, 0, 0, 0, 1, 120000);
        var invocation = new Profile.InvokeRequest(key, null, null, target, Encoding.UTF8.GetBytes("[{\"delta\":1,\"reject\":true}]"),
            "application/vnd.latent.wit-values.v1+json", null, 0, null, budget, new Dictionary<string,string>());
        var request = new Tx.InvokeCommandRequest(Tx.CurrentTransactionProfile.Create(), invocation, selector, "lsf-wit-values-v1", new[] { new Tx.ExpectedVersion(Encoding.UTF8.GetBytes("aggregate/count"), null, version) }, null);
        bool failed = false;
        try { await client.InvokeCommandAsync(request, options); }
        catch (Tx.TransactionException error)
        {
            var failure = error.Failure;
            Check(failure.Transport.Dispatched && failure.Transport.Outcome == Profile.OutcomeKnowledge.Unknown, "dispatched unknown");
            Check(failure.Identity.Command?.ClientKey == key && failure.Observed is null, "original identity without fabricated outcome");
            failed = true;
        }
        Check(failed, "response must be withheld");
        Console.WriteLine("LOST_REJECTION_UNKNOWN");
    }
}
finally { await client.DisposeAsync(); Check(client.Snapshot().Reaped, "client retirement"); }
