import { StudioClient } from "@/components/StudioClient";

export default async function StudioPage({ params }: { params: Promise<{ trackId: string }> }) {
  const { trackId } = await params;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Studio</h1>
        <p className="font-mono text-xs text-muted">track {trackId}</p>
      </div>
      <StudioClient trackId={trackId} />
    </div>
  );
}
