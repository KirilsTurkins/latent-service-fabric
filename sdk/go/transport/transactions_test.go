package transport

import (
    "bytes"
    "context"
    "errors"
    "math"
    "net/http"
    "strings"
    "strconv"
    "sync/atomic"
    "testing"
    "time"
    "google.golang.org/protobuf/proto"
    "google.golang.org/protobuf/encoding/protowire"
    "latent.dev/sdk/go/internal/rpc/controlv1"
    "latent.dev/sdk/go/internal/rpc/transactionv1"
    "latent.dev/sdk/go/profile"
    tx "latent.dev/sdk/go/transaction"
)

func transactionFixtures() (tx.NamespaceSelector,tx.CommandSelector,tx.InspectNamespaceRequest) {
    namespace:=tx.NamespaceSelector{Tenant:"tenant-a",Namespace:"transactional-aggregate",Incarnation:"1"}
    command:=tx.CommandSelector{Namespace:&namespace,Operation:"update",Entity:pointer("aggregate-a"),ClientKey:"business-key-a"}
    inspect:=tx.InspectNamespaceRequest{Profile:pointer(tx.CurrentProfile()),Namespace:&namespace,AuthorizationPublication:&profile.PublicationRef{Id:"publication:sha256:"+strings.Repeat("b",64),Tenant:namespace.Tenant}}
    return namespace,command,inspect
}
func transactionInvokeFixture() tx.InvokeCommandRequest {
    _,command,_:=transactionFixtures(); invocation:=invokeRequest("activation-a")
    return tx.InvokeCommandRequest{Profile:pointer(tx.CurrentProfile()),Invocation:&invocation,Command:&command,InputFormat:"aggregate-input-v1",
        ExpectedVersions:[]tx.ExpectedVersion{{Key:[]byte{0,255},Version:pointer([]byte{1})}}}
}
func transactionLookupFixture(attempt *string) tx.LookupCommandRequest {
    _,command,inspect:=transactionFixtures(); return tx.LookupCommandRequest{Profile:inspect.Profile,Command:&command,AttemptId:attempt,AuthorizationPublication:inspect.AuthorizationPublication}
}
func transactionSourceFixture() *tx.SourceIdentity {
    digest:="sha256:"+strings.Repeat("a",64)
    return &tx.SourceIdentity{PublicationId:"publication:sha256:"+strings.Repeat("b",64),RevisionId:"revision-a",ReleaseDigest:digest,ComponentDigest:digest,ContractDigest:digest,
        StateSchema:digest,RouteGeneration:math.MaxUint64,InputFormat:"aggregate-input-v1",ResultFormat:"aggregate-result-v1"}
}
func transactionCommandFixture(outcome tx.CommandOutcome,payload bool) *tx.CommandInspection {
    namespace,command,_:=transactionFixtures(); source:=transactionSourceFixture()
    result:=&tx.CommandInspection{Key:&tx.CommandKey{Namespace:&namespace,RecoveryScope:"caller:subject-a",Operation:command.Operation,Entity:command.Entity,ClientKey:command.ClientKey},
        CommandId:"command-a",AttemptId:"attempt-a",FingerprintSha256:make([]byte,32),Outcome:outcome,MetadataDurable:true,ApplicationStateCommitted:outcome==tx.CommandOutcomeCommitted,Source:source,
        Retention:&tx.LinkedRetention{RecordFormat:"command-v1",RecordVersion:1,PayloadAvailable:payload,RequiredRecordIds:[]string{"command-a"},RemainingRecoveryMillis:pointer(uint64(math.MaxUint64))}}
    switch outcome {
    case tx.CommandOutcomeCommitted:
        if payload { result.Success=&profile.Success{Payload:[]byte{0,255},MediaType:"application/octet-stream"} }
        result.Commit=&tx.CommitReceipt{CommandId:result.CommandId,AttemptId:result.AttemptId,TransactionId:"transaction-a",ReceiptId:"receipt-a",CommittedVersion:[]byte{1},CommittedAtUnixMillis:math.MaxUint64,Source:source,EffectIds:[]string{"effect-a"}}
    case tx.CommandOutcomeRejected:
        if payload { result.BusinessRejection=&profile.DeclaredError{Code:"business-rejected",Message:"expected rejection",Payload:[]byte{0,255},MediaType:"application/octet-stream"} }
    case tx.CommandOutcomeAborted:
        result.TechnicalFailure=&profile.PlatformError{Code:"cancelled",Message:"physical owner retired"}
        result.ProvenAbort=&tx.AbortFence{CommandId:result.CommandId,AttemptId:result.AttemptId,TransactionId:"transaction-a",OwnerFence:[]byte{1,2}}
    }
    return result
}
func transactionInvocationFixture(test *testing.T,command *tx.CommandInspection) *profile.InvokeResponse {
    test.Helper(); value:=&profile.InvokeResponse{}
    if fromProto(successWire("activation-a"),value)!=nil { test.Fatal("controlled invocation fixture conversion failed") }
    value.Success=command.Success; value.DeclaredError=command.BusinessRejection; value.PlatformFailure=command.TechnicalFailure
    return value
}
func transactionEffectFixture() tx.EffectReceipt {
    return tx.EffectReceipt{EffectId:"effect-a",CommandId:"command-a",CommandAttemptId:"attempt-a",ProviderProfile:"approved-provider-v1",DispatchAttempt:1,
        Disposition:tx.EffectDispositionProviderAcknowledged,ProviderReceipt:pointer("provider-receipt-a"),OccurredAtUnixMillis:math.MaxUint64}
}
func transactionWireFixture[Message proto.Message](test *testing.T,value any,message Message) Message {
    test.Helper(); if failure:=toProto(value,message);failure!=nil { test.Fatal(failure) }; return message
}
func transactionFailureFixture(test *testing.T,failure error,category profile.FailureCategory) *tx.ClientFailure {
    test.Helper(); var result *tx.ClientFailure
    if !errors.As(failure,&result)||result.Transport.Category!=category { test.Fatalf("expected independent transaction failure %d: %v",category,failure) }; return result
}

