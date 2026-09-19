using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.Transport.Tests;

internal static partial class Program
{
    internal const string Token = "LSF-DOTNET-CONTROLLED-PEER-TEST-ONLY";
    private static readonly Profile.CallOptions Defaults = new(null);
    private static int assertions;

    private static async Task<int> Main()
    {
        try
        {
            SharedVectors();
            foreach (Func<Task> scenario in new Func<Task>[]
            {
                EightOperations, CancellationAndQueue, DeadlinesAndShutdown, NoReplay, LostMutation,
                MalformedAndBounds, AuditAndRawStatus, ConnectionOwnership, ZeroLengthReads, FrameFragments, StalledRawPeers
            })
            {
                await scenario().WaitAsync(TimeSpan.FromSeconds(30));
                Console.WriteLine("PASS " + scenario.Method.Name);
            }
            Console.WriteLine($"PASS .NET native transport: {assertions} checks");
            return 0;
        }
        catch (Exception failure)
        {
            Console.Error.WriteLine(failure);
            return 1;
        }
    }

    internal static void Check(bool valid, string message)
    {
        if (!valid) throw new InvalidOperationException(message);
        Interlocked.Increment(ref assertions);
    }

    private static async Task<Profile.ClientFailure> Failure(Task operation, Profile.FailureCategory? category = null, bool? dispatched = null)
    {
        try { await operation.WaitAsync(TimeSpan.FromSeconds(4)); }
        catch (Exception exception) when (exception is Profile.ClientException or Profile.ClientCancellationException)
        {
            Profile.ClientFailure failure = exception is Profile.ClientException client ? client.Failure : ((Profile.ClientCancellationException)exception).Failure;
            Check(category is null || failure.Category == category, "unexpected failure category: " + failure.Category.Value + " " + failure.Message);
            Check(dispatched is null || failure.Dispatched == dispatched, "dispatch evidence changed");
            return failure;
        }
        throw new InvalidOperationException("expected a typed client failure");
    }

    private static async Task Until(Func<bool> condition)
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        while (!condition()) await Task.Delay(2, deadline.Token);
    }

    private static Profile.InvokeRequest Invoke(string? identity = "activation-a") => new(identity, null, null,
        new("tenant-a", "echo", "tests:echo/api@1.0.0", "run", null), new byte[] { 0, 255, 1, 128 }, "application/octet-stream",
        null, 0, null, new(ulong.MaxValue, 4096, 0, 0, 0, 0, 0, 0, 0, 0, 0), new Dictionary<string, string>());

    private static Profile.ApplyPolicyRequest Apply() => new(new("policy-a", new("policy-a", "tenant-a", null,
        new Dictionary<string, string>(), new Dictionary<string, string>()), "{\"rules\":[]}", 0, "lsf-capability-policy-v1",
        Profile.CapabilityPolicyRecordKind.Policy, "", false), 0, "operation-a");

    private static ClientOptions Options(string endpoint, int inflight = 8, int recovery = 2, int queue = 8,
        int response = 1024 * 1024, int nodes = 8192, TimeSpan? timeout = null) => new()
    {
        Endpoint = endpoint, BearerToken = Token, MaxInFlight = inflight, ReservedRecovery = recovery, MaxQueued = queue,
        MaxResponseBytes = response, MaxGraphNodes = nodes, DefaultTimeout = timeout ?? TimeSpan.FromSeconds(2), ConnectTimeout = TimeSpan.FromSeconds(1)
    };
}
