package transport

// Explicit executable mode uses the real SDK/channel; default TestMain retains every test.
import (
    "bufio"
    "context"
    "encoding/json"
    "errors"
    "fmt"
    "io"
    "os"
    "path/filepath"
    "reflect"
    "regexp"
    "strconv"
    "strings"
    "testing"
    "time"
    "google.golang.org/protobuf/proto"
    "latent.dev/sdk/go/internal/rpc/statev1"
    "latent.dev/sdk/go/internal/rpc/transactionv1"
    "latent.dev/sdk/go/profile"
    tx "latent.dev/sdk/go/transaction"
    "syscall"
)

const nodeMaximum = 2 * 1024 * 1024
var nodeIdentifier = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

func nodeRead(path string, maximum int) ([]byte, error) {
    fd, failure := syscall.Open(path, syscall.O_RDONLY | syscall.O_NOFOLLOW | syscall.O_CLOEXEC, 0)
    if failure != nil { return nil, failure }
    file := os.NewFile(uintptr(fd), path)
    defer file.Close()
    information, failure := file.Stat()
    if failure != nil { return nil, failure }
    stat, valid := information.Sys().(*syscall.Stat_t)
    if !valid || !information.Mode().IsRegular() || stat.Uid != uint32(os.Getuid()) || information.Mode().Perm() & 077 != 0 || information.Size() > int64(maximum) { return nil, errBound }
    data := make([]byte, information.Size() + 1)
    count := 0
    for count < len(data) {
        size, failure := file.Read(data[count:]); count += size
        if failure != nil { if failure != io.EOF { return nil, failure }; break }
    }
    if count != int(information.Size()) { return nil, errBound }
    return data[:count], nil
}

func nodeWrite(path string, value []byte) error {
    if len(value) > nodeMaximum { return errBound }
    file, failure := os.OpenFile(path, os.O_WRONLY | os.O_CREATE | os.O_EXCL, 0600)
    if failure != nil { return failure }
    defer file.Close()
    if _, failure = file.Write(value); failure != nil { return failure }
    return file.Sync()
}

func nodeCall[Request any, Response any](client *Client, ctx context.Context, data []byte, options profile.CallOptions,
    wireRequest, wireResponse proto.Message, dispatch func(context.Context, Request, profile.CallOptions) (tx.ClientResponse[Response], error)) (proto.Message, *tx.ClientFailure, error) {
    nodes := 8192
    if failure := validateTransactionWire(context.Background(), data, wireRequest.ProtoReflect().Descriptor(), &nodes, 0); failure != nil { return nil, nil, failure }
    if failure := proto.Unmarshal(data, wireRequest); failure != nil { return nil, nil, failure }
    var request Request
    if failure := fromProto(wireRequest, &request); failure != nil { return nil, nil, failure }
    response, failure := dispatch(ctx, request, options)
    if failure != nil {
        var typed *tx.ClientFailure
        if !errors.As(failure, &typed) { return nil, nil, failure }
        return nil, typed, nil
    }
    if failure = toProto(response.Value, wireResponse); failure != nil { return nil, nil, failure }
    return wireResponse, nil, nil
}

