# Start with LSF

LSF runs small programs called **capsules**. A **node** loads a capsule when you
call it, runs the requested function, and returns the result. You can deploy
several capsules to one node without starting a separate server for each one.

In your first walkthrough you will create a local node, deploy an echo capsule,
send it `hello`, and receive `hello` back. You will also restart the node and
call the same deployment again. That gives you a working foundation for adding
your own application functions.

## Create your first node

Open [Run your first node](first-node.md). It walks through every command:

1. Download the source and build the two LSF programs.
2. Create private node and client configuration files.
3. Start the node and check that it is ready.
4. Publish and deploy a capsule.
5. Call it, inspect the answer, and try an invalid input.
6. Restart the node and call the saved deployment.
7. Stop the node when you finish.

You need a Linux environment and a terminal that runs Bash. The walkthrough
uses a node that only accepts connections from your own machine. A prebuilt
installation release is being prepared; [installation](../installation.md)
will explain that option when it is available.

## Develop an application from selected packages

For Windows/WSL2, direct Linux, an explicit SSH host or native Windows capsule
tests, start with [Application development](application-development.md).
That path uses independently approved candidate packages and generates private
workspace credentials. It covers authoring, testing, edit/watch, recovery and
cleanup without building LSF. Candidate access is a maintainer handoff until a
public developer release is approved.

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
