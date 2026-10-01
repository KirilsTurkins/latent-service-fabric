import type * as model from "./transactions.js";
import type * as profile from "./management.js";

/** Original admission and recovery data. None of these fields grants authority. */
export interface RecoveryIdentity extends profile.RequestIdentity {
  readonly namespace?: model.NamespaceSelector;
  readonly command?: model.CommandSelector;
  readonly commandId?: string;
  readonly attemptId?: string;
  readonly receiptId?: string;
  readonly effectId?: string;
  readonly retryRequestId?: string;
  readonly expectedAbort?: model.AbortFence;
  readonly expectedVersions?: readonly model.ExpectedVersion[];
  readonly expectedGeneration?: bigint;
  readonly expectedVersion?: Uint8Array;
  readonly expectedPolicyDigest?: string;
  readonly fingerprintSha256?: Uint8Array;
  readonly authorizationPublication?: profile.PublicationRef;
  readonly dispatcherAction?: model.DispatcherAction;
  readonly dispatcherExpectedGeneration?: model.DispatcherGeneration;
}

/** Retains bounded receipt data independently of an application result body. */
export type ObservedOutcome =
  | { readonly kind: "command"; readonly command: Omit<model.CommandInspection, "success" | "businessRejection" | "technicalFailure" | "cleanupFailure"> }
  | { readonly kind: "state"; readonly receipt: model.StateOperationReceipt }
  | { readonly kind: "namespace"; readonly receipt: model.NamespaceOperationReceipt }
  | { readonly kind: "effect"; readonly receipt: model.EffectReceipt }
  | { readonly kind: "dispatcher"; readonly receipt: model.DispatcherOperationReceipt };

export interface ResponseMetadata extends profile.ResponseMetadata {
  readonly transactionIdentity: RecoveryIdentity;
  readonly observedTransaction?: ObservedOutcome;
}

export interface ClientResponse<Response> {
  readonly value: Response;
  readonly metadata: ResponseMetadata;
}

export interface ClientFailure extends profile.ClientFailure {
  readonly transactionIdentity: RecoveryIdentity;
  readonly observedTransaction?: ObservedOutcome;
}

/** Implemented by the maintained Node RPC transport. Browser code uses HTTP. */
export interface TransactionClient {
  invokeCommand(request: model.InvokeCommandRequest, options?: profile.CallOptions): Promise<ClientResponse<model.InvokeCommandResponse>>;
  query(request: model.QueryRequest, options?: profile.CallOptions): Promise<ClientResponse<model.QueryResponse>>;
  lookupCommand(request: model.LookupCommandRequest, options?: profile.CallOptions): Promise<ClientResponse<model.LookupCommandResponse>>;
  lookupCommit(request: model.LookupCommitRequest, options?: profile.CallOptions): Promise<ClientResponse<model.LookupCommitResponse>>;
  getEffect(request: model.GetEffectRequest, options?: profile.CallOptions): Promise<ClientResponse<model.GetEffectResponse>>;
  listEffectHistory(request: model.ListEffectHistoryRequest, options?: profile.CallOptions): Promise<ClientResponse<model.ListEffectHistoryResponse>>;
  cancelCommand(request: model.CancelCommandRequest, options?: profile.CallOptions): Promise<ClientResponse<model.CancelCommandResponse>>;
  inspectNamespace(request: model.InspectNamespaceRequest, options?: profile.CallOptions): Promise<ClientResponse<model.InspectNamespaceResponse>>;
  mutateNamespace(request: model.MutateNamespaceRequest, options?: profile.CallOptions): Promise<ClientResponse<model.MutateNamespaceResponse>>;
  selectEntity(request: model.SelectEntityRequest, options?: profile.CallOptions): Promise<ClientResponse<model.SelectEntityResponse>>;
  mutateState(request: model.MutateStateRequest, options?: profile.CallOptions): Promise<ClientResponse<model.MutateStateResponse>>;
  getStateOperationReceipt(request: model.GetStateOperationReceiptRequest, options?: profile.CallOptions): Promise<ClientResponse<model.GetStateOperationReceiptResponse>>;
  inspectDispatcher(request: model.InspectDispatcherRequest, options?: profile.CallOptions): Promise<ClientResponse<model.InspectDispatcherResponse>>;
  controlDispatcher(request: model.ControlDispatcherRequest, options?: profile.CallOptions): Promise<ClientResponse<model.ControlDispatcherResponse>>;
  getDispatcherOperation(request: model.GetDispatcherOperationRequest, options?: profile.CallOptions): Promise<ClientResponse<model.GetDispatcherOperationResponse>>;
}
