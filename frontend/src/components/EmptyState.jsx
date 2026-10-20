export default function EmptyState({ message = "No data yet." }) {
  return <div className="empty-state">{message}</div>;
}
