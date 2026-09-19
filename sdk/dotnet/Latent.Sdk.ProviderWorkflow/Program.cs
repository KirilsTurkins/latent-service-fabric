using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;

namespace Latent.Examples;

internal sealed partial class Workflow
{
    private readonly Input input;
    private readonly CancellationToken stop;
    private readonly List<BoundedClient> clients = [];
    private readonly List<string> identities = [];
    private readonly Dictionary<string, bool> assertions = [];
    private static readonly Profile.CallOptions Calls = new(3000);
    internal string Stage { get; private set; } = "input";

    internal Workflow(Input input, CancellationToken stop) { this.input = input; this.stop = stop; }

    private void Require(bool condition) => Input.Require(condition, Stage);
    private void Passed(string name) => assertions.Add(name, true);
    private void AbsentAudit(Profile.ResponseMetadata value) => Require(value.AuditAck is null && value.AuditStatus is null && value.AuditAttemptSequence is null);
    private void AbsentAudit(Profile.ClientFailure value) => Require(value.AuditAck is null && value.AuditStatus is null && value.AuditAttemptSequence is null);

    private async Task<BoundedClient> Connect(bool wrongCredential = false, bool limited = false)
    {
        Require(clients.Count < 8);
        BoundedClient client = await BoundedClient.ConnectAsync(input.Options(wrongCredential, limited), stop);
        clients.Add(client);
        return client;
    }

    private async Task<Profile.ClientFailure> Failure(Task operation)
    {
        try { await operation.WaitAsync(stop); }
        catch (Profile.ClientException failure) { return failure.Failure; }
        catch (Profile.ClientCancellationException failure) { return failure.Failure; }
        throw new InvalidOperationException(Stage);
    }

    private async Task<Profile.ActivationStatus> Terminal(BoundedClient observer, string identity)
    {
        long start = Stopwatch.GetTimestamp();
        while (Stopwatch.GetElapsedTime(start) < TimeSpan.FromSeconds(3))
        {
            Profile.ActivationStatus value = (await observer.GetActivationAsync(new(identity), Calls, stop)).Value;
            Require(value.ActivationId == identity);
            if (value.TerminalState is not null)
            {
                Require(value.FinalConsumption is not null && value.TerminalAtUnixMillis is not null);
                return value;
            }
            await Task.Delay(5, stop);
        }
        throw new InvalidOperationException(Stage);
    }

    private async Task Invocations(BoundedClient client)
    {
        foreach (string provider in new[] { "http", "blob" })
        {
            Stage = provider + "-guest";
            string identity = "dotnet-" + provider;
            Profile.InvokeResponse response = (await client.InvokeAsync(input.Request(provider, identity), Calls, stop)).Value;
            input.Receipt(response, provider, identity);
            Require(Input.Guest(response) == (provider == "http" ? 2201UL : 4UL));
            identities.Add(identity);
            Passed(provider + "Guest");
        }
        Stage = "declared-error";
        Profile.InvokeResponse declared = (await client.InvokeAsync(input.Request("callee", "dotnet-declared", "fail"), Calls, stop)).Value;
        input.Receipt(declared, "callee", "dotnet-declared");
        Require(declared.DeclaredError is not null && declared.Success is null && declared.PlatformFailure is null);
        identities.Add("dotnet-declared");
        Passed("declaredError");
        Stage = "platform-failure";
        Profile.InvokeResponse platform = (await client.InvokeAsync(input.Request("callee", "dotnet-platform", "spin"), Calls, stop)).Value;
        input.Receipt(platform, "callee", "dotnet-platform");
        Require(platform.PlatformFailure is not null && platform.Success is null && platform.DeclaredError is null);
        identities.Add("dotnet-platform");
        Passed("platformFailure");
        Stage = "wrong-tenant";
        Profile.ClientFailure wrongTenant = await Failure(client.InvokeAsync(input.Request("callee", "dotnet-wrong-tenant", tenant: "foreign"), Calls, stop).AsTask());
        Require(wrongTenant.Category == Profile.FailureCategory.Rpc && wrongTenant.GrpcStatus == 7);
        Passed("wrongTenant");
        Stage = "wrong-credential";
        BoundedClient denied = await Connect(wrongCredential: true);
        Profile.ClientFailure wrongCredential = await Failure(denied.InvokeAsync(input.Request("callee", "dotnet-wrong-credential"), Calls, stop).AsTask());
        Require(wrongCredential.Category == Profile.FailureCategory.Rpc && wrongCredential.GrpcStatus == 16);
        await denied.DisposeAsync();
        Passed("wrongCredential");
        Stage = "response-limit";
        BoundedClient limited = await Connect(limited: true);
        Profile.ClientFailure size = await Failure(limited.InvokeAsync(input.Request("callee", "dotnet-response-limit"), Calls, stop).AsTask());
        Require(size.Category == Profile.FailureCategory.Limit && size.Dispatched && size.Outcome == Profile.OutcomeKnowledge.Unknown &&
            size.Identity.ActivationId == "dotnet-response-limit");
        await limited.DisposeAsync();
        Require((await Terminal(client, "dotnet-response-limit")).Succeeded is not null);
        identities.Add("dotnet-response-limit");
        Passed("responseLimit");
    }

    private async Task<object> Execute()
    {
        try
        {
            BoundedClient client = await Connect();
            await Invocations(client);
            await Management(client);
            foreach (string kind in new[] { "local-cancel", "explicit-cancel", "deadline", "shutdown" }) await Held(client, kind);
            Stage = "retained-terminal-identities";
            foreach (string identity in identities) await Terminal(client, identity);
        }
        finally
        {
            await Task.WhenAll(clients.Select(client => client.DisposeAsync().AsTask()));
        }
        Stage = "client-owners-reaped";
        Require(clients.All(client => client.Snapshot() is { Reaped: true, InFlight: 0, Queued: 0, WireStreams: 0 }));
        Passed("clientOwnersReaped");
        Require(assertions.Count == 18 && identities.Count == 9 && identities.Distinct().Count() == 9);
        return new
        {
            schemaVersion = "latent.sdk.provider.workflow.result.v1", language = "dotnet", assertions,
            activationIds = identities, operationId = "dotnet-policy-create", auditAttempt = (string?)null,
            transport = "numeric-loopback-http2-protobuf-v1"
        };
    }

    private static async Task<int> Main(string[] args)
    {
        Workflow? workflow = null;
        try
        {
            Input.Require(args.Length == 2 && args[0] == "--config", "configuration-arguments");
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(80));
            workflow = new(new Input(args[1]), deadline.Token);
            Console.WriteLine(JsonSerializer.Serialize(await workflow.Execute()));
            return 0;
        }
        catch (Exception failure)
        {
            var diagnostic = new Dictionary<string, object> { ["stage"] = "dotnet-participant", ["reason"] = workflow?.Stage ?? "input" };
            Profile.ClientFailure? details = failure is Profile.ClientException client ? client.Failure :
                failure is Profile.ClientCancellationException cancelled ? cancelled.Failure : null;
            if (details is not null)
            {
                diagnostic["category"] = details.Category.Value;
                if (details.GrpcStatus is >= 0 and <= 16) diagnostic["grpcStatus"] = details.GrpcStatus.Value;
            }
            Console.Error.WriteLine(JsonSerializer.Serialize(diagnostic));
            return 1;
        }
    }
}
