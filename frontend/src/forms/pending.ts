/** Whatever is typed but not saved yet, so that Continue, Submit and Send save
 *  it first and stay put if that fails (owner, 2026-11-20: intake #1 lost its
 *  door code to a Save button nobody pressed). Each field that holds its own
 *  value until it is saved, a sensitive value above all, adds itself here. */
import { createContext, useContext, useEffect, useRef } from "react";

export interface Saver {
  /** Save now whatever isn't saved; false if that failed. */
  flush(): Promise<boolean>;
  /** Something is typed that isn't saved yet. */
  dirty(): boolean;
}

export class Pending {
  private savers = new Set<Saver>();

  add(saver: Saver): () => void {
    this.savers.add(saver);
    return () => { this.savers.delete(saver); };
  }

  dirty(): boolean {
    return [...this.savers].some((s) => s.dirty());
  }

  /** Every saver at once; true only if all of them saved. */
  async flush(): Promise<boolean> {
    const results = await Promise.all([...this.savers].map((s) => s.flush()
      .catch(() => false)));
    return results.every(Boolean);
  }
}

export const PendingContext = createContext<Pending | null>(null);

/** Adds a saver for as long as the component is on the screen. The saver may
 *  change on every render; the latest one is used. */
export function useSaver(saver: Saver): void {
  const pending = useContext(PendingContext);
  const latest = useRef(saver);
  latest.current = saver;
  useEffect(() => pending?.add({
    flush: () => latest.current.flush(),
    dirty: () => latest.current.dirty(),
  }), [pending]);
}
