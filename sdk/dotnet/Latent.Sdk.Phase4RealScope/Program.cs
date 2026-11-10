using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;
using Tx = Latent.Sdk.Transactions;

// Explicit caller-scope refusal on a provisioned node.
static string Required(string key) => Environment.GetEnvironmentVariable(key) is { Length: > 0 } value
    ? value : throw new InvalidOperationException("missing live fixture field: " + key);
static void Check(bool value, string label) { if (!value) throw new InvalidOperationException(label); }
string tenant = Required("LSF_401_TENANT"), key = Required("LSF_401_COMMAND_KEY");
var ns = new Tx.NamespaceSelector(tenant, Required("LSF_401_NAMESPACE"), Required("LSF_401_INCARNATION"));
var selector = new Tx.CommandSelector(ns, Required("LSF_401_OPERATION"), null, key, null);
var request = new Tx.LookupCommandRequest(Tx.CurrentTransactionProfile.Create(), selector, null,
    new Profile.PublicationRef(Required("LSF_401_PUBLICATION"), tenant));
var client = await BoundedClient.ConnectAsync(new ClientOptions
    { Endpoint = "http://" + Required("LSF_401_ENDPOINT"), BearerToken = Required("LSF_401_SCOPE_TOKEN") });
try
{
    var options = new Profile.CallOptions(5000);
    bool refused = false;
    try { await client.LookupCommandAsync(request, options); }
    catch (Tx.TransactionException error) { Check(error.Failure.Transport.GrpcStatus == 7 && error.Failure.Observed is null, "scope refusal"); refused = true; }
    Check(refused, "different caller must not recover original");
}
finally
{
    await client.DisposeAsync();
    var state = client.Snapshot();
    Check(state.Closed && state.Reaped && state.InFlight == 0 && state.Queued == 0 && state.WireStreams == 0, "client owner retirement");
}
Console.WriteLine("SCOPE_REFUSED grpc=7");
