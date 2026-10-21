using System;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;

namespace OutsideResourceRuntime;

public static class Library
{
    private static int calls;
    private static readonly AsyncLocal<string?> local = new();
    private static void Need(bool value)
    {
        if (!value) throw new InvalidOperationException("resource-late-observable");
    }
    private static string Read(Stream input)
    {
        using var output = new MemoryStream(); input.CopyTo(output);
        return Convert.ToHexString(output.ToArray()).ToLowerInvariant();
    }
    private static void Facilities(Stream first, Stream second, char marker)
    {
        Need(Data.TextHex() == "4772c3bcc39f6500e99baa0a"); Data.CheckEmpty();
        long before = Stopwatch.GetTimestamp();
        long wall = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        byte[] entropy = new byte[8]; RandomNumberGenerator.Fill(entropy);
        Need(before >= 0 && Stopwatch.GetTimestamp() >= before && wall > 0x1_0000_0000L);
        Array.Clear(entropy); first.Dispose(); second.Dispose();
        // One standard synchronous record after all resource/facility operations.
        Console.Write(marker); Console.Out.Flush();
    }
    public static string Run(string mode)
    {
        Need(++calls == 1 && local.Value is null && SynchronizationContext.Current is null);
        local.Value = "root";
        using var first = Data.Open(); using var second = Data.Open();
        if (mode == "fresh")
        {
            Need(Read(first) == "00ff80410d0a" && Read(second) == "00ff80410d0a");
            Facilities(first, second, 'F'); Need(local.Value == "root");
            return "resource-late|fresh|readers=2|binary=00ff80410d0a|text=1|empty=1|entropy=8|wall64=1|closed=1";
        }
        Need(mode == "late");
        int entered = 0, completed = 0, closed = 0;
        var completion = new TaskCompletionSource<Task>(TaskCreationOptions.RunContinuationsAsynchronously);
        Timer? timer = null;
        timer = new Timer(_ =>
        {
            Task? actualDisposal = null;
            Exception? failure = null;
            try
            {
                Need(++entered == 1 && local.Value == "root"); local.Value = "callback";
                Need(first.ReadByte() == 0 && first.ReadByte() == 255 && second.ReadByte() == 0);
                var disposal = timer!.DisposeAsync();
                Need(!disposal.IsCompleted && completed == 0 && closed == 0);
                Need(Read(first) == "80410d0a" && Read(second) == "ff80410d0a");
                Facilities(first, second, 'L'); Need(local.Value == "callback");
                Need(++completed == 1);
                actualDisposal = disposal.AsTask();
            }
            catch (Exception error) { failure = error; }
            finally {
                try { first.Dispose(); }
                catch (Exception error) { failure ??= error; }
                finally {
                    try { second.Dispose(); }
                    catch (Exception error) { failure ??= error; }
                    finally { Interlocked.Increment(ref closed); }
                }
            }
            if (failure is not null) completion.TrySetException(failure);
            else completion.SetResult(actualDisposal!);
        }, null, Timeout.Infinite, Timeout.Infinite);
        try
        {
            Need(!completion.Task.IsCompleted); timer.Change(1, Timeout.Infinite);
            Task disposal = completion.Task.GetAwaiter().GetResult();
            disposal.GetAwaiter().GetResult();
            Need(entered == 1 && completed == 1 && closed == 1 && local.Value == "root");
            return "resource-late|dispose=pending|entered=1|completed=1|readers=2|binary=00ff80410d0a|text=1|empty=1|entropy=8|wall64=1|closed=1";
        }
        finally { timer.Dispose(); }
    }
}
