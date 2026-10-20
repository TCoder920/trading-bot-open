export default function ErrorState({ message, onRetry }) {
  return (
    <div className="error-state">
      <p>{message || "Something went wrong."}</p>
      {onRetry && (
        <button className="btn btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
