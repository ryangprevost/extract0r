export const metadata = { title: "Copyright & DMCA · Extract0r" };

const NOTICE_ELEMENTS = [
  "Identification of the copyrighted work you say has been infringed.",
  "Identification of the material at issue and enough detail for us to locate it.",
  "Your name, address, telephone number, and email address.",
  "A statement that you believe in good faith the use is not authorised by the rights holder, its agent, or the law.",
  "A statement, under penalty of perjury, that the information is accurate and that you are the rights holder or authorised to act on their behalf.",
  "Your physical or electronic signature.",
];

export default function DmcaPage() {
  return (
    <article className="max-w-3xl space-y-8">
      <h1 className="text-2xl font-bold">Copyright &amp; DMCA</h1>

      <section>
        <h2 className="font-semibold">Our position</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          Extract0r is a processing tool. It does not host a catalogue, it does not let users
          search for or share other people&rsquo;s uploads, and every upload is deleted after a
          short retention window. Uploaders confirm they hold the rights to their audio before
          anything is processed.
        </p>
      </section>

      <section>
        <h2 className="font-semibold">Sending a notice</h2>
        <p className="mt-2 text-sm text-muted">A notice should include:</p>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-muted">
          {NOTICE_ELEMENTS.map((element) => (
            <li key={element}>{element}</li>
          ))}
        </ol>
        <p className="mt-4 text-sm text-muted">
          Send it to the address configured as <code className="font-mono">DMCA_CONTACT_EMAIL</code>{" "}
          for this deployment.
        </p>
      </section>

      <section>
        <h2 className="font-semibold">Counter-notices and repeat infringers</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          If we remove material you believe was removed in error, you may send a counter-notice
          with your contact details, a statement under penalty of perjury that the removal was a
          mistake, and consent to jurisdiction. Accounts that repeatedly draw valid notices are
          terminated.
        </p>
      </section>
    </article>
  );
}
