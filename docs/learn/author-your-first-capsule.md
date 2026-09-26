# Understand your first capsule

The [packaged application walkthrough](../start/application-development.md)
creates a greeting program: send `Ada`, receive `Hello, Ada!`. This page explains
the files you created and how an input becomes a typed answer. You can write the
same capsule in Rust, C, TypeScript, Go, Java or C#.

## 1. Read the contract

Open the WIT contract under your project's `app` directory. The greeting exports:

```wit
greet: func(name: string) -> result<string, string>;
```

`name: string` is the input. `result<string, string>` means the function returns
either a greeting or an explanation of invalid input. An **export** is a
function callers can use. An **import** is a function your capsule asks the
node to provide, such as a permitted clock or HTTP request.

The contract stays the same when you choose another programming language.
Generated bindings connect your language's types to that contract. The node
checks calls against the contract before running the function.

## 2. Follow the implementation

Select your language above this complete greeting example:

<!-- lsf-example: guest/tutorial-greeting capsule -->

The program trims the supplied name, rejects empty or excessive input, and
returns the greeting. Open the matching source under `app` in the project
created by `dev init`. Edit that source, then use `dev build` to compile it.
The [Windows walkthrough](../component-development/windows-application.md)
also shows a Rust watch session that changes `Hello,` to `Welcome,` and keeps
the previous deployment working through a compiler error.

This code runs **inside** the capsule. A [client SDK](use-a-client.mdx) is a
separate application that calls the capsule from outside the node. Both offer
six language choices, but their libraries have different jobs.

## 3. Connect the project files

| File or directory | What you use it for |
| --- | --- |
| `app` | Edit the application source and its WIT contract |
| `latent.project.json` | Review the selected compiler, build recipe and output paths |
| `tests/scenarios.json` | See the named success and failure cases |
| `tests/*-input.json` and `tests/*-expected.json` | Read or change a case's input and expected typed answer |
| `.vscode/tasks.json`, after `dev editor` | Run the same commands from an optional editor |

`dev build` produces the component and its manifests. `dev deploy` selects that
accepted build for your service. The frontend keeps the generated identifiers
and node credentials; you do not copy them into your source.

Each call starts with fresh guest state. A global variable is not storage for
the next request. Host access needs an explicit deployment grant: importing a
capability alone does not authorize it. See [Use capabilities](use-capabilities.md)
when your program needs something beyond its input and local computation.

## 4. Compare a result and an error

The greeting's real-node scenarios include:

| Input | Expected answer | Meaning |
| --- | --- | --- |
| `Ada` | `Hello, Ada!` | The function returned a successful result |
| An empty name | A declared string error | The program rejected invalid input |

Run `dev test --environment node` with your workspace as shown in the platform
walkthrough. Expect all three greeting cases to pass, including the declared
error. A test passes when the observed outcome matches its expectation; an
expected application error is a useful successful test.

A connection failure, denied capability or exhausted execution budget is a
different outcome. Inspect the reported category and original operation status.
Do not repeat a call whose response was lost: it may already have executed.

## 5. Try a different purpose

[Build a packaged capsule in your language](../component-development/packaged-languages.md)
shows how to select the `word-count` or `shipping` template. Use a new project
and disposable workspace for each example. [Creating a capsule](../component-development/creating-a-capsule.md)
explains all three programs, displays their six-language implementations, and
also provides the lower-level operator commands for running them together.

Use `dev down` to stop your node while retaining its data. Use the explicit
workspace purge from the platform guide when the disposable tutorial is finished.
Your application source remains available for the next edit.
