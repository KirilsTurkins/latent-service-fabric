using System.Text;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;
using Tx = Latent.Sdk.Transactions;

// Explicit version-fenced command against a separately provisioned node.
static string Required(string key) => Environment.GetEnvironmentVariable(key) is { Length: > 0 } value
    ? value : throw new InvalidOperationException("missing live fixture field: " + key);
static void Check(bool value, string label) { if (!value) throw new InvalidOperationException(label); }
string tenant = Required("LSF_401_TENANT"), key = "dotnet-sdk-direct-command";
byte[] version = Convert.FromHexString(Required("LSF_401_EXPECTED_VERSION_HEX")); Check(version.Length > 0, "current key version");
var ns = new Tx.NamespaceSelector(tenant, Required("LSF_401_NAMESPACE"), Required("LSF_401_INCARNATION"));
var selector = new Tx.CommandSelector(ns, "update", null, key, null);
var target = new Profile.InvocationTarget(tenant, "examples/transaction-java-aggregate", "examples:transactional-aggregate/api@1.0.0", "update", "transaction-java-aggregate");
var budget = new Profile.ResourceBudget(1000000000, 67108864, 0, 0, 4194304, 2097152, 0, 0, 0, 1, 120000);
var invocation = new Profile.InvokeRequest(key, null, null, target, Encoding.UTF8.GetBytes("[{\"delta\":1,\"reject\":false}]"),
    "application/vnd.latent.wit-values.v1+json", null, 0, null, budget, new Dictionary<string,string>());
var request = new Tx.InvokeCommandRequest(Tx.CurrentTransactionProfile.Create(), invocation, selector, "lsf-wit-values-v1",
    new[] { new Tx.ExpectedVersion(Encoding.UTF8.GetBytes("aggregate/count"), null, version) }, null);
var options = new Profile.CallOptions(5000);
var config = new ClientOptions { Endpoint = "http://" + Required("LSF_401_ENDPOINT"), BearerToken = Required("LSF_401_TOKEN") };
var client = await BoundedClient.ConnectAsync(config);
try
{
    try
    {
        var command = (await client.InvokeCommandAsync(request, options)).Value.Command ?? throw new InvalidOperationException("missing command");
        Check(command.Outcome == Tx.CommandOutcome.Committed && command.MetadataDurable && command.ApplicationStateCommitted && command.Commit?.EffectIds.Count == 1, "committed command");
        Console.WriteLine($"RESULT {command.CommandId} {command.AttemptId} {command.Commit!.EffectIds[0]}");
    }
    catch (Tx.TransactionException failure)
    {
        Console.Error.WriteLine($"DIAGNOSTIC category={failure.Failure.Transport.Category} outcome={failure.Failure.Transport.Outcome} dispatched={failure.Failure.Transport.Dispatched}");
        var recovery = await BoundedClient.ConnectAsync(config);
        try
        {
            var lookup = new Tx.LookupCommandRequest(Tx.CurrentTransactionProfile.Create(), selector, null, new Profile.PublicationRef(Required("LSF_401_PUBLICATION"), tenant));
            var original = (await recovery.LookupCommandAsync(lookup, options)).Value.Command ?? throw new InvalidOperationException("missing recovery");
            Console.Error.WriteLine($"RECOVERY outcome={original.Outcome} durable={original.MetadataDurable} committed={original.ApplicationStateCommitted} effects={original.Commit?.EffectIds.Count}");
        }
        finally { await recovery.DisposeAsync(); Check(recovery.Snapshot().Reaped, "recovery retirement"); }
        throw;
    }
}
finally { await client.DisposeAsync(); Check(client.Snapshot().Reaped, "client retirement"); }