// Real HTTP/2 serialization peers, independent of the signed-node acceptance gate.
func TestTransactionTwelveOperationsUseOneOwnedChannel(test *testing.T) {
    namespace,command,inspect:=transactionFixtures(); digest:=transactionSourceFixture().StateSchema
    peer:=newPeer(test,func(writer http.ResponseWriter,request *http.Request) {
        switch request.URL.Path[strings.LastIndex(request.URL.Path,"/")+1:] {
        case "InvokeCommand":
            wire:=&transactionv1.InvokeCommandRequest{}; decodePeerRequest(test,request,wire)
            if wire.Command.ClientKey!="business-key-a"||!bytes.Equal(wire.ExpectedVersions[0].GetVersion(),[]byte{1}) { test.Error("original command or stale-edit precondition changed") }
            result:=transactionCommandFixture(tx.CommandOutcomeCommitted,true); result.Success.Payload=make([]byte,750*1024)
            peerReply(writer,transactionWireFixture(test,tx.InvokeCommandResponse{Invocation:transactionInvocationFixture(test,result),Command:result},&transactionv1.InvokeCommandResponse{}))
        case "Query":
            decodePeerRequest(test,request,&transactionv1.QueryRequest{}); result:=transactionCommandFixture(tx.CommandOutcomeCommitted,true)
            peerReply(writer,transactionWireFixture(test,tx.QueryResponse{Invocation:transactionInvocationFixture(test,result),Source:result.Source,View:&tx.ViewIdentity{Namespace:&namespace,Version:[]byte{1},StateSchema:digest},ObservedAtUnixMillis:math.MaxUint64},&transactionv1.QueryResponse{}))
        case "LookupCommand": decodePeerRequest(test,request,&transactionv1.LookupCommandRequest{}); peerReply(writer,transactionWireFixture(test,tx.LookupCommandResponse{Command:transactionCommandFixture(tx.CommandOutcomeCommitted,true)},&transactionv1.LookupCommandResponse{}))
        case "LookupCommit": decodePeerRequest(test,request,&transactionv1.LookupCommitRequest{}); peerReply(writer,transactionWireFixture(test,tx.LookupCommitResponse{Command:transactionCommandFixture(tx.CommandOutcomeCommitted,true)},&transactionv1.LookupCommitResponse{}))
        case "GetEffect": decodePeerRequest(test,request,&transactionv1.GetEffectRequest{}); peerReply(writer,transactionWireFixture(test,tx.GetEffectResponse{Effect:pointer(transactionEffectFixture())},&transactionv1.GetEffectResponse{}))
        case "ListEffectHistory":
            decodePeerRequest(test,request,&transactionv1.ListEffectHistoryRequest{}); peerReply(writer,transactionWireFixture(test,tx.ListEffectHistoryResponse{Receipts:[]tx.EffectReceipt{transactionEffectFixture()},Page:&tx.PageResponse{NextCursor:pointer([]byte{1}),ReturnedCount:1,EncodedBytes:128}},&transactionv1.ListEffectHistoryResponse{}))
        case "CancelCommand": decodePeerRequest(test,request,&transactionv1.CancelCommandRequest{}); peerReply(writer,transactionWireFixture(test,tx.CancelCommandResponse{Disposition:tx.CommandCancelDispositionAlreadyCommitted,Command:transactionCommandFixture(tx.CommandOutcomeCommitted,true)},&transactionv1.CancelCommandResponse{}))
        case "InspectNamespace":
            decodePeerRequest(test,request,&controlv1.InspectNamespaceRequest{}); peerReply(writer,transactionWireFixture(test,tx.InspectNamespaceResponse{Namespace:&tx.NamespaceInspection{View:&tx.ViewIdentity{Namespace:&namespace,Version:[]byte{1},StateSchema:digest},Status:tx.NamespaceStatusActive,
                EngineProfile:"redb-v1",EngineProfileDigest:digest,Generation:math.MaxUint64,Quota:&tx.NamespaceQuota{StateKeys:1,StateBytes:4096,ResultRows:1,ResultBytes:4096,EffectRows:1,EffectBytes:4096,PayloadBytes:4096,RecoveryBytes:4096}}},&controlv1.InspectNamespaceResponse{}))
        case "SelectEntity":
            decodePeerRequest(test,request,&controlv1.SelectEntityRequest{}); peerReply(writer,transactionWireFixture(test,tx.SelectEntityResponse{Entities:[]tx.EntityInspection{{Entity:"aggregate-a",Version:[]byte{1}}},Page:&tx.PageResponse{NextCursor:pointer([]byte{2}),ReturnedCount:1,EncodedBytes:32}},&controlv1.SelectEntityResponse{}))
        case "MutateState":
            wire:=&controlv1.MutateStateRequest{}; decodePeerRequest(test,request,wire)
            peerReply(writer,transactionWireFixture(test,tx.MutateStateResponse{Receipt:&tx.StateOperationReceipt{OperationId:wire.OperationId,ReceiptId:"state-receipt-a",Mutation:tx.StateMutationKindCheckpointNamespace,Namespace:&namespace,AuthenticatedOperator:"operator-a",BeforeVersion:[]byte{1},AfterVersion:[]byte{2},CompletedAtUnixMillis:math.MaxUint64,PolicyDigest:digest,Disposition:tx.StateOperationDispositionCommitted},AuditAck:&profile.AuditAck{Status:profile.AuditAckStatusDurable,AttemptSequence:pointer(uint64(math.MaxUint64))}},&controlv1.MutateStateResponse{}))
        case "MutateNamespace":
            wire:=&controlv1.MutateNamespaceRequest{}; decodePeerRequest(test,request,wire); if wire.ExpectedGeneration==nil||*wire.ExpectedGeneration!=math.MaxUint64-1 { test.Error("namespace original generation/presence narrowed") }
            peerReply(writer,transactionWireFixture(test,tx.MutateNamespaceResponse{Receipt:&tx.NamespaceOperationReceipt{OperationId:wire.OperationId,ReceiptId:"namespace-receipt-a",Mutation:tx.NamespaceMutationKindQuiesce,Namespace:&namespace,AuthenticatedOperator:"operator-a",BeforeGeneration:pointer(uint64(math.MaxUint64-1)),AfterGeneration:math.MaxUint64,Status:tx.NamespaceStatusQuiescing,StateSchema:digest,Disposition:tx.StateOperationDispositionCommitted}},&controlv1.MutateNamespaceResponse{}))
        case "GetStateOperationReceipt":
            decodePeerRequest(test,request,&controlv1.GetStateOperationReceiptRequest{}); peerReply(writer,transactionWireFixture(test,tx.GetStateOperationReceiptResponse{Receipt:&tx.StateOperationReceipt{OperationId:"state-operation-a",ReceiptId:"state-receipt-a",Mutation:tx.StateMutationKindCheckpointNamespace,Namespace:&namespace,AuthenticatedOperator:"operator-a",BeforeVersion:[]byte{1},AfterVersion:[]byte{2},PolicyDigest:digest,Disposition:tx.StateOperationDispositionCommitted}},&controlv1.GetStateOperationReceiptResponse{}))
        default: test.Error("unexpected transaction operation")
        }
    })
    client:=testClient(test,peer,func(config *Config) { config.MaxResponseBytes=2*1024*1024 }); ctx:=context.Background(); options:=profile.CallOptions{}
    invoked,failure:=client.InvokeCommand(ctx,transactionInvokeFixture(),options); if failure!=nil { test.Fatal(failure) }
    if invoked.Metadata.Observed.Command.Success!=nil||invoked.Metadata.Observed.Command.Commit.ReceiptId!="receipt-a"||len(invoked.Value.Invocation.Success.Payload)!=750*1024||len(invoked.Value.Command.Success.Payload)!=750*1024 { test.Fatal("bounded result bodies or independent receipt ownership changed") }
    query,failure:=client.Query(ctx,tx.QueryRequest{Profile:inspect.Profile,Invocation:pointer(invokeRequest("activation-a")),Namespace:&namespace,MinimumViewVersion:pointer([]byte{1})},options)
    if failure!=nil||query.Metadata.Observed!=nil||query.Value.ObservedAtUnixMillis!=math.MaxUint64 { test.Fatal("fresh query acquired durable command knowledge",failure) }
    if _,failure=client.LookupCommand(ctx,transactionLookupFixture(nil),options);failure!=nil { test.Fatal(failure) }
    if _,failure=client.LookupCommit(ctx,tx.LookupCommitRequest{Profile:inspect.Profile,Command:&command,ReceiptId:"receipt-a",AuthorizationPublication:inspect.AuthorizationPublication},options);failure!=nil { test.Fatal(failure) }
    effect:=tx.GetEffectRequest{Profile:inspect.Profile,Command:&command,EffectId:"effect-a",AuthorizationPublication:inspect.AuthorizationPublication}
    if result,invalid:=client.GetEffect(ctx,effect,options);invalid!=nil||result.Value.Effect.OccurredAtUnixMillis!=math.MaxUint64 { test.Fatal("effect timestamp narrowed",invalid) }
    if result,invalid:=client.ListEffectHistory(ctx,tx.ListEffectHistoryRequest{Effect:&effect,Page:&tx.PageRequest{Limit:16}},options);invalid!=nil||len(result.Value.Receipts)!=1||result.Value.Page.NextCursor==nil { test.Fatal("short history page auto-drained or lost cursor",invalid) }
    if _,failure=client.CancelCommand(ctx,tx.CancelCommandRequest{Command:pointer(transactionLookupFixture(nil)),Reason:"logical cancellation"},options);failure!=nil { test.Fatal(failure) }
    if result,invalid:=client.InspectNamespace(ctx,inspect,options);invalid!=nil||result.Value.Namespace.Generation!=math.MaxUint64 { test.Fatal("namespace generation narrowed",invalid) }
    if result,invalid:=client.SelectEntity(ctx,tx.SelectEntityRequest{Namespace:&inspect,Page:&tx.PageRequest{Limit:16}},options);invalid!=nil||result.Value.Page.NextCursor==nil { test.Fatal("entity page lost authoritative continuation",invalid) }
    if result,invalid:=client.MutateState(ctx,tx.MutateStateRequest{Namespace:&inspect,OperationId:"state-operation-a",Mutation:tx.StateMutationKindCheckpointNamespace,ExpectedVersion:[]byte{1},ExpectedPolicyDigest:digest,Reason:"checkpoint"},options);invalid!=nil||*result.Value.AuditAck.AttemptSequence!=math.MaxUint64 { test.Fatal("state receipt/audit facts changed",invalid) }
    lifecycle,failure:=client.MutateNamespace(ctx,tx.MutateNamespaceRequest{Namespace:&inspect,OperationId:"namespace-operation-a",Mutation:tx.NamespaceMutationKindQuiesce,ExpectedGeneration:pointer(uint64(math.MaxUint64-1))},options)
    if failure!=nil||lifecycle.Metadata.Identity.ExpectedGeneration==nil||*lifecycle.Metadata.Identity.ExpectedGeneration!=math.MaxUint64-1||lifecycle.Value.Receipt.AfterGeneration!=math.MaxUint64 { test.Fatal("lifecycle original precondition refreshed",failure) }
    if _,failure=client.GetStateOperationReceipt(ctx,tx.GetStateOperationReceiptRequest{Namespace:&inspect,OperationId:"state-operation-a"},options);failure!=nil { test.Fatal(failure) }
    if peer.requests.Load()!=12||peer.accepted.Load()!=1 { test.Fatal("twelve calls resubmitted or replaced the owned connection") }
}

