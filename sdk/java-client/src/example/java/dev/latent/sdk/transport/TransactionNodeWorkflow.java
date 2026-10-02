package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import dev.latent.sdk.TransactionClient;
import dev.latent.sdk.Transactions;
import com.google.protobuf.Message;
import java.nio.channels.Channels;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermission;
import java.time.Duration;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;

/** Finite actual SDK participant; input identities and keys convey no authority. */
public final class TransactionNodeWorkflow {
    private static final int MAXIMUM = 2 * 1024 * 1024;
    private static final Set<PosixFilePermission> PRIVATE = Set.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE);
    private static final ScheduledThreadPoolExecutor CANCEL = new ScheduledThreadPoolExecutor(1);
    private TransactionNodeWorkflow() { }

    private static void require(boolean value) { if (!value) throw new IllegalArgumentException("transaction-node-fixture-input"); }
    private static byte[] read(Path path, int maximum) throws Exception {
        require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) && PRIVATE.containsAll(Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS)));
        try (var channel = Files.newByteChannel(path, Set.of(StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)); var input = Channels.newInputStream(channel)) {
            byte[] bytes = input.readNBytes(maximum + 1); require(bytes.length <= maximum); return bytes;
        }
    }
    private static void write(Path path, byte[] bytes) throws Exception {
        require(bytes.length <= MAXIMUM);
        try (var output = Files.newByteChannel(path, Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE),
                java.nio.file.attribute.PosixFilePermissions.asFileAttribute(PRIVATE))) {
            var buffer = java.nio.ByteBuffer.wrap(bytes); while (buffer.hasRemaining()) output.write(buffer);
        }
    }
    private static String command() throws Exception {
        var bytes = new java.io.ByteArrayOutputStream(192);
        for (int count = 0; count <= 192; count++) {
            int value = System.in.read(); if (value == -1) return bytes.size() == 0 ? "close" : throwInput();
            if (value == '\n') return bytes.toString(StandardCharsets.US_ASCII);
            require(value >= 32 && value <= 126); bytes.write(value);
        }
        return throwInput();
    }
    private static String throwInput() { throw new IllegalArgumentException("fixture-command-bound"); }

    private record Reply(byte[] response, Optional<TransactionClient.ClientFailure> failure) { }
    private static <Response> Reply call(CompletableFuture<TransactionClient.ClientResponse<Response>> future,
            Function<Response, byte[]> encode, int cancellation) throws Exception {
        if (cancellation == 0) future.cancel(false);
        var timer = cancellation > 0 ? CANCEL.schedule(() -> future.cancel(false), cancellation, TimeUnit.MILLISECONDS) : null;
        try { return new Reply(encode.apply(future.get(6, TimeUnit.SECONDS).value()), Optional.empty()); }
        catch (Exception failure) {
            var observed = TransactionClient.clientFailure(failure);
            if (observed.isEmpty()) throw failure;
            return new Reply(null, observed);
        } finally { if (timer != null) timer.cancel(false); }
    }
    private static Reply dispatch(RpcClient client, String method, byte[] bytes, Management.CallOptions options, int cancel) throws Exception {
        return switch (method) {
                case "invoke_command" -> call(client.invokeCommand(TransactionWire.fromWire(latent.transaction.v1.Transaction.InvokeCommandRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "query" -> call(client.query(TransactionWire.fromWire(latent.transaction.v1.Transaction.QueryRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "lookup_command" -> call(client.lookupCommand(TransactionWire.fromWire(latent.transaction.v1.Transaction.LookupCommandRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "lookup_commit" -> call(client.lookupCommit(TransactionWire.fromWire(latent.transaction.v1.Transaction.LookupCommitRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "get_effect" -> call(client.getEffect(TransactionWire.fromWire(latent.transaction.v1.Transaction.GetEffectRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "list_effect_history" -> call(client.listEffectHistory(TransactionWire.fromWire(latent.transaction.v1.Transaction.ListEffectHistoryRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "cancel_command" -> call(client.cancelCommand(TransactionWire.fromWire(latent.transaction.v1.Transaction.CancelCommandRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "mutate_namespace" -> call(client.mutateNamespace(TransactionWire.fromWire(latent.control.v1.State.MutateNamespaceRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "inspect_namespace" -> call(client.inspectNamespace(TransactionWire.fromWire(latent.control.v1.State.InspectNamespaceRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "select_entity" -> call(client.selectEntity(TransactionWire.fromWire(latent.control.v1.State.SelectEntityRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "mutate_state" -> call(client.mutateState(TransactionWire.fromWire(latent.control.v1.State.MutateStateRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "plan_effect_mutation" -> call(client.planEffectMutation(TransactionWire.fromWire(latent.control.v1.State.PlanEffectMutationRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "get_state_operation_receipt" -> call(client.getStateOperationReceipt(TransactionWire.fromWire(latent.control.v1.State.GetStateOperationReceiptRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "inspect_dispatcher" -> call(client.inspectDispatcher(TransactionWire.fromWire(latent.control.v1.Dispatcher.InspectDispatcherRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "control_dispatcher" -> call(client.controlDispatcher(TransactionWire.fromWire(latent.control.v1.Dispatcher.ControlDispatcherRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
                case "get_dispatcher_operation" -> call(client.getDispatcherOperation(TransactionWire.fromWire(latent.control.v1.Dispatcher.GetDispatcherOperationRequest.parseFrom(bytes)), options), value -> TransactionWire.toWire(value).toByteArray(), cancel);
            default -> throw new IllegalArgumentException("fixture-method");
        };
    }

    private static void observations(Path directory, String id, Optional<TransactionClient.ObservedOutcome> observed) throws Exception {
        if (observed.isEmpty()) return;
        String kind; Message wire;
        switch (observed.get()) {
            case TransactionClient.ObservedOutcome.Command selected -> {
                var value = selected.command(); kind = "command";
                var model = new Transactions.CommandInspection(Optional.empty(), value.commandId(), value.attemptId(), value.fingerprintSha256(),
                    value.outcome(), value.metadataDurable(), value.applicationStateCommitted(), value.source(), Optional.empty(), Optional.empty(),
                    Optional.empty(), value.commit(), value.provenAbort(), value.retention(), Optional.empty());
                wire = TransactionWire.toWire(model);
            }
            case TransactionClient.ObservedOutcome.State selected -> { kind = "state"; wire = TransactionWire.toWire(selected.receipt()); }
            case TransactionClient.ObservedOutcome.Namespace selected -> { kind = "namespace"; wire = TransactionWire.toWire(selected.receipt()); }
            case TransactionClient.ObservedOutcome.Effect selected -> { kind = "effect"; wire = TransactionWire.toWire(selected.receipt()); }
            case TransactionClient.ObservedOutcome.Dispatcher selected -> { kind = "dispatcher"; wire = TransactionWire.toWire(selected.receipt()); }
            case TransactionClient.ObservedOutcome.EffectPlan selected -> { kind = "effectPlan"; wire = TransactionWire.toWire(selected.plan()); }
        }
        write(directory.resolve(id + "." + kind + ".pb"), wire.toByteArray());
    }

    private static boolean run(String[] args) throws Exception {
        require(args.length == 5 && args[0].equals("--node-fixture") && System.getProperty("os.name").equals("Linux"));
        Path directory = Path.of(args[4]).toAbsolutePath();
        require(Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS) && Set.of(PosixFilePermission.OWNER_READ,
            PosixFilePermission.OWNER_WRITE, PosixFilePermission.OWNER_EXECUTE).containsAll(Files.getPosixFilePermissions(directory)));
        byte[] credential = read(Path.of(args[3]), 256);
        require(credential.length >= 32);
        for (byte value : credential) require(value >= 33 && value <= 126);
        String token = new String(credential, StandardCharsets.US_ASCII); Arrays.fill(credential, (byte)0);
        var client = new RpcClient(new ClientConfig(args[1], args[2], token, 4, MAXIMUM, MAXIMUM, 5000, 2000, 5000));
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(120);
        Set<String> used = new HashSet<>();
        CANCEL.setRemoveOnCancelPolicy(true);
        boolean success = false;
        try {
            System.out.println("ready");
            while (true) {
                String line = command(); if (line.equals("close")) break;
                String[] values = line.split(" ", -1);
                require(values.length == 4 && values[1].matches("[A-Za-z0-9_-]{1,64}") && used.size() < 32 && used.add(values[1]));
                long timeout = Long.parseLong(values[2]); int cancel = Integer.parseInt(values[3]);
                long remaining = TimeUnit.NANOSECONDS.toMillis(deadline - System.nanoTime());
                require(timeout >= 1 && timeout <= 5000 && cancel >= -1 && cancel <= 5000 && remaining > 0);
                var options = new Management.CallOptions(Optional.of(Math.min(timeout, remaining)));
                Reply result = dispatch(client, values[0], read(directory.resolve(values[1] + ".request.pb"), MAXIMUM), options, cancel);
                String summary;
                if (result.failure().isEmpty()) {
                    write(directory.resolve(values[1] + ".response.pb"), result.response()); summary = "{\"status\":\"response\"}";
                } else {
                    var failure = result.failure().get(); observations(directory, values[1], failure.observed());
                    summary = "{\"status\":\"failure\",\"failureCategory\":" + failure.transport().category().value() +
                        ",\"grpcStatus\":" + failure.transport().grpcStatus().map(String::valueOf).orElse("null") +
                        ",\"dispatched\":" + failure.transport().dispatched() + "}";
                }
                write(directory.resolve(values[1] + ".result.json"), summary.getBytes(StandardCharsets.US_ASCII));
                System.out.println("done " + values[1]);
            }
            success = true;
        } finally {
            CANCEL.shutdownNow();
            var cleanup = client.shutdown(Duration.ofSeconds(5));
            boolean clean = cleanup.clean() && CANCEL.awaitTermination(5, TimeUnit.SECONDS);
            write(directory.resolve("cleanup.json"), ("{\"schemaVersion\":\"latent.sdk.transaction.node.cleanup.v1\",\"clean\":" + clean +
                ",\"activeCalls\":" + cleanup.activeCalls() + ",\"liveOwnedThreads\":" + cleanup.liveOwnedThreads() + "}").getBytes(StandardCharsets.US_ASCII));
            success &= clean;
        }
        return success;
    }
    public static void main(String[] args) {
        try { if (run(args)) return; } catch (Exception failure) { }
        CANCEL.shutdownNow(); System.err.println("transaction-node-workflow-failed"); System.exit(1);
    }
}
