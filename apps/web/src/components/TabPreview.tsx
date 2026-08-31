"use client";

import { api } from "@/lib/api";
import { STEM_LABELS, type TabArtifact } from "@/lib/types";

export function TabPreview({ artifact, trackId }: { artifact: TabArtifact; trackId: string }) {
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
      <pre className="tab-output p-4">{artifact.preview}</pre>
    </article>
  );
}
