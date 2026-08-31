import { UploadPanel } from "@/components/UploadPanel";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";
const DEFAULT_MAX_UPLOAD_MB = 60;

/** Ask the API for its own limits so the copy never drifts from the server config. */
async function getMaxUploadMb(): Promise<number> {
  try {
    const response = await fetch(`${API_ORIGIN}/api/v1/capabilities`, { cache: "no-store" });
    if (!response.ok) return DEFAULT_MAX_UPLOAD_MB;
    const body = await response.json();
    return body?.limits?.max_upload_mb ?? DEFAULT_MAX_UPLOAD_MB;
  } catch {
    return DEFAULT_MAX_UPLOAD_MB;
  }
}

export default async function HomePage() {
  const maxUploadMb = await getMaxUploadMb();

  return (
    <div className="space-y-10">
      <section>
        <h1 className="text-3xl font-bold tracking-tight">
          Split it. Read it. <span className="text-accent">Play it.</span>
        </h1>
        <p className="mt-3 max-w-2xl text-muted">
          Extract0r pulls a song apart into drums, bass, vocals, guitar, and keys, then writes
          out playable tablature for the parts you pick. Everything you upload is deleted
          automatically.
        </p>
      </section>

      <UploadPanel maxUploadMb={maxUploadMb} />

      <section className="grid gap-6 sm:grid-cols-3">
        {[
          {
            title: "Real separation",
            body: "Demucs v4 six-stem model, so guitar and piano come out as their own tracks.",
          },
          {
            title: "Tab that reads",
            body: "A fretboard solver picks positions that minimise hand movement, not just the first fret that fits.",
          },
          {
            title: "Portable output",
            body: "Plain .txt per stem, plus a .x0r session file with the exact note timings and provenance.",
          },
        ].map((card) => (
          <div key={card.title} className="rounded-lg border border-edge bg-panel p-5">
            <h2 className="font-semibold">{card.title}</h2>
            <p className="mt-2 text-sm text-muted">{card.body}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
