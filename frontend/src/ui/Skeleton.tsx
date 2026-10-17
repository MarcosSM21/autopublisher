interface SkeletonProps {
  /** Placeholder rows; they reserve space so content does not jump in. */
  lines?: number;
  /** What is loading, announced once to assistive technology. */
  label?: string;
}

/** Loading placeholder: the container is busy, the blocks are hidden. */
function Skeleton({ lines = 3, label = "Loading…" }: SkeletonProps) {
  return (
    <div className="ap-skeleton" role="status" aria-busy="true">
      <span className="ap-visually-hidden">{label}</span>
      {Array.from({ length: lines }, (_, index) => (
        <span key={index} className="ap-skeleton__line" aria-hidden="true" />
      ))}
    </div>
  );
}

export default Skeleton;
