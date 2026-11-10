using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;
using Tx = Latent.Sdk.Transactions;

// Explicit live-node probe; the caller provisions the committed fixture.
static string Required(string key) => Environment.GetEnvironmentVariable(key) is { Length: > 0 } value
    ? value : throw new InvalidOperationException("missing live fixture field: " + key);
static void Check(bool value, string label) { if (!value) throw new InvalidOperationException(label); }
string tenant = Required("LSF_401_TENANT"), key = Required("LSF_401_COMMAND_KEY");
var ns = new Tx.NamespaceSelector(tenant, Required("LSF_401_NAMESPACE"), Required("LSF_401_INCARNATION"));
var selector = new Tx.CommandSelector(ns, Required("LSF_401_OPERATION"), null, key, null);
var request = new Tx.LookupCommandRequest(Tx.CurrentTransactionProfile.Create(), selector, null,
    new Profile.PublicationRef(Required("LSF_401_PUBLICATION"), tenant));
var client = await BoundedClient.ConnectAsync(new ClientOptions
    { Endpoint = "http://" + Required("LSF_401_ENDPOINT"), BearerToken = Required("LSF_401_TOKEN") });
try
{
    var options = new Profile.CallOptions(5000);
    var first = (await client.LookupCommandAsync(request, options)).Value.Command ?? throw new InvalidOperationException("first command missing");
    var second = (await client.LookupCommandAsync(request, options)).Value.Command ?? throw new InvalidOperationException("second command missing");
    Check(first.CommandId == Required("LSF_401_COMMAND_ID") && first.AttemptId == Required("LSF_401_ATTEMPT_ID"), "command identity");
    Check(first.Key?.ClientKey == key && first.Outcome == Tx.CommandOutcome.Committed && first.MetadataDurable
        && first.ApplicationStateCommitted && first.Commit is not null, "committed command");
    Check(first.CommandId == second.CommandId && first.AttemptId == second.AttemptId && first.Key == second.Key
        && first.FingerprintSha256.ToArray().SequenceEqual(second.FingerprintSha256.ToArray()) && first.Outcome == second.Outcome
        && first.Source == second.Source && first.Commit!.ReceiptId == second.Commit?.ReceiptId, "stable original receipt");
}
finally
{
    await client.DisposeAsync();
    var state = client.Snapshot();
    Check(state.Closed && state.Reaped && state.InFlight == 0 && state.Queued == 0 && state.WireStreams == 0, "client owner retirement");
}
Console.WriteLine(".NET live original-command lookup and shutdown passed");
