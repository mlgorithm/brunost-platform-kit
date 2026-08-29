# `@brunost/browser-runtime`

Framework-neutral browser execution primitives for student workspaces. The
package owns the public contract between an editor and a browser kernel; it does
not own authentication, storage, React, Monaco, or the trusted contest judge.

The important boundary is an immutable project snapshot. A snapshot contains
the exact files, entrypoint, language, and pinned runtime manifest. Its SHA-256
hash is deterministic, so a platform can store it, display it next to a local
preview, or submit the same input to a trusted judge later.

## Install

```bash
npm install @brunost/browser-runtime
```

The package is MIT licensed and lives in the public
[`brunost-platform-kit`](https://github.com/mlgorithm/brunost-platform-kit)
repository. Browser kernel adapters are deliberately small and replaceable:
Pyodide, a WebAssembly C/C++ compiler, a GPU simulator, or a platform-specific
worker can all implement the same `BrowserKernel` interface.

## Minimal adapter

```ts
import {
  createBrowserWorkspace,
  type BrowserKernel,
} from "@brunost/browser-runtime";

const python: BrowserKernel = {
  language: "python",
  async run(request) {
    // Execute request.snapshot.files in your worker.
    return {
      stdout: "hello\n",
      stderr: "",
      result: null,
      error: null,
      exit_code: 0,
      duration_ms: 4,
    };
  },
};

const workspace = createBrowserWorkspace({ kernels: { python } });
const result = await workspace.run({
  language: "python",
  entrypoint: "main.py",
  files: [{ path: "main.py", content: "print('hello')" }],
  runtime_manifest: {
    schema_version: 1,
    runtime_id: "pyodide",
    runtime_version: "0.26.4",
    language: "python",
    compiler_id: null,
    compiler_version: null,
    time_limit_ms: 15_000,
    memory_limit_mb: 512,
    output_limit_bytes: 1_000_000,
    flags: ["browser-worker"],
  },
});

console.log(result.snapshot.content_hash);
```

This core package is intentionally runtime-agnostic. Brunost currently keeps
its Pyodide and browsercc worker adapters in the Premium application while the
adapter API stabilizes; they can be published as optional packages without
changing this contract.
