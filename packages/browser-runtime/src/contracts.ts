export type BrowserLanguage = "python" | "c" | "cpp";

export type BrowserProjectFile = {
  path: string;
  content: string;
};

export type BrowserRuntimeManifest = {
  schema_version: 1;
  runtime_id: string;
  runtime_version: string;
  language: BrowserLanguage;
  compiler_id: string | null;
  compiler_version: string | null;
  time_limit_ms: number;
  memory_limit_mb: number;
  output_limit_bytes: number;
  flags: string[];
};

export type BrowserSnapshotInput = {
  language: BrowserLanguage;
  entrypoint: string;
  files: BrowserProjectFile[];
  runtime_manifest: BrowserRuntimeManifest;
};

export type BrowserProjectSnapshot = BrowserSnapshotInput & {
  content_hash: string;
};

export type BrowserRunRequest = BrowserSnapshotInput & {
  stdin?: string;
  /** Set by createBrowserWorkspace; kernels should execute this exact snapshot. */
  snapshot?: BrowserProjectSnapshot;
};

export type BrowserExecutionResult = {
  stdout: string;
  stderr: string;
  result: unknown | null;
  error: string | null;
  exit_code: number | null;
  duration_ms: number;
};

export interface BrowserKernel {
  readonly language: BrowserLanguage;
  run(request: BrowserRunRequest): Promise<BrowserExecutionResult>;
  reset?(): void;
}

export type BrowserCapabilities = {
  worker: boolean;
  webassembly: boolean;
  webgpu: boolean;
};

export type BrowserWorkspace = {
  capabilities(): BrowserCapabilities;
  run(request: BrowserSnapshotInput & { stdin?: string }): Promise<BrowserExecutionResult & {
    snapshot: BrowserProjectSnapshot;
  }>;
};

export type BrowserWorkspaceOptions = {
  kernels: Partial<Record<BrowserLanguage, BrowserKernel>>;
};
