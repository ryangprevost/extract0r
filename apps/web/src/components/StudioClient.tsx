"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, waitForJob } from "@/lib/api";
import {
  STEM_LABELS,
  TRANSCRIBABLE,
  type Job,
  type SeparationResult,
  type StemKind,
  type TabArtifact,
  type TranscribeResult,
  type TuningOption,
} from "@/lib/types";
import { TabPreview } from "./TabPreview";

type Phase = "separating" | "choosing" | "transcribing" | "done" | "error";

export function StudioClient({ trackId }: { trackId: string }) {
  const [phase, setPhase] = useState<Phase>("separating");
  const [progress, setProgress] = useState<Job | null>(null);
  const [separation, setSeparation] = useState<SeparationResult | null>(null);
  const [selected, setSelected] = useState<Set<StemKind>>(new Set());
  const [tunings, setTunings] = useState<Record<string, TuningOption>>({});
  const [chosenTuning, setChosenTuning] = useState<Partial<Record<StemKind, string>>>({});
  const [artifacts, setArtifacts] = useState<TabArtifact[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fail = useCallback((cause: unknown) => {
    setError(cause instanceof ApiError ? cause.message : "Something went wrong.");
    setPhase("error");
  }, []);

  // Kick off separation as soon as the studio opens; the upload page routed us here.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [job, tuningOptions] = await Promise.all([api.separate(trackId), api.tunings()]);
        if (cancelled) return;
        setTunings(tuningOptions);
        const finished = await waitForJob(job.job_id, (update) => {
          if (!cancelled) setProgress(update);
        });
        if (cancelled) return;
        if (finished.state === "failed") throw new ApiError(finished.error ?? "Separation failed.", 500);
        setSeparation(await api.stems(trackId));
        setPhase("choosing");
      } catch (cause) {
        if (!cancelled) fail(cause);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [trackId, fail]);

  function toggle(stem: StemKind) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(stem)) next.delete(stem);
      else next.add(stem);
      return next;
    });
  }

  async function transcribe() {
    setPhase("transcribing");
    setError(null);
    try {
      const job = await api.transcribe(trackId, [...selected], chosenTuning);
      const finished = await waitForJob<TranscribeResult>(job.job_id, setProgress);
      if (finished.state === "failed" || !finished.result) {
        throw new ApiError(finished.error ?? "Transcription failed.", 500);
      }
      setArtifacts(finished.result.artifacts);
      setPhase("done");
    } catch (cause) {
      fail(cause);
    }
  }

  async function deleteTrack() {
    await api.deleteTrack(trackId).catch(() => undefined);
    window.location.href = "/";
  }

  if (phase === "error") {
    return (
      <div className="rounded-lg border border-warn/40 bg-warn/5 p-6">
        <h2 className="font-semibold text-warn">Could not process this track</h2>
        <p className="mt-2 text-sm">{error}</p>
      </div>
    );
  }

  if (phase === "separating" || phase === "transcribing") {
    return <ProgressPanel job={progress} phase={phase} />;
  }

  const stemsAvailable = (separation?.stems ?? [])
    .map((s) => s.stem)
    .filter((s) => TRANSCRIBABLE.includes(s));

  return (
    <div className="space-y-8">
      <section>
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Stems</h2>
          <span className="text-xs text-muted">
            {separation?.backend}/{separation?.model}
          </span>
        </div>
        <p className="mt-1 text-sm text-muted">Pick the parts you want written out as tab.</p>

        <ul className="mt-4 grid gap-3 sm:grid-cols-2">
          {stemsAvailable.map((stem) => (
            <li key={stem} className="rounded-lg border border-edge bg-panel p-4">
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={selected.has(stem)}
                  onChange={() => toggle(stem)}
                />
                <span className="font-medium">{STEM_LABELS[stem]}</span>
              </label>

              {stem !== "drums" && selected.has(stem) ? (
                <select
                  aria-label={`${STEM_LABELS[stem]} tuning`}
                  className="mt-3 w-full rounded border border-edge bg-ink px-2 py-1.5 text-sm"
                  value={chosenTuning[stem] ?? ""}
                  onChange={(event) =>
                    setChosenTuning((current) => ({ ...current, [stem]: event.target.value }))
                  }
                >
                  <option value="">Default tuning</option>
                  {Object.entries(tunings).map(([key, tuning]) => (
                    <option key={key} value={key}>
                      {tuning.name}
                    </option>
                  ))}
                </select>
              ) : null}
            </li>
          ))}
        </ul>

        <div className="mt-5 flex items-center gap-4">
          <button
            onClick={transcribe}
            disabled={selected.size === 0}
            className="rounded-lg bg-accent px-5 py-2.5 font-semibold text-ink disabled:opacity-40"
          >
            Transcribe {selected.size || ""} stem{selected.size === 1 ? "" : "s"}
          </button>
          <button onClick={deleteTrack} className="text-sm text-muted underline hover:text-white">
            Delete this track and its stems now
          </button>
        </div>
      </section>

      {artifacts.length > 0 ? (
        <section>
          <h2 className="text-lg font-semibold">Tablature</h2>
          <div className="mt-4 space-y-6">
            {artifacts.map((artifact) => (
              <TabPreview key={artifact.stem} artifact={artifact} trackId={trackId} />
            ))}
          </div>
          <a
            href={api.x0rUrl(trackId)}
            className="mt-6 inline-block text-sm text-accent underline"
            download
          >
            Download the full .x0r session file
          </a>
        </section>
      ) : null}
    </div>
  );
}

function ProgressPanel({ job, phase }: { job: Job | null; phase: Phase }) {
  const percent = Math.round((job?.progress ?? 0) * 100);
  return (
    <div className="rounded-lg border border-edge bg-panel p-8">
      <h2 className="font-semibold">
        {phase === "separating" ? "Splitting the track into stems…" : "Writing the tab…"}
      </h2>
      <p className="mt-1 text-sm text-muted">{job?.message ?? "starting"}</p>
      <div
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        className="mt-4 h-2 overflow-hidden rounded bg-edge"
      >
        <div className="h-full bg-accent transition-all" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
