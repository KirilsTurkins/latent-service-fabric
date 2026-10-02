using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Google.Protobuf;
using Profile = Latent.Sdk.Profile;
using Tx = Latent.Sdk.Transactions;
using WireControl = global::Latent.Control.V1;
using WireTransaction = global::Latent.Transaction.V1;

namespace Latent.Sdk.Transport.Tests;

internal static partial class Program
{
    private const int NodeMaximum = 2 * 1024 * 1024;
    private sealed record NodeResult(IMessage? Response, Tx.TransactionFailure? Failure);

    private static byte[] NodeRead(string path, int maximum)
    {
        if (!OperatingSystem.IsLinux()) throw new IOException("fixture-platform");
        var information = new FileInfo(path);
        if (!information.Exists || information.LinkTarget is not null || information.Length > maximum ||
            (File.GetUnixFileMode(path) & (UnixFileMode.GroupRead | UnixFileMode.GroupWrite | UnixFileMode.GroupExecute |
            UnixFileMode.OtherRead | UnixFileMode.OtherWrite | UnixFileMode.OtherExecute)) != 0)
            throw new IOException("fixture-private-file");
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        byte[] bytes = new byte[maximum + 1];
        int count = 0;
        while (count < bytes.Length)
        {
            int read = stream.Read(bytes, count, bytes.Length - count);
            if (read == 0) break;
            count += read;
        }
        if (count > maximum || count != information.Length || new FileInfo(path).LinkTarget is not null)
            throw new IOException("fixture-file-bound");
        return bytes[..count];
    }

    private static void NodeWrite(string directory, string name, byte[] bytes)
    {
        if (!OperatingSystem.IsLinux()) throw new IOException("fixture-platform");
        if (bytes.Length > NodeMaximum) throw new IOException("fixture-output-bound");
        using var output = new FileStream(Path.Combine(directory, name), new FileStreamOptions
        { Mode = FileMode.CreateNew, Access = FileAccess.Write, Share = FileShare.None, UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite });
        output.Write(bytes); output.Flush(flushToDisk: true);
    }

    private static async Task<NodeResult> NodeCall<Request, Response, WireRequest, WireResponse>(BoundedClient client,
        byte[] bytes, Profile.CallOptions options, CancellationToken token,
        Func<Request, Profile.CallOptions, CancellationToken, ValueTask<Tx.TransactionResponse<Response>>> dispatch)
        where Request : class where Response : class where WireRequest : IMessage, new() where WireResponse : IMessage, new()
    {
        var wire = new WireRequest(); wire.MergeFrom(bytes);
        var request = (Request)ProfileCodec.FromWire(wire, typeof(Request));
        try
        {
            var value = await dispatch(request, options, token);
            return new NodeResult(ProfileCodec.ToWire(value.Value, new WireResponse()), null);
        }
        catch (Tx.TransactionException failure) { return new NodeResult(null, failure.Failure); }
        catch (Tx.TransactionCancellationException failure) { return new NodeResult(null, failure.Failure); }
    }