func TestTransactionDurableRejectionSurvivesAuditFailure(test *testing.T) {
    peer:=newPeer(test,func(writer http.ResponseWriter,request *http.Request) {
        decodePeerRequest(test,request,&transactionv1.InvokeCommandRequest{}); command:=transactionCommandFixture(tx.CommandOutcomeRejected,true)
        writer.Header().Set("latent-audit-attempt","not-an-integer")
        peerReply(writer,transactionWireFixture(test,tx.InvokeCommandResponse{Invocation:transactionInvocationFixture(test,command),Command:command},&transactionv1.InvokeCommandResponse{}))
    }); client:=testClient(test,peer)
    _,invalid:=client.InvokeCommand(context.Background(),transactionInvokeFixture(),profile.CallOptions{})
    failure:=transactionFailureFixture(test,invalid,profile.FailureCategoryDecode)
    if failure.Transport.Outcome!=profile.OutcomeKnowledgeObserved||failure.Observed==nil||failure.Observed.Command.Outcome!=tx.CommandOutcomeRejected||failure.Observed.Command.ApplicationStateCommitted||failure.Observed.Command.BusinessRejection!=nil||failure.Observed.Command.ProvenAbort!=nil||!bytes.Equal(*failure.Identity.ExpectedVersions[0].Version,[]byte{1})||peer.requests.Load()!=1 { test.Fatal("later audit failure erased rejection or fabricated abort/retry") }
}
func TestTransactionTransportAbortedNeverAuthorizesAttempt(test *testing.T) {
    var submissions atomic.Int32
    peer:=newPeer(test,func(writer http.ResponseWriter,request *http.Request) {
        if strings.HasSuffix(request.URL.Path,"/LookupCommand") { decodePeerRequest(test,request,&transactionv1.LookupCommandRequest{}); peerReply(writer,transactionWireFixture(test,tx.LookupCommandResponse{Command:transactionCommandFixture(tx.CommandOutcomeAborted,true)},&transactionv1.LookupCommandResponse{})); return }
        wire:=&transactionv1.InvokeCommandRequest{}; decodePeerRequest(test,request,wire)
        if submissions.Add(1)==1 { peerFailure(writer,"10"); return }
        if wire.RetryAttempt==nil||wire.RetryAttempt.RequestId!="explicit-retry-a"||!bytes.Equal(wire.RetryAttempt.ExpectedAbort.OwnerFence,[]byte{1,2}) { test.Error("explicit attempt lost its original proven fence") }
        command:=transactionCommandFixture(tx.CommandOutcomeCommitted,true); peerReply(writer,transactionWireFixture(test,tx.InvokeCommandResponse{Invocation:transactionInvocationFixture(test,command),Command:command},&transactionv1.InvokeCommandResponse{}))
    }); client:=testClient(test,peer); ctx:=context.Background()
    _,invalid:=client.InvokeCommand(ctx,transactionInvokeFixture(),profile.CallOptions{}); failure:=transactionFailureFixture(test,invalid,profile.FailureCategoryRpc)
    if failure.Transport.GrpcStatus==nil||*failure.Transport.GrpcStatus!=10||failure.Transport.Outcome!=profile.OutcomeKnowledgeUnknown||failure.Observed!=nil||submissions.Load()!=1 { test.Fatal("gRPC ABORTED supplied durable proof or automatically resubmitted") }
    aborted,invalid:=client.LookupCommand(ctx,transactionLookupFixture(nil),profile.CallOptions{}); if invalid!=nil||aborted.Value.Command.ProvenAbort==nil { test.Fatal("durable abort fence not retained",invalid) }
    explicit:=transactionInvokeFixture(); explicit.RetryAttempt=&tx.RetryAttempt{RequestId:"explicit-retry-a",ExpectedAbort:aborted.Value.Command.ProvenAbort}
    committed,invalid:=client.InvokeCommand(ctx,explicit,profile.CallOptions{}); if invalid!=nil||committed.Metadata.Identity.AttemptId==nil||*committed.Metadata.Identity.AttemptId!="attempt-a"||submissions.Load()!=2 { test.Fatal("explicit attempt changed original attempt identity",invalid) }
}
func TestTransactionPredecodeAndRetainedOldFormats(test *testing.T) {
    peer:=newPeer(test,func(writer http.ResponseWriter,request *http.Request) {
        wire:=&transactionv1.LookupCommandRequest{}; decodePeerRequest(test,request,wire); command:=transactionCommandFixture(tx.CommandOutcomeCommitted,false)
        command.Retention.RecordFormat="retained-original-format"; command.Retention.RecordVersion=7
        command.Retention.RequiredRecordIds=nil; for i:=0;i<256;i++ { command.Retention.RequiredRecordIds=append(command.Retention.RequiredRecordIds,"linked-"+strconvForTest(i)) }
        if wire.AttemptId!=nil&&*wire.AttemptId=="future" { command.Outcome=tx.CommandOutcome(91) }
        payload,invalid:=proto.Marshal(transactionWireFixture(test,tx.LookupCommandResponse{Command:command},&transactionv1.LookupCommandResponse{})); if invalid!=nil { test.Error(invalid) }
        if wire.AttemptId!=nil&&*wire.AttemptId=="duplicate" { payload=append(payload,payload...) }; peerBytes(writer,frame(payload),"0")
    }); client:=testClient(test,peer); ctx:=context.Background()
    original,invalid:=client.LookupCommand(ctx,transactionLookupFixture(nil),profile.CallOptions{}); if invalid!=nil||len(original.Value.Command.Retention.RequiredRecordIds)!=256||original.Value.Command.Retention.RecordVersion!=7||original.Value.Command.Success!=nil||original.Metadata.Observed.Command.Commit==nil { test.Fatal("expiry erased retained original receipt",invalid) }
    _,invalid=client.LookupCommand(ctx,transactionLookupFixture(pointer("future")),profile.CallOptions{}); future:=transactionFailureFixture(test,invalid,profile.FailureCategoryDecode)
    if future.Transport.UnsupportedWireValue==nil||future.Transport.UnsupportedWireValue.Value!="91"||future.Observed!=nil { test.Fatal("unknown future enum was collapsed or treated as receipt") }
    _,invalid=client.LookupCommand(ctx,transactionLookupFixture(pointer("duplicate")),profile.CallOptions{}); duplicate:=transactionFailureFixture(test,invalid,profile.FailureCategoryDecode); if duplicate.Observed!=nil { test.Fatal("duplicate field supplied durable knowledge") }
    records:=[]byte{}; for i:=0;i<129;i++ { records=protowire.AppendTag(records,1,protowire.BytesType); records=protowire.AppendBytes(records,nil) }
    nodes:=4096; if validateTransactionWire(ctx,records,(&transactionv1.ListEffectHistoryResponse{}).ProtoReflect().Descriptor(),&nodes,0)!=errBound { test.Fatal("empty-record expansion passed native predecode") }
}
func strconvForTest(value int) string { return strconv.FormatInt(int64(value),10) }
func TestTransactionCancellationKeepsOriginalInputsForExplicitRecovery(test *testing.T) {
    seen:=make(chan struct{})
    peer:=newPeer(test,func(writer http.ResponseWriter,request *http.Request) {
        if strings.HasSuffix(request.URL.Path,"/InvokeCommand") { decodePeerRequest(test,request,&transactionv1.InvokeCommandRequest{}); close(seen); <-request.Context().Done(); return }
        decodePeerRequest(test,request,&transactionv1.LookupCommandRequest{}); peerReply(writer,transactionWireFixture(test,tx.LookupCommandResponse{Command:transactionCommandFixture(tx.CommandOutcomeCommitted,true)},&transactionv1.LookupCommandResponse{}))
    }); client:=testClient(test,peer); original:=transactionInvokeFixture(); ctx,stop:=context.WithCancel(context.Background()); defer stop()
    finished:=make(chan error,1); go func() { _,invalid:=client.InvokeCommand(ctx,original,profile.CallOptions{}); finished<-invalid }()
    select { case <-seen: case <-time.After(2*time.Second): test.Fatal("controlled command did not dispatch") }
    (*original.ExpectedVersions[0].Version)[0]=9; stop()
    var invalid error; select { case invalid=<-finished: case <-time.After(2*time.Second): test.Fatal("local cancellation did not settle") }
    failure:=transactionFailureFixture(test,invalid,profile.FailureCategoryLocalCancelled)
    if !errors.Is(invalid,context.Canceled)||!bytes.Equal(*failure.Identity.ExpectedVersions[0].Version,[]byte{1})||failure.Observed!=nil { test.Fatal("native cancellation lost original precondition or invented cleanup") }
    waitFor(test,func() bool { snapshot:=client.Snapshot(); return snapshot.InFlight==0&&snapshot.WireConcurrencySlots==0 })
    recovered,invalid:=client.LookupCommand(context.Background(),transactionLookupFixture(nil),profile.CallOptions{}); if invalid!=nil||recovered.Metadata.Observed.Command.Commit.ReceiptId!="receipt-a"||peer.requests.Load()!=2 { test.Fatal("explicit new local scope recovery replayed command",invalid) }
}
func TestTransactionWrongProfileAndOriginalDeadlineRejectBeforeDispatch(test *testing.T) {
    peer:=newPeer(test,func(writer http.ResponseWriter,request *http.Request) { test.Error("invalid transaction reached native dispatch") }); client:=testClient(test,peer)
    original:=transactionInvokeFixture(); original.Profile.HostAbiDigest="future"
    _,invalid:=client.InvokeCommand(context.Background(),original,profile.CallOptions{}); rejected:=transactionFailureFixture(test,invalid,profile.FailureCategoryInvalidRequest)
    if rejected.Transport.Dispatched||rejected.Identity.Command==nil||rejected.Identity.Command.ClientKey!="business-key-a" { test.Fatal("profile rejection lost original recovery identity") }
    original=transactionInvokeFixture(); original.Invocation.DeadlineUnixMillis=pointer(uint64(0))
    _,invalid=client.InvokeCommand(context.Background(),original,profile.CallOptions{}); expired:=transactionFailureFixture(test,invalid,profile.FailureCategoryDeadline)
    if expired.Transport.Dispatched||len(expired.Identity.ExpectedVersions)!=1||peer.requests.Load()!=0 { test.Fatal("original expired wall deadline was refreshed or dispatched") }
}
