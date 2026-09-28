# Start with LSF

LSF runs small programs called **capsules**. A **node** loads a capsule when you
call it, runs the requested function, and returns the result. You can deploy
several capsules to one node without starting a separate server for each one.

## Build your first application

Start with [Application development](application-development.md). You will set up
a development node, create a greeting in your chosen language, send it `Ada`, and
receive `Hello, Ada!`. Then try a word counter or shipping calculator. You will
have working source that you can edit, build, test and deploy yourself.

1. [Get the developer tools](developer-setup.md).
2. [Set up a workspace](development-workspace.md), using the Windows or Linux steps.
3. [Create a capsule](../component-development/creating-a-capsule.md) in Rust, C,
   TypeScript, Go, Java or C#.
4. [Change and test it](../learn/deliver-and-recover-a-capsule.md).

The tools generate the node credentials and install the matching compiler.
No LSF source checkout or host language compiler is needed for this path.

## Choose another starting point

| What you want to do | Start here |
| --- | --- |
| Call a capsule from an existing application | [Client SDK guide](../learn/use-a-client.mdx) |
| Serve an existing frontend or documentation site | [Deliver a website](../how-to/deliver-a-website.md), including Angular/PrimeNG and Docusaurus |
| Render Angular on the server | [Angular application guide](../learn/build-and-deliver-angular.mdx) |
| Install a persistent node | [Native installation](../installation.md) |
| Learn individual node commands or contribute to LSF | [Run your first node](first-node.md) from source |
| Find a development command | [Developer commands](../how-to/developer-commands.md) |

## A few terms you will use

| Term | Meaning |
| --- | --- |
| Capsule | Your program, packaged as a WebAssembly component with a description of its functions |
| Contract | The names and types of the inputs and outputs a capsule accepts |
| Publication | The node's record of a capsule you uploaded |
| Deployment | A named choice of which published capsule should answer a service's calls |
| Activation | One call to a capsule function |

You do not need to understand LSF's internal architecture to complete the first
application. Follow the working example and open the references when you need them.
