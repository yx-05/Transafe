export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger";

const STATUS_TONES: Record<string, BadgeTone> = {
  CANDIDATE: "warning",
  PENDING_VALIDATION: "warning",
  APPROVED: "success",
  ACTIVE: "success",
  PUBLISHED: "success",
  DRAFT: "info",
  SUPERSEDED: "neutral",
  ARCHIVED: "neutral",
  REJECTED: "danger",
  ROLLED_BACK: "danger",
  NORMAL: "neutral",
  OBSERVED: "warning",
  CLUSTERED: "danger",
  LOW: "neutral",
  MEDIUM: "info",
  HIGH: "warning",
  CRITICAL: "danger",
  info: "info",
  warning: "warning",
  critical: "danger",
};

export function toneFor(label: string): BadgeTone {
  return STATUS_TONES[label] ?? "neutral";
}

interface Props {
  label: string;
  tone?: BadgeTone;
  title?: string;
}

export function StatusBadge({ label, tone, title }: Props) {
  const resolved = tone ?? toneFor(label);
  return (
    <span className={`status-badge tone-${resolved}`} title={title} data-tone={resolved}>
      {label}
    </span>
  );
}

export default StatusBadge;
