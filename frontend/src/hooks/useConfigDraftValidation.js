import { useCallback, useEffect, useMemo, useState } from "react";
import { post } from "../api";

export function draftsEqual(a, b) {
  if (!a || !b) return false;
  return JSON.stringify(a) === JSON.stringify(b);
}

export default function useConfigDraftValidation(draft, enabled = true) {
  const [validation, setValidation] = useState(null);

  const validate = useCallback(async () => {
    if (!enabled || !draft) return null;
    try {
      const result = await post("/api/config/validate-draft", { updates: draft });
      setValidation(result);
      return result;
    } catch (e) {
      const fallback = { valid: false, errors: [e.message], live_trading_ready: false, live_trading_errors: [] };
      setValidation(fallback);
      return fallback;
    }
  }, [draft, enabled]);

  useEffect(() => {
    if (!enabled) return undefined;
    const id = setTimeout(() => {
      validate();
    }, 300);
    return () => clearTimeout(id);
  }, [validate, enabled]);

  const liveErrors = useMemo(() => {
    if (!validation) return [];
    if (validation.live_trading_requested && !validation.live_trading_ready) {
      return validation.live_trading_errors || [];
    }
    return validation.errors || [];
  }, [validation]);

  return { validation, liveErrors, validate };
}
