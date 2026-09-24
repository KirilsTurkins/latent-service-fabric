# Understand your first capsule

The [first-node walkthrough](../start/first-node.md) runs an echo capsule:
you send a message and get the same message back. This page explains how its
contract, Rust implementation and deployment fit together. To write programs
with different purposes, continue with
[Creating a capsule](../component-development/creating-a-capsule.md).

## 1. Read the contract

Open [echo.wit](../../examples/echo-contract/wit/echo.wit). Its function is:

```wit
variant echo-error {
    empty-message,
    message-too-large,
}

echo: func(message: string) -> result<string, echo-error>;
```

`message: string` is the input. `result<string, echo-error>` means the function
returns either a string or one of the named errors. A caller can handle an empty
message differently from a message that is too long.

The same file's `world service` exports this API and imports two host capabilities:
activation context and logging. An **export** is a function callers can use.
An **import** is a function your capsule asks the node to provide.

## 2. Follow the Rust implementation

The [domain logic](../../tools/toolchain-smoke/examples/echo_capsule/logic.rs)
checks for an empty string, rejects messages larger than 65,536 UTF-8 bytes,
and otherwise returns the input. The limit counts bytes, so some characters
occupy more than one byte.

The following implementation connects that logic to the generated interface:

<!-- lsf-example: guest/rust-echo echo -->

`impl Guest for EchoCapsule` implements the exported function. The generated
`EchoError` type corresponds to the two errors in WIT. Before returning, the
function also records the activation ID, input length and outcome in a log.
It does not log the message contents. Logging is best effort: a rejected log
record does not turn a successful echo into an application error.

The complete [component source](../../tools/toolchain-smoke/examples/echo_capsule/component.rs)
includes binding generation, imports and the export macro. This is Rust code
compiled **inside** the capsule. An external Rust or other-language client is a
separate application that calls it through the [client SDK](use-a-client.mdx).

## 3. Connect the files you built

After `make echo-capsule`, the `target/capsules/echo` directory contains:

| File | Role |
| --- | --- |
| `echo-capsule.wasm` | The program the node executes |
| `capsule.json` | Its identity, exported contract and execution requirements |
| `contracts.json` | Input/output types used to check calls |
| `deployment.json` | The service name, chosen publication and allowed resources |
| `input.json` | A sample call |

The builder fills in the program's checksum. Publishing returns a publication
ID, and the first-node walkthrough puts that ID into the deployment. Deploying
selects which program answers calls; editing a source file does not automatically
replace a running deployment.

Each call starts with fresh guest state. A global variable in the capsule is
not storage for the next request. Host access also needs a deployment grant:
importing a capability alone does not authorize it.

## 4. Compare a result and an error

In the [first-node walkthrough](../start/first-node.md#6-call-the-capsule):

| Input | Decoded answer | Meaning |
| --- | --- | --- |
| `["hello"]` | `[{"ok":"hello"}]` | The capsule returned a normal result |
| `[""]` | An `err` containing `empty-message` | The capsule rejected the input as its contract permits |

These application errors differ from a connection failure or an exhausted
execution budget. The CLI returns exit code 3 for a declared application error;
[other exit codes](../reference/operator-cli.md#output-and-exits) identify the
other outcomes. Do not repeat an uncertain call merely because its response
was lost.

## Next: write your own functions

[Creating a capsule](../component-development/creating-a-capsule.md) provides
complete greeting, word-count and shipping-calculator implementations and the
commands to deploy all three. It shows a source change you can make and passes
you to [updating and restoring a deployment](deliver-and-recover-a-capsule.md).
