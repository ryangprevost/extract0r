"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError, formatBytes } from "@/lib/api";
import { CopyrightBanner } from "./CopyrightBanner";

const ACCEPT = ".mp3,.wav,.flac,.m4a,.aac,.ogg,.aiff,.aif";

export function UploadPanel({ maxUploadMb }: { maxUploadMb: number }) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [ownsOrLicensed, setOwnsOrLicensed] = useState(false);
  const [personalUseOnly, setPersonalUseOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Both boxes are a hard gate: the API rejects the upload without them anyway.
  const ready = Boolean(file) && ownsOrLicensed && personalUseOnly && !busy;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const track = await api.upload(file, { ownsOrLicensed, personalUseOnly });
      router.push(`/studio/${track.track_id}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Upload failed. Try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <CopyrightBanner variant="inline" />

      <label className="block cursor-pointer rounded-xl border-2 border-dashed border-edge bg-panel p-10 text-center hover:border-accent/60">
        <input
          type="file"
          accept={ACCEPT}
          className="sr-only"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setError(null);
          }}
        />
        {file ? (
          <span className="font-mono text-sm">
            {file.name} <span className="text-muted">({formatBytes(file.size)})</span>
          </span>
        ) : (
          <span className="text-muted">
            Choose an audio file — up to {maxUploadMb} MB (mp3, wav, flac, m4a, ogg, aiff)
          </span>
        )}
      </label>

      <fieldset className="space-y-3 text-sm">
        <legend className="sr-only">Rights attestation</legend>
        <label className="flex gap-3">
          <input
            type="checkbox"
            checked={ownsOrLicensed}
            onChange={(event) => setOwnsOrLicensed(event.target.checked)}
            className="mt-1"
          />
          <span>
            I own this recording, hold a licence for it, or my use is otherwise permitted by law.
          </span>
        </label>
        <label className="flex gap-3">
          <input
            type="checkbox"
            checked={personalUseOnly}
            onChange={(event) => setPersonalUseOnly(event.target.checked)}
            className="mt-1"
          />
          <span>
            I will use the output for personal study, practice, or another lawful purpose, and I
            will not distribute it without permission.
          </span>
        </label>
      </fieldset>

      {error ? <p className="text-sm text-warn">{error}</p> : null}

      <button
        type="submit"
        disabled={!ready}
        className="rounded-lg bg-accent px-5 py-2.5 font-semibold text-ink disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? "Uploading…" : "Upload and split"}
      </button>
    </form>
  );
}
