import { useEffect, useRef, useState } from "react";

export default function usePolling(fetchFn, intervalMs = 5000) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const savedFn = useRef(fetchFn);
  savedFn.current = fetchFn;

  const refresh = () => {
    savedFn
      .current()
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e.message));
  };

  useEffect(() => {
    refresh();
    if (intervalMs <= 0) return;
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return { data, error, refresh };
}
