# Read a capsule contract

A contract tells callers which functions a capsule provides, what values those
functions accept, and what results they can return. LSF uses **WIT** (WebAssembly
Interface Types) for these contracts. You can understand a small contract before
you learn the runtime's internal architecture.

## 1. Find the exported function

The greeting example in [Creating a capsule](../component-development/creating-a-capsule.md)
exports this function:

```wit
greet: func(name: string) -> result<string, string>;
```

Read it from left to right:

- `greet` is the function name.
- `name: string` is one argument: a person's name.
- `result<string, string>` is either a successful string or a string explaining
  why the application rejected the input.

The [complete contract](../../tools/toolchain-smoke/examples/tutorial_greeting/world.wit)
places the function in a named interface and exports that interface from a
world. The world describes the complete set of imports and exports for the
component. Its version is part of the contract identity.

## 2. Match a call to its argument types

The generic CLI represents arguments as a positional JSON array. For `greet`,
which takes one string, use:

```json
["Ada"]
```

The shipping example takes a whole number and a boolean:

```wit
quote: func(items: u32, express: bool) -> result<u32, string>;
```

Its corresponding input is:

```json
[2, false]
```

The order matters. `u32` is an unsigned 32-bit whole number, so a negative value
or a fractional value is invalid. For this example, the decoded answer is
`[{"ok":650}]`: a successful shipping price of 650 cents.

The CLI's outer response also carries the activation ID and other request
information. The tutorials' `answer` helper decodes the result for you. When
writing a client, use the SDK's response model and preserve its error category.
[WIT value encoding](../protocol/wit-values.md) documents records, lists, options,
variants and large integer values when your contract needs them.

## 3. Distinguish the possible outcomes

| What happened | How to handle it |
| --- | --- |
| The function returned a normal value | Use the result |
| The function returned its declared error | Handle the application's error according to its contract |
| The platform rejected or interrupted execution | Inspect the policy, budget or platform outcome |
| The transport lost the response | Keep the activation ID and query status; execution may have occurred |

For example, shipping zero items returns the declared error
`Choose between 1 and 100 items.` The node is still available for another valid
request. An invalid argument shape can instead be rejected before the function
runs. A timeout alone does not tell you which application result occurred.

## 4. Read imports before granting capabilities

An import is a host function the capsule needs, such as logging, outbound HTTP
or blob access. The guest SDK generates matching language types from WIT.
The node still needs the provider installed, and your deployment and policy must
grant the required access within a budget. A declared import does not grant that
access by itself.

Follow [Use capabilities](use-capabilities.md) when your function needs host
services. Check [available standalone providers](../reference/standalone-providers.md)
before copying an example that uses a trusted Rust embedding.

## 5. Know which contract you are reading

| File family | Defines |
| --- | --- |
| [WIT](../../wit/README.md) | Guest exports and host capabilities |
| [Protobuf APIs](../api-surface.md) | Node invocation and management RPCs |
| [JSON Schemas](../../schemas/README.md) | Capsule, deployment, policy, trigger and other document shapes |
| [SDK profile](../../sdk/profile/README.md) | Convenient language APIs that preserve the RPC semantics |

Use the documentation version that matches your node and SDK. A future design
or an old measured result does not add an implemented API to that version.
Contributors checking implementation claims can use the
[validation guide](../../VALIDATION.md); application authors can continue with
[creating a capsule](../component-development/creating-a-capsule.md) and
[calling it from a client](use-a-client.mdx).

