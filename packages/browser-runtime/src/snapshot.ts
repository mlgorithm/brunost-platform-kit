import type {
  BrowserProjectFile,
  BrowserProjectSnapshot,
  BrowserSnapshotInput,
} from "./contracts.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const PATH_SEGMENT = /^[A-Za-z0-9._-]{1,80}$/;

/** Stable JSON used for content addressing and server/client snapshot agreement. */
export function stableStringify(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
    const encoded = JSON.stringify(value);
    if (encoded === undefined) throw new TypeError("Snapshot values must be JSON-compatible");
    return encoded;
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(",")}}`;
  }
  throw new TypeError("Snapshot values must be JSON-compatible");
}

export function normalizeProjectFiles(files: BrowserProjectFile[]): BrowserProjectFile[] {
  const normalized = files.map((file) => {
    const path = file.path.trim();
    if (
      !path ||
      path.length > 255 ||
      path.startsWith("/") ||
      path.endsWith("/") ||
      path.includes("\\")
    ) {
      throw new Error(`Invalid project path: ${file.path}`);
    }
    const segments = path.split("/");
    if (
      segments.length > 8 ||
      segments.some((segment) => segment === "." || segment === ".." || !PATH_SEGMENT.test(segment))
    ) {
      throw new Error(`Invalid project path: ${file.path}`);
    }
    return { path, content: file.content };
  });
  // Do not use localeCompare here: Python's server canonicalizer sorts Unicode
  // code points, and locale-sensitive ordering would produce different hashes.
  normalized.sort((left, right) => (left.path < right.path ? -1 : left.path > right.path ? 1 : 0));
  for (let index = 1; index < normalized.length; index += 1) {
    if (normalized[index - 1].path === normalized[index].path) {
      throw new Error(`Duplicate project path: ${normalized[index].path}`);
    }
  }
  return normalized;
}

export function snapshotCanonicalPayload(input: BrowserSnapshotInput): BrowserSnapshotInput {
  return {
    language: input.language,
    entrypoint: input.entrypoint,
    files: normalizeProjectFiles(input.files),
    runtime_manifest: input.runtime_manifest,
  };
}

export async function sha256Hex(value: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function createProjectSnapshot(input: BrowserSnapshotInput): Promise<BrowserProjectSnapshot> {
  const canonical = snapshotCanonicalPayload(input);
  const content_hash = await sha256Hex(stableStringify({ schema_version: 1, ...canonical }));
  return { ...canonical, content_hash };
}