    private static async Task<NodeResult> NodeDispatch(BoundedClient client, string method, byte[] bytes,
        Profile.CallOptions options, CancellationToken cancellationToken) => method switch
    {
            "invoke_command" => await NodeCall<Tx.InvokeCommandRequest, Tx.InvokeCommandResponse, WireTransaction.InvokeCommandRequest, WireTransaction.InvokeCommandResponse>(client, bytes, options, cancellationToken, client.InvokeCommandAsync),
            "query" => await NodeCall<Tx.QueryRequest, Tx.QueryResponse, WireTransaction.QueryRequest, WireTransaction.QueryResponse>(client, bytes, options, cancellationToken, client.QueryAsync),
            "lookup_command" => await NodeCall<Tx.LookupCommandRequest, Tx.LookupCommandResponse, WireTransaction.LookupCommandRequest, WireTransaction.LookupCommandResponse>(client, bytes, options, cancellationToken, client.LookupCommandAsync),
            "lookup_commit" => await NodeCall<Tx.LookupCommitRequest, Tx.LookupCommitResponse, WireTransaction.LookupCommitRequest, WireTransaction.LookupCommitResponse>(client, bytes, options, cancellationToken, client.LookupCommitAsync),
            "get_effect" => await NodeCall<Tx.GetEffectRequest, Tx.GetEffectResponse, WireTransaction.GetEffectRequest, WireTransaction.GetEffectResponse>(client, bytes, options, cancellationToken, client.GetEffectAsync),
            "list_effect_history" => await NodeCall<Tx.ListEffectHistoryRequest, Tx.ListEffectHistoryResponse, WireTransaction.ListEffectHistoryRequest, WireTransaction.ListEffectHistoryResponse>(client, bytes, options, cancellationToken, client.ListEffectHistoryAsync),
            "cancel_command" => await NodeCall<Tx.CancelCommandRequest, Tx.CancelCommandResponse, WireTransaction.CancelCommandRequest, WireTransaction.CancelCommandResponse>(client, bytes, options, cancellationToken, client.CancelCommandAsync),
            "mutate_namespace" => await NodeCall<Tx.MutateNamespaceRequest, Tx.MutateNamespaceResponse, WireControl.MutateNamespaceRequest, WireControl.MutateNamespaceResponse>(client, bytes, options, cancellationToken, client.MutateNamespaceAsync),
            "inspect_namespace" => await NodeCall<Tx.InspectNamespaceRequest, Tx.InspectNamespaceResponse, WireControl.InspectNamespaceRequest, WireControl.InspectNamespaceResponse>(client, bytes, options, cancellationToken, client.InspectNamespaceAsync),
            "select_entity" => await NodeCall<Tx.SelectEntityRequest, Tx.SelectEntityResponse, WireControl.SelectEntityRequest, WireControl.SelectEntityResponse>(client, bytes, options, cancellationToken, client.SelectEntityAsync),
            "mutate_state" => await NodeCall<Tx.MutateStateRequest, Tx.MutateStateResponse, WireControl.MutateStateRequest, WireControl.MutateStateResponse>(client, bytes, options, cancellationToken, client.MutateStateAsync),
            "plan_effect_mutation" => await NodeCall<Tx.PlanEffectMutationRequest, Tx.PlanEffectMutationResponse, WireControl.PlanEffectMutationRequest, WireControl.PlanEffectMutationResponse>(client, bytes, options, cancellationToken, client.PlanEffectMutationAsync),
            "get_state_operation_receipt" => await NodeCall<Tx.GetStateOperationReceiptRequest, Tx.GetStateOperationReceiptResponse, WireControl.GetStateOperationReceiptRequest, WireControl.GetStateOperationReceiptResponse>(client, bytes, options, cancellationToken, client.GetStateOperationReceiptAsync),
            "inspect_dispatcher" => await NodeCall<Tx.InspectDispatcherRequest, Tx.InspectDispatcherResponse, WireControl.InspectDispatcherRequest, WireControl.InspectDispatcherResponse>(client, bytes, options, cancellationToken, client.InspectDispatcherAsync),
            "control_dispatcher" => await NodeCall<Tx.ControlDispatcherRequest, Tx.ControlDispatcherResponse, WireControl.ControlDispatcherRequest, WireControl.ControlDispatcherResponse>(client, bytes, options, cancellationToken, client.ControlDispatcherAsync),
            "get_dispatcher_operation" => await NodeCall<Tx.GetDispatcherOperationRequest, Tx.GetDispatcherOperationResponse, WireControl.GetDispatcherOperationRequest, WireControl.GetDispatcherOperationResponse>(client, bytes, options, cancellationToken, client.GetDispatcherOperationAsync),
        _ => throw new FormatException("fixture-method")
    };

    private static void NodeObservations(string directory, string id, Tx.ObservedOutcome? observed)
    {
        if (observed is null) return;
        void Save(string kind, object? model, IMessage wire)
        {
            if (model is not null) NodeWrite(directory, id + "." + kind + ".pb", ProfileCodec.ToWire(model, wire).ToByteArray());
        }
        Save("command", observed.Command, new WireTransaction.CommandInspection());
        Save("state", observed.State, new WireControl.StateOperationReceipt());
        Save("namespace", observed.Namespace, new WireControl.NamespaceOperationReceipt());
        Save("effect", observed.Effect, new WireTransaction.EffectReceipt());
        Save("dispatcher", observed.Dispatcher, new WireControl.DispatcherOperationReceipt());
        Save("effectPlan", observed.EffectPlan, new WireControl.EffectManagementPlan());
    }

