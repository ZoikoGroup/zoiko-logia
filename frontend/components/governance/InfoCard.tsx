import { Card } from "./Card";

export function InfoCard({ heading, body }: { heading: string; body: string }) {
  return (
    <Card title={heading}>
      <p className="text-sm text-muted leading-relaxed">{body}</p>
    </Card>
  );
}