func nodeDispatch(client *Client, ctx context.Context, method string, data []byte, options profile.CallOptions) (proto.Message, *tx.ClientFailure, error) {
    switch method {
    case "invoke_command":
        return nodeCall(client, ctx, data, options, &transactionv1.InvokeCommandRequest{}, &transactionv1.InvokeCommandResponse{}, client.InvokeCommand)
    case "query":
        return nodeCall(client, ctx, data, options, &transactionv1.QueryRequest{}, &transactionv1.QueryResponse{}, client.Query)
    case "lookup_command":
        return nodeCall(client, ctx, data, options, &transactionv1.LookupCommandRequest{}, &transactionv1.LookupCommandResponse{}, client.LookupCommand)
    case "lookup_commit":
        return nodeCall(client, ctx, data, options, &transactionv1.LookupCommitRequest{}, &transactionv1.LookupCommitResponse{}, client.LookupCommit)
    case "get_effect":
        return nodeCall(client, ctx, data, options, &transactionv1.GetEffectRequest{}, &transactionv1.GetEffectResponse{}, client.GetEffect)
    case "list_effect_history":
        return nodeCall(client, ctx, data, options, &transactionv1.ListEffectHistoryRequest{}, &transactionv1.ListEffectHistoryResponse{}, client.ListEffectHistory)
    case "cancel_command":
        return nodeCall(client, ctx, data, options, &transactionv1.CancelCommandRequest{}, &transactionv1.CancelCommandResponse{}, client.CancelCommand)
    case "mutate_namespace":
        return nodeCall(client, ctx, data, options, &statev1.MutateNamespaceRequest{}, &statev1.MutateNamespaceResponse{}, client.MutateNamespace)
    case "inspect_namespace":
        return nodeCall(client, ctx, data, options, &statev1.InspectNamespaceRequest{}, &statev1.InspectNamespaceResponse{}, client.InspectNamespace)
    case "select_entity":
        return nodeCall(client, ctx, data, options, &statev1.SelectEntityRequest{}, &statev1.SelectEntityResponse{}, client.SelectEntity)
    case "mutate_state":
        return nodeCall(client, ctx, data, options, &statev1.MutateStateRequest{}, &statev1.MutateStateResponse{}, client.MutateState)
    case "plan_effect_mutation":
        return nodeCall(client, ctx, data, options, &statev1.PlanEffectMutationRequest{}, &statev1.PlanEffectMutationResponse{}, client.PlanEffectMutation)
    case "get_state_operation_receipt":
        return nodeCall(client, ctx, data, options, &statev1.GetStateOperationReceiptRequest{}, &statev1.GetStateOperationReceiptResponse{}, client.GetStateOperationReceipt)
    case "inspect_dispatcher":
        return nodeCall(client, ctx, data, options, &statev1.InspectDispatcherRequest{}, &statev1.InspectDispatcherResponse{}, client.InspectDispatcher)
    case "control_dispatcher":
        return nodeCall(client, ctx, data, options, &statev1.ControlDispatcherRequest{}, &statev1.ControlDispatcherResponse{}, client.ControlDispatcher)
    case "get_dispatcher_operation":
        return nodeCall(client, ctx, data, options, &statev1.GetDispatcherOperationRequest{}, &statev1.GetDispatcherOperationResponse{}, client.GetDispatcherOperation)
    default: return nil, nil, errShape
    }
}

func nodeObservations(directory, id string, observed *tx.ObservedOutcome) error {
    if observed == nil { return nil }
    values := []struct {kind string; model any; wire proto.Message}{
        {"command", observed.Command, &transactionv1.CommandInspection{}},
        {"state", observed.State, &statev1.StateOperationReceipt{}},
        {"namespace", observed.Namespace, &statev1.NamespaceOperationReceipt{}},
        {"effect", observed.Effect, &transactionv1.EffectReceipt{}},
        {"dispatcher", observed.Dispatcher, &statev1.DispatcherOperationReceipt{}},
        {"effectPlan", observed.EffectPlan, &statev1.EffectManagementPlan{}},
    }
    for _, value := range values {
        if reflectNil(value.model) { continue }
        if failure := toProto(value.model, value.wire); failure != nil { return failure }
        encoded, failure := proto.Marshal(value.wire); if failure != nil { return failure }
        if failure = nodeWrite(filepath.Join(directory, id + "." + value.kind + ".pb"), encoded); failure != nil { return failure }
    }
    return nil
}

func reflectNil(value any) bool { return value == nil || reflect.ValueOf(value).IsNil() }

