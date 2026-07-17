export function SkeletonCard({ className = '' }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded-xl bg-[#12121a] border border-[#1e1e2e] p-6 ${className}`}>
      <div className="h-4 bg-gray-700/50 rounded w-1/3 mb-3" />
      <div className="h-8 bg-gray-700/50 rounded w-1/2 mb-2" />
      <div className="h-3 bg-gray-700/30 rounded w-2/3" />
    </div>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="animate-pulse space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-12 bg-gray-700/20 rounded" />
      ))}
    </div>
  );
}