    private static async Task<int> TransactionNodeWorkflow(string[] args)
    {
        BoundedClient? client = null;
        string? directory = null;
        bool success = false;
        try
        {
            if (args.Length != 5 || args[0] != "--node-fixture" || !OperatingSystem.IsLinux()) throw new FormatException("fixture-arguments");
            directory = Path.GetFullPath(args[4]);
            var information = new DirectoryInfo(directory);
            if (!information.Exists || information.LinkTarget is not null || (File.GetUnixFileMode(directory) &
                (UnixFileMode.GroupRead | UnixFileMode.GroupWrite | UnixFileMode.GroupExecute | UnixFileMode.OtherRead |
                 UnixFileMode.OtherWrite | UnixFileMode.OtherExecute)) != 0) throw new IOException("fixture-directory");
            byte[] credential = NodeRead(args[3], 256);
            if (credential.Length < 32 || credential.Any(value => value < 33 || value > 126)) throw new FormatException("fixture-credential");
            string token = Encoding.ASCII.GetString(credential); Array.Clear(credential);
            using var lifetime = new CancellationTokenSource(TimeSpan.FromSeconds(120));
            long started = Stopwatch.GetTimestamp();
            client = await BoundedClient.ConnectAsync(new ClientOptions { Endpoint = args[1], BearerToken = token,
                MaxRequestBytes = NodeMaximum, MaxResponseBytes = NodeMaximum }, lifetime.Token);
            var used = new HashSet<string>(StringComparer.Ordinal);
            Console.WriteLine("ready");
            while (true)
            {
                // The fixture process owner bounds stdin and positively reaps this process.
                string? line = await Console.In.ReadLineAsync(lifetime.Token);
                if (line is null || line == "close") break;
                string[] values = line.Split(' ');
                if (line.Length > 192 || values.Length != 4 || !Regex.IsMatch(values[1], "^[A-Za-z0-9_-]{1,64}$") ||
                    used.Count >= 32 || !used.Add(values[1]) || !ulong.TryParse(values[2], out ulong timeout) || timeout is < 1 or > 5000 ||
                    !int.TryParse(values[3], out int cancel) || cancel is < -1 or > 5000) throw new FormatException("fixture-command");
                ulong remaining = (ulong)Math.Max(1, 120000 - Stopwatch.GetElapsedTime(started).TotalMilliseconds);
                lifetime.Token.ThrowIfCancellationRequested();
                byte[] bytes = NodeRead(Path.Combine(directory, values[1] + ".request.pb"), NodeMaximum);
                using var cancellation = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
                if (cancel == 0) cancellation.Cancel(); else if (cancel > 0) cancellation.CancelAfter(cancel);
                NodeResult result = await NodeDispatch(client, values[0], bytes, new Profile.CallOptions(Math.Min(timeout, remaining)), cancellation.Token);
                object summary;
                if (result.Failure is null)
                {
                    NodeWrite(directory, values[1] + ".response.pb", result.Response!.ToByteArray());
                    summary = new { status = "response" };
                }
                else
                {
                    NodeObservations(directory, values[1], result.Failure.Observed);
                    summary = new { status = "failure", failureCategory = result.Failure.Transport.Category.Value,
                        grpcStatus = result.Failure.Transport.GrpcStatus, dispatched = result.Failure.Transport.Dispatched };
                }
                NodeWrite(directory, values[1] + ".result.json", JsonSerializer.SerializeToUtf8Bytes(summary));
                Console.WriteLine("done " + values[1]);
            }
            success = true;
        }
        catch { Console.Error.WriteLine("transaction-node-workflow-failed"); }
        finally
        {
            if (client is not null && directory is not null)
            {
                bool shutdown = false;
                try { await client.DisposeAsync(); shutdown = true; } catch { success = false; }
                var usage = client.Snapshot();
                bool clean = shutdown && usage.Closed && usage.Reaped && usage.InFlight == 0 && usage.Queued == 0 && usage.WireStreams == 0;
                NodeWrite(directory, "cleanup.json", JsonSerializer.SerializeToUtf8Bytes(new
                { schemaVersion = "latent.sdk.transaction.node.cleanup.v1", clean, usage.InFlight, usage.Queued, usage.WireStreams, usage.Reaped }));
                success &= clean;
            }
        }
        return success ? 0 : 1;
    }
}
