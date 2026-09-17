import { useState } from "react";

/**
 * One choice, remembered for this person in this browser.
 *
 * **Per user**, because two people share a browser on the practice's laptop and
 * one narrowing Work to a client — or collapsing a goal — should not narrow it
 * for the other. `localStorage` only: a per-viewer convenience, not state the
 * server should carry, and every access is wrapped because a private window or
 * blocked site data makes it throw.
 *
 * The fallback is returned whenever nothing is stored or storage is unreadable,
 * so a screen that cannot remember still renders its default rather than
 * nothing at all.
 */
export function useRemembered<T>(key: string, fallback: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const saved = window.localStorage.getItem(key);
      return saved === null ? fallback : (JSON.parse(saved) as T);
    } catch {
      return fallback;
    }
  });
  const remember = (next: T) => {
    setValue(next);
    try {
      window.localStorage.setItem(key, JSON.stringify(next));
    } catch {
      /* The screen still works; only the memory of the choice is lost. */
    }
  };
  return [value, remember];
}
