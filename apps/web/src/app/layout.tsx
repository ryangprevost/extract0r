import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { CopyrightBanner } from "@/components/CopyrightBanner";

export const metadata: Metadata = {
  title: "Extract0r",
  description: "Split a song into stems, transcribe them to tab, remix and master.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <header className="border-b border-edge">
          <nav className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-4">
            <Link href="/" className="font-mono text-lg font-bold tracking-tight">
              extract<span className="text-accent">0</span>r
            </Link>
            <div className="ml-auto flex gap-5 text-sm text-muted">
              <Link href="/legal/terms" className="hover:text-white">
                Terms
              </Link>
              <Link href="/legal/dmca" className="hover:text-white">
                Copyright
              </Link>
            </div>
          </nav>
        </header>

        <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>

        <footer className="mt-16 border-t border-edge">
          <div className="mx-auto max-w-5xl px-6 py-8">
            <CopyrightBanner />
          </div>
        </footer>
      </body>
    </html>
  );
}
