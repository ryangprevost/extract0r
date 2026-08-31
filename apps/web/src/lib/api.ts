import type {
  Capabilities,
  Job,
  LegalNotices,
  SeparationResult,
  StemKind,
  Track,
  TranscribeResult,
  TuningOption,
} from "./types";

// Requests go to /api on this origin; next.config.ts rewrites them to the FastAPI service.
const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    // FastAPI puts the human-readable reason in `detail`.
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail ?? response.statusText, response.status);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  legal: () => request<LegalNotices>("/legal"),
  capabilities: () => request<Capabilities>("/capabilities"),
  tunings: () => request<Record<string, TuningOption>>("/tracks/tunings"),

  async upload(file: File, attestation: { ownsOrLicensed: boolean; personalUseOnly: boolean }) {
    const form = new FormData();
    form.append("file", file);
    form.append("owns_or_licensed", String(attestation.ownsOrLicensed));
    form.append("personal_use_only", String(attestation.personalUseOnly));
    return request<Track>("/tracks", { method: "POST", body: form });
  },

  separate: (trackId: string) => request<Job>(`/tracks/${trackId}/separate`, { method: "POST" }),

  stems: (trackId: string) => request<SeparationResult>(`/tracks/${trackId}/stems`),

  transcribe: (trackId: string, stems: StemKind[], tunings: Partial<Record<StemKind, string>>) =>
    request<Job>(`/tracks/${trackId}/transcribe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stems, tunings }),
    }),

  job: <T>(jobId: string) => request<Job<T>>(`/jobs/${jobId}`),

  deleteTrack: (trackId: string) => request<void>(`/tracks/${trackId}`, { method: "DELETE" }),

  tabUrl: (trackId: string, stem: StemKind) => `${BASE}/tracks/${trackId}/tabs/${stem}`,
  x0rUrl: (trackId: string) => `${BASE}/tracks/${trackId}/x0r`,
};

/** Poll a job until it settles. Jobs are minutes-long, so a fixed interval is fine. */
export async function waitForJob<T>(
  jobId: string,
  onProgress?: (job: Job<T>) => void,
  intervalMs = 1000,
  timeoutMs = 15 * 60 * 1000,
): Promise<Job<T>> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const job = await api.job<T>(jobId);
    onProgress?.(job);
    if (job.state === "succeeded" || job.state === "failed") return job;
    if (Date.now() > deadline) throw new ApiError("Job timed out.", 504);
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
