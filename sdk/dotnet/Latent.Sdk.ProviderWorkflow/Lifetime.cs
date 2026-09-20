using System.Diagnostics;
using System.Text;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;

namespace Latent.Examples;

internal sealed partial class Workflow
{
    private void Mode(string value)
    {
        string temporary = Path.Combine(input.Control, "mode-dotnet.tmp");
        using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) output.Write(Encoding.ASCII.GetBytes(value));
        File.Move(temporary, Path.Combine(input.Control, "mode"), true);
    }

    private async Task Marker(string prefix, string token, Task? pending = null)
    {
        string path = Path.Combine(input.Control, prefix + "-" + token);
        long start = Stopwatch.GetTimestamp();
        while (Stopwatch.GetElapsedTime(start) < TimeSpan.FromSeconds(3))
        {
            if (File.Exists(path))
            {
                Require((File.GetAttributes(path) & (FileAttributes.ReparsePoint | FileAttributes.Directory)) == 0 &&
                    Input.Read(path, 16).AsSpan().SequenceEqual("observed\n"u8));
                return;
            }
            Require(pending is null || !pending.IsCompleted);
            await Task.Delay(2, stop);
        }
        throw new InvalidOperationException(Stage);
    }

    private async Task Cancel(BoundedClient observer, string identity)
    {
        Profile.CancelResponse response = (await observer.CancelAsync(new(identity, "explicit workflow recovery"), Calls, stop)).Value;
        Require(response.Disposition == Profile.CancelDisposition.Accepted || response.Disposition == Profile.CancelDisposition.AlreadyTerminal);
    }

    private async Task Held(BoundedClient observer, string kind)
    {
        Stage = "held-" + kind;
        string identity = "dotnet-" + kind;
        string token = "hold-" + identity;
        BoundedClient client = await Connect();
        using var local = CancellationTokenSource.CreateLinkedTokenSource(stop);
        Mode(token);
        ulong timeout = kind == "deadline" ? 500UL : 3000UL;
        ulong? deadline = kind == "deadline" ? checked((ulong)DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + timeout) : null;
        long start = Stopwatch.GetTimestamp();
        Task<Profile.ClientResponse<Profile.InvokeResponse>> pending = client.InvokeAsync(input.Request("http", identity, deadline: deadline), new(timeout), local.Token).AsTask();
        Stage = "held-" + kind + "-upstream-start";
        await Marker("started", token, pending);
        identities.Add(identity);
        Stage = "held-" + kind + "-active-status";
        Profile.ActivationStatus active = (await observer.GetActivationAsync(new(identity), Calls, stop)).Value;
        Require(active.ActivationId == identity && active.TerminalState is null && !pending.IsCompleted);
        Stage = "held-" + kind + "-terminal-response";
        switch (kind)
        {
            case "local-cancel":
                // lsf-example-begin: cancel
                local.Cancel();
                Profile.ClientFailure cancelled = await Failure(pending);
                Require(cancelled.Category == Profile.FailureCategory.LocalCancelled && cancelled.Dispatched &&
                    cancelled.Outcome == Profile.OutcomeKnowledge.Unknown && cancelled.Identity.ActivationId == identity);
                await Cancel(observer, identity);
                // lsf-example-end: cancel
                Passed("localCancellation");
                break;
            case "explicit-cancel":
                await Cancel(observer, identity);
                try
                {
                    Profile.InvokeResponse response = (await pending).Value;
                    Require(response.ActivationId == identity && response.PlatformFailure?.Code == "cancelled");
                }
                catch (Profile.ClientException failure)
                {
                    Require(failure.Failure.GrpcStatus is 1 or 4 && failure.Failure.Identity.ActivationId == identity);
                }
                Passed("explicitCancellation");
                break;
            case "deadline":
                try
                {
                    Profile.InvokeResponse response = (await pending).Value;
                    Require(response.ActivationId == identity && response.PlatformFailure?.Code == "deadline-exceeded");
                }
                catch (Exception failure) when (failure is Profile.ClientException or Profile.ClientCancellationException)
                {
                    Profile.ClientFailure details = failure is Profile.ClientException rpc ? rpc.Failure : ((Profile.ClientCancellationException)failure).Failure;
                    Require(details.Category == Profile.FailureCategory.Deadline && details.Identity.ActivationId == identity);
                }
                Stage = "held-deadline-completion-bound";
                Require(Stopwatch.GetElapsedTime(start) < TimeSpan.FromSeconds(2));
                Passed("absoluteDeadline");
                break;
            case "shutdown":
                await client.DisposeAsync();
                Profile.ClientFailure shutdown = await Failure(pending);
                Require(shutdown.Category == Profile.FailureCategory.Transport && shutdown.Dispatched &&
                    shutdown.Outcome == Profile.OutcomeKnowledge.Unknown && shutdown.Identity.ActivationId == identity);
                await Cancel(observer, identity);
                Passed("shutdownOutstanding");
                break;
            default: throw new InvalidOperationException(Stage);
        }
        Stage = "held-" + kind + "-upstream-closed";
        await Marker("closed", token);
        Stage = "held-" + kind + "-terminal-status";
        await Terminal(observer, identity);
        if (kind == "local-cancel") Passed("lostResponseStatus");
        Mode("reply");
        await client.DisposeAsync();
    }
}
