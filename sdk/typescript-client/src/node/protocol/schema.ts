import { createFileRegistry, fromBinary, type DescMethod } from "@bufbuild/protobuf";
import { FileDescriptorSetSchema } from "@bufbuild/protobuf/wkt";
import { descriptorBytes } from "./generated.js";
import { descriptorBytes as transactionDescriptorBytes } from "./transaction-generated.js";

export const registry = createFileRegistry(fromBinary(FileDescriptorSetSchema, descriptorBytes));
export const transactionRegistry = createFileRegistry(fromBinary(FileDescriptorSetSchema, transactionDescriptorBytes));

const operations = {
  invoke: ["latent.invocation.v1.InvocationService", "Invoke"],
  cancel: ["latent.invocation.v1.InvocationService", "Cancel"],
  getActivation: ["latent.invocation.v1.InvocationService", "GetActivation"],
  getPolicy: ["latent.control.v1.PolicyService", "GetPolicy"],
  listPolicies: ["latent.control.v1.PolicyService", "ListPolicies"],
  listCapabilities: ["latent.control.v1.CapabilityService", "ListCapabilities"],
  applyPolicy: ["latent.control.v1.PolicyService", "ApplyPolicy"],
  getPolicyOperation: ["latent.control.v1.PolicyService", "GetPolicyOperation"],
  invokeCommand: ["latent.transaction.v1.TransactionService", "InvokeCommand"],
  query: ["latent.transaction.v1.TransactionService", "Query"],
  lookupCommand: ["latent.transaction.v1.TransactionService", "LookupCommand"],
  lookupCommit: ["latent.transaction.v1.TransactionService", "LookupCommit"],
  getEffect: ["latent.transaction.v1.TransactionService", "GetEffect"],
  listEffectHistory: ["latent.transaction.v1.TransactionService", "ListEffectHistory"],
  cancelCommand: ["latent.transaction.v1.TransactionService", "CancelCommand"],
  inspectNamespace: ["latent.control.v1.StateService", "InspectNamespace"],
  mutateNamespace: ["latent.control.v1.StateService", "MutateNamespace"],
  selectEntity: ["latent.control.v1.StateService", "SelectEntity"],
  mutateState: ["latent.control.v1.StateService", "MutateState"],
  getStateOperationReceipt: ["latent.control.v1.StateService", "GetStateOperationReceipt"],
  inspectDispatcher: ["latent.control.v1.DispatcherService", "InspectDispatcher"],
  controlDispatcher: ["latent.control.v1.DispatcherService", "ControlDispatcher"],
  getDispatcherOperation: ["latent.control.v1.DispatcherService", "GetDispatcherOperation"],
} as const;

export type Operation = keyof typeof operations;

export function isTransaction(operation: Operation): boolean {
  const service = operations[operation][0];
  return service === "latent.transaction.v1.TransactionService" || service === "latent.control.v1.StateService" || service === "latent.control.v1.DispatcherService";
}

export function method(operation: Operation): DescMethod {
  const [service, name] = operations[operation];
  const selected = isTransaction(operation) ? transactionRegistry : registry;
  const descriptor = selected.getService(service)?.methods.find((candidate) => candidate.name === name);
  if (!descriptor || descriptor.methodKind !== "unary") throw new Error("unsupported RPC descriptor");
  return descriptor;
}