func nodeWorkflow(args []string) (success bool) {
    if len(args) != 5 || args[0] != "--node-fixture" { return false }
    directory, failure := filepath.Abs(args[4]); if failure != nil { return false }
    info, failure := os.Lstat(directory); if failure != nil || !info.IsDir() || info.Mode().Perm() & 077 != 0 { return false }
    stat, valid := info.Sys().(*syscall.Stat_t); if !valid || stat.Uid != uint32(os.Getuid()) { return false }
    token, failure := nodeRead(args[3], 256); if failure != nil { return false }
    config := DefaultConfig(args[1], string(token)); clear(token)
    config.MaxRequestBytes, config.MaxResponseBytes = nodeMaximum, nodeMaximum
    ctx, retire := context.WithTimeout(context.Background(), 120 * time.Second)
    defer retire()
    client, failure := New(ctx, config); if failure != nil { return false }
    defer func() {
        clean := client.Close() == nil && client.socket.inFlight() == 0
        client.mutex.Lock(); clean = clean && client.closed && client.active == 0 && client.queued == 0; client.mutex.Unlock()
        encoded, _ := json.Marshal(map[string]any{"schemaVersion":"latent.sdk.transaction.node.cleanup.v1", "clean":clean})
        if nodeWrite(filepath.Join(directory, "cleanup.json"), encoded) != nil || !clean { success = false }
    }()
    fmt.Println("ready")
    used := make(map[string]bool)
    scanner := bufio.NewScanner(os.Stdin); scanner.Buffer(make([]byte, 193), 193)
    for scanner.Scan() {
        if scanner.Text() == "close" { return true }
        values := strings.Split(scanner.Text(), " ")
        if len(values) != 4 || !nodeIdentifier.MatchString(values[1]) || len(used) >= 32 || used[values[1]] || ctx.Err() != nil { return false }
        used[values[1]] = true
        timeout, err := strconv.ParseUint(values[2], 10, 64); if err != nil || timeout < 1 || timeout > 5000 { return false }
        cancellation, err := strconv.ParseInt(values[3], 10, 64); if err != nil || cancellation < -1 || cancellation > 5000 { return false }
        data, err := nodeRead(filepath.Join(directory, values[1]+".request.pb"), nodeMaximum); if err != nil { return false }
        call, cancel := context.WithCancel(ctx)
        var timer *time.Timer
        timerDone := make(chan struct{})
        if cancellation == 0 { cancel() } else if cancellation > 0 {
            timer = time.AfterFunc(time.Duration(cancellation)*time.Millisecond, func() { cancel(); close(timerDone) })
        }
        response, typed, err := nodeDispatch(client, call, values[0], data, profile.CallOptions{TimeoutMillis: &timeout})
        cancel(); if timer != nil && !timer.Stop() { <-timerDone }
        if err != nil { return false }
        result := map[string]any{"status":"response"}
        if typed == nil {
            encoded, err := proto.Marshal(response); if err != nil { return false }
            if nodeWrite(filepath.Join(directory, values[1]+".response.pb"), encoded) != nil { return false }
        } else {
            result = map[string]any{"status":"failure", "failureCategory":typed.Transport.Category, "grpcStatus":typed.Transport.GrpcStatus, "dispatched":typed.Transport.Dispatched}
            if nodeObservations(directory, values[1], typed.Observed) != nil { return false }
        }
        encoded, err := json.Marshal(result); if err != nil || nodeWrite(filepath.Join(directory, values[1]+".result.json"), encoded) != nil { return false }
        fmt.Println("done " + values[1])
    }
    return scanner.Err() == nil && ctx.Err() == nil
}

func TestMain(main *testing.M) {
    if len(os.Args) > 1 && os.Args[1] == "--node-fixture" {
        if nodeWorkflow(os.Args[1:]) { os.Exit(0) }
        fmt.Fprintln(os.Stderr, "transaction-node-workflow-failed"); os.Exit(1)
    }
    os.Exit(main.Run())
}
