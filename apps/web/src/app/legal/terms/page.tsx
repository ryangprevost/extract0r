export const metadata = { title: "Terms of use · Extract0r" };

// Placeholder copy pending review by a lawyer (see EPIC-06 / X0R-604).
const SECTIONS = [
  {
    heading: "What Extract0r does",
    body: "Extract0r takes an audio file you upload, separates it into instrument stems, and produces transcriptions and remixes from those stems. Every one of those outputs is derived from your upload.",
  },
  {
    heading: "What you promise when you upload",
    body: "That you own the recording, hold a licence covering this use, or that your use is otherwise permitted by law; that you did not obtain the file by circumventing DRM or breaching a streaming service's terms; and that you will not distribute Extract0r's output from someone else's recording without permission.",
  },
  {
    heading: "What Extract0r does not give you",
    body: "No licence, no permission, and no legal opinion. A transcription of a copyrighted song is itself a derivative work of that composition. Private study is often argued to be fair use in the United States, but fair use is a defence decided case by case, not a permission slip, and other countries treat private copying differently.",
  },
  {
    heading: "How long we keep your audio",
    body: "Uploads and everything derived from them are deleted automatically after the retention window shown on the studio screen. You can delete a track and its stems immediately from that screen at any time.",
  },
  {
    heading: "Accuracy",
    body: "Automatic transcription is approximate. Expect wrong octaves, missed notes in dense passages, and fingerings that a human would voice differently. Treat the output as a starting point, not a published score.",
  },
  {
    heading: "Enforcement",
    body: "We may refuse or stop processing any upload, and we remove material in response to valid copyright notices. Repeat infringers lose access.",
  },
];

export default function TermsPage() {
  return (
    <article className="prose-invert max-w-3xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Terms of use</h1>
        <p className="mt-1 text-sm text-muted">Version 2026-08-31</p>
      </div>

      <p className="rounded-lg border border-warn/40 bg-warn/5 p-4 text-sm text-warn">
        This page is placeholder copy written by engineers. Have a lawyer review it before
        Extract0r accepts uploads from anyone but you.
      </p>

      {SECTIONS.map((section) => (
        <section key={section.heading}>
          <h2 className="font-semibold">{section.heading}</h2>
          <p className="mt-2 text-sm leading-relaxed text-muted">{section.body}</p>
        </section>
      ))}
    </article>
  );
}
