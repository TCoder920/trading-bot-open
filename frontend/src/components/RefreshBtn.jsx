export default function RefreshBtn({ onClick, label = "Refresh" }) {
  return (
    <button className="btn btn-sm" onClick={onClick}>
      {label}
    </button>
  );
}
