# Manual guide checks, 2026-09-23

The current learning path uses individual commands on the reader's tutorial
node. This record separates local command execution from the older automated
qualification workflows and from the pending human walkthrough review.

## Observed commands

The Bash blocks were extracted from the guides and run in order on Linux x86_64
inside the retained development container. The setup used the first-node guide's
configuration, generated private credential, authenticated readiness, echo
publication and deployment. Existing local binary and generated-echo paths
replaced the checkout/build prerequisite; the node and CLI were not rebuilt.

| Guide | Observed result |
| --- | --- |
| [Update and restore a capsule](../learn/deliver-and-recover-a-capsule.md) | The rebuilt greeting returned `Welcome, Ada!`; restoring the original publication returned `Hello, Ada!`. Current generations permitted final deployment cleanup. |
| [Change and revoke a policy](../how-to/reconcile-a-policy-change.md) | Creation, bounded listing and operation lookup succeeded. Revocation persisted after restart. The earlier creation receipt remained historical and did not restore authority. |
| [Inspect and stop a node](../how-to/operate-and-contribute.md) | Readiness and routes were visible; the completed echo activation returned `already_terminal` on cancellation. The final stopped report was clean, and the saved deployment reopened successfully. |

The optional audit query was not executed against the basic tutorial node,
which has no audit configuration. The walkthrough labels that prerequisite.
The policy example grants no capability access and invokes no provider; its
first-node setup executes echo. These checks do not replace allowed/denied
provider, in-flight cancellation or uncertainty qualification.

## Runtime identity and limits

| Retained executable | SHA-256 |
| --- | --- |
| `latent` | `e38d2746df5e02953e9da579c16b66472b8582435cc6ac9a7e3f64016fdedc77` |
| `latentd` | `7b025a3072ef539d55499b2955a375e0a0babf255c09789303301824cfbebadd` |

This run identifies the executed bytes without asserting a new source-to-binary
build relationship. Local command transcripts remain in the review workspace.
No runtime release, installed-bundle qualification, performance result or human
acceptance is established by these checks. The current guide changes still need
their CI and newcomer review; retained historical receipts keep their original
source identities.

The [core validation handoff](core-guide-validation.md) documents the automated
companion and its separate record format. The website checks rendering, links,
source extraction and navigation; building it does not execute these commands.
