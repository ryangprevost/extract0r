// Mirrors app/api/schemas.py. Regenerate from /openapi.json once the API stabilises.

export type StemKind = "vocals" | "drums" | "bass" | "guitar" | "piano" | "other";

export type JobState = "queued" | "running" | "succeeded" | "failed";

export interface Track {
  track_id: string;
  original_filename: string;
  size_bytes: number;
  sha256: string;
  duration_s?: number | null;
}

export interface StemInfo {
  stem: StemKind;
  filename: string;
  bytes: number;
}

export interface SeparationResult {
  track_id: string;
  backend: string;
  model: string;
  stems: StemInfo[];
}

export interface Job<TResult = unknown> {
  job_id: string;
  kind: string;
  track_id: string;
  state: JobState;
  progress: number;
  message: string;
  result?: TResult | null;
  error?: string | null;
}

export interface TabArtifact {
  stem: StemKind;
  notation: "string_tab" | "drum_tab" | "pitch_list";
  note_count: number;
  download_url: string;
  preview: string;
}

export interface TranscribeResult {
  track_id: string;
  artifacts: TabArtifact[];
  x0r_url: string;
}

export interface TuningOption {
  name: string;
  open_pitches: number[];
  strings: number;
  frets: number;
}

export interface LegalNotices {
  terms_version: string;
  copyright_notice: string;
  upload_gate: string;
  retention_hours: number;
  dmca_contact: string;
}

export interface Capabilities {
  configured: Record<string, string>;
  installed: Record<string, boolean>;
  limits: { max_upload_mb: number; retention_hours: number };
}

export const STEM_LABELS: Record<StemKind, string> = {
  vocals: "Vocals",
  drums: "Drums",
  bass: "Bass",
  guitar: "Guitar",
  piano: "Piano",
  other: "Other",
};

// Stems we can turn into tab. Vocals transcribe to a pitch list, not tablature.
export const TRANSCRIBABLE: StemKind[] = ["bass", "guitar", "piano", "drums", "other"];
