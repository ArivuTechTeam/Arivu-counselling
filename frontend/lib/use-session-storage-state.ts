"use client";

import { Dispatch, SetStateAction, useEffect, useState } from "react";

/**
 * Keeps non-sensitive UI preferences across refreshes in the current browser tab.
 * Callers should never use this for passwords, credentials, uploaded File objects,
 * or destructive confirmation state.
 */
export function useSessionStorageState<T>(
  key: string,
  initialValue: T,
  isValid?: (value: unknown) => value is T,
): [T, Dispatch<SetStateAction<T>>, boolean] {
  const [value, setValue] = useState<T>(initialValue);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const saved = window.sessionStorage.getItem(key);
      if (saved !== null) {
        const parsed: unknown = JSON.parse(saved);
        if (!isValid || isValid(parsed)) setValue(parsed as T);
      }
    } catch {
      // Continue with the page default when storage is unavailable or invalid.
    } finally {
      setHydrated(true);
    }
    // Hydrate only when the storage namespace changes. Validators are deliberately
    // not dependencies because callers may supply an inline predicate.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    if (!hydrated) return;
    try {
      const serialized = JSON.stringify(value);
      if (serialized === undefined) window.sessionStorage.removeItem(key);
      else window.sessionStorage.setItem(key, serialized);
    } catch {
      // The live UI remains usable when browser storage is unavailable.
    }
  }, [hydrated, key, value]);

  return [value, setValue, hydrated];
}
