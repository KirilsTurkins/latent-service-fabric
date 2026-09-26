import { createFileRegistry, fromBinary, type DescMethod } from "@bufbuild/protobuf";
import { FileDescriptorSetSchema } from "@bufbuild/protobuf/wkt";
import { descriptorBytes } from "./generated.js";

export const registry = createFileRegistry(fromBinary(FileDescriptorSetSchema, descriptorBytes));

const operations = {
  invoke: ["latent.invocation.v1.InvocationService", "Invoke"],
  cancel: ["latent.invocation.v1.InvocationService", "Cancel"],
  getActivation: ["latent.invocation.v1.InvocationService", "GetActivation"],
  getPolicy: ["latent.control.v1.PolicyService", "GetPolicy"],
  listPolicies: ["latent.control.v1.PolicyService", "ListPolicies"],
  listCapabilities: ["latent.control.v1.CapabilityService", "ListCapabilities"],
  applyPolicy: ["latent.control.v1.PolicyService", "ApplyPolicy"],
  getPolicyOperation: ["latent.control.v1.PolicyService", "GetPolicyOperation"],
} as const;

export type Operation = keyof typeof operations;

export function method(operation: Operation): DescMethod {
  const [service, name] = operations[operation];
  const descriptor = registry.getService(service)?.methods.find((candidate) => candidate.name === name);
  if (!descriptor || descriptor.methodKind !== "unary") throw new Error("unsupported RPC descriptor");
  return descriptor;
}
