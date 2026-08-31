"use client";

import { api } from "@/lib/api";
import { STEM_LABELS, type TabArtifact } from "@/lib/types";

export function TabPreview({ artifact, trackId }: { artifact: TabArtifact; trackId: string }) {
  // Separation is never perfect, so some notes land outside the instrument's range.
  // Saying so is better than quietly handing back a thinner tab than the count implies.
  const adjusted = artifact.dropped_count + artifact.folded_count;

  return (
    <article className="rounded-lg border border-edge bg-panel">
      <header className="flex items-center justify-between border-b border-edge px-4 py-3">
        <h3 className="font-medium">
          {STEM_LABELS[artifact.stem]}{" "}
          <span className="text-xs text-muted">
            {artifact.note_count} notes · {artifact.notation.replace("_", " ")}
          </span>
        </h3>
        <a
          href={api.tabUrl(trackId, artifact.stem)}
          download={`${artifact.stem}.txt`}
          className="text-sm text-accent underline"
        >
          Download .txt
        </a>
      </header>
      {adjusted > 0 ? (
        <p className="border-b border-edge px-4 py-2 text-xs text-muted">
          {artifact.dropped_count > 0
            ? `${artifact.dropped_count} note${artifact.dropped_count === 1 ? "" : "s"} outside this instrument's range were left out`
            : null}
          {artifact.dropped_count > 0 && artifact.folded_count > 0 ? " · " : null}
          {artifact.folded_count > 0
            ? `${artifact.folded_count} moved by an octave to fit`
            : null}
          . Usually bleed from another stem.
        </p>
      ) : null}
      <pre className="tab-output p-4">{artifact.preview}</pre>
    </article>
  );
}
