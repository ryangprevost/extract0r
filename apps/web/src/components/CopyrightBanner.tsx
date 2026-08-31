import Link from "next/link";

/**
 * The site-wide copyright notice.
 *
 * Rendered in the footer of every page and, in `variant="inline"`, immediately above
 * the upload control. Deliberately not dismissible.
 */
export function CopyrightBanner({ variant = "footer" }: { variant?: "footer" | "inline" }) {
  const inline = variant === "inline";
  return (
    <div
      className={
        inline
          ? "rounded-lg border border-warn/40 bg-warn/5 p-4 text-sm"
          : "text-xs leading-relaxed text-muted"
      }
    >
      <p className={inline ? "font-semibold text-warn" : "font-semibold"}>
        Only upload audio you have the right to use.
      </p>
      <p className="mt-1">
        Recordings and the songs underneath them are usually copyrighted. Separating,
        transcribing, and remixing all create derivative works. Extract0r does not grant you a
        licence to anything, and it will not process audio obtained by breaking a streaming
        service&rsquo;s terms or any DRM.
      </p>
      <p className="mt-2">
        <Link href="/legal/terms" className="underline hover:text-white">
          Terms of use
        </Link>
        {" · "}
        <Link href="/legal/dmca" className="underline hover:text-white">
          Copyright &amp; DMCA
        </Link>
      </p>
    </div>
  );
}
