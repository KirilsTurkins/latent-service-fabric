# Start with LSF

LSF runs small programs called **capsules**. A **node** loads a capsule when you
call it, runs the requested function, and returns the result. You can deploy
several capsules to one node without starting a separate server for each one.

In your first walkthrough you will create a local node, deploy an echo capsule,
send it `hello`, and receive `hello` back. You will also restart the node and
call the same deployment again. That gives you a working foundation for adding
your own application functions.

## Create your first application

Start with [application development](application-development.md). You will
install the selected tools, choose one of six languages, create a greeting,
and run its tests on a node. The tools create private credentials for you.
After changing `Hello` to `Welcome`, edit/watch builds and deploys the change;
a compiler error leaves the last working version callable. You will also
restart the node and see your deployment retained.

Use [Windows and WSL2](../component-development/windows-application.md) or
[Linux](../component-development/linux-workspace.md). You do not need an LSF
source checkout or a host language compiler for this packaged workflow.

## Run a node from source

For contributor builds and a closer look at individual operator commands,
open [Run your first node](first-node.md). It walks through every command:

1. Download the source and build the two LSF programs.
2. Create private node and client configuration files.
3. Start the node and check that it is ready.
4. Publish and deploy a capsule.
5. Call it, inspect the answer, and try an invalid input.
6. Restart the node and call the saved deployment.
7. Stop the node when you finish.

You need a Linux environment and a terminal that runs Bash. The walkthrough
uses a node that only accepts connections from your own machine. For prebuilt
developer tools or a persistent native server, use
[installation](../installation.md) instead.

## Develop an application from selected packages

For Windows/WSL2, direct Linux, an explicit SSH host or native Windows capsule
tests, start with [Application development](application-development.md).
That path uses the qualified development toolkit and generates private
workspace credentials. It covers authoring, testing, edit/watch, recovery and
cleanup without building LSF. [Get the developer tools](developer-setup.md)
before following your platform walkthrough.

## Build something of your own

After the first invocation, continue with
[Creating a capsule](../component-development/creating-a-capsule.md).
You will build small services with different purposes, see their complete code,
and try their inputs and outputs on the node you just created.

To call LSF from an existing application, use the
[client SDK guide](../learn/use-a-client.mdx). Its language tabs select Rust,
TypeScript, Go, C, Java or C#. To build a website, follow the
[Angular application guide](../learn/build-and-deliver-angular.mdx).

## A few terms you will use

| Term | Meaning in the walkthrough |
| --- | --- |
| Capsule | Your program, packaged as a WebAssembly component with a description of its functions |
| Contract | The names and types of the inputs and outputs a capsule accepts |
| Publication | The node's record of the capsule you uploaded |
| Deployment | A named choice of which published capsule should answer calls to a service |
| Activation | One call to a capsule function |

You do not need to understand LSF's internal architecture to complete these
walkthroughs. Start with the working example and explore the references when
you need more detail.
