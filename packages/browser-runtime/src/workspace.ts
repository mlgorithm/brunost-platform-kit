import type {
  BrowserCapabilities,
  BrowserExecutionResult,
  BrowserWorkspace,
  BrowserWorkspaceOptions,
} from "./contracts.js";
import { createProjectSnapshot } from "./snapshot.js";

function detectCapabilities(): BrowserCapabilities {
  return {
    worker: typeof Worker !== "undefined",
    webassembly: typeof WebAssembly !== "undefined",
    webgpu: typeof navigator !== "undefined" && "gpu" in navigator,
  };
}

export function createBrowserWorkspace(options: BrowserWorkspaceOptions): BrowserWorkspace {
  return {
    capabilities: detectCapabilities,
    async run(request): Promise<BrowserExecutionResult & { snapshot: Awaited<ReturnType<typeof createProjectSnapshot>> }> {
      const kernel = options.kernels[request.language];
      if (!kernel) {
        throw new Error(`No browser kernel registered for ${request.language}`);
      }
      if (kernel.language !== request.language) {
        throw new Error(`Kernel language mismatch: expected ${request.language}, got ${kernel.language}`);
      }
      const snapshot = await createProjectSnapshot(request);
      const result = await kernel.run({ ...request, ...snapshot, snapshot });
      return { ...result, snapshot };
    },
  };
}
