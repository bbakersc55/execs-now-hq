import { createContext, createElement, ReactNode, useContext, useMemo } from "react";

/**
 * What this practice calls its goals, projects, tasks and steps (2026-10-15).
 *
 * Each practice names them in Settings → Branding → Wording; the server sends them on
 * `/api/me` as `words`. Screens read them with `useWords()` and never write
 * the four words as fixed text. Capitalization follows the place: `w.task` in
 * a sentence, `w.Task` at its start or on a button, `w.aTask` for "a task" /
 * "an action". The backend twin is apps/tenancy/words.py.
 *
 * Not applied to the platform owner's pages, the code or the API: URLs, field
 * names and the values in stored data keep "task", "project" and so on.
 */
export type WordKind = "goal" | "project" | "task" | "step";
export type WordPairs = Record<WordKind, { singular: string; plural: string }>;

export const WORD_KINDS: WordKind[] = ["goal", "project", "task", "step"];

export const DEFAULT_WORD_PAIRS: WordPairs = {
  goal: { singular: "goal", plural: "goals" },
  project: { singular: "project", plural: "projects" },
  task: { singular: "task", plural: "tasks" },
  step: { singular: "step", plural: "steps" },
};

export interface Words {
  goal: string; goals: string; Goal: string; Goals: string; aGoal: string; AGoal: string;
  project: string; projects: string; Project: string; Projects: string;
  aProject: string; AProject: string;
  task: string; tasks: string; Task: string; Tasks: string; aTask: string; ATask: string;
  step: string; steps: string; Step: string; Steps: string; aStep: string; AStep: string;
  /** The word for a kind, as the place needs it. */
  of: (kind: WordKind, opts?: { plural?: boolean; capital?: boolean }) => string;
  /** "1 task", "3 tasks". */
  count: (n: number, kind: WordKind) => string;
  /** "3 task(s)" while the plural is the word and an s, as these lines always
   *  read; "3 activities" / "1 activity" when the practice's plural is not. */
  counted: (n: number, kind: WordKind) => string;
  /** "were" after `counted`, unless it reads as one ("1 activity was"). */
  were: (n: number, kind: WordKind) => string;
}

export const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const article = (s: string) => (/^[aeiou]/i.test(s) ? "an" : "a");

export function makeWords(pairs?: Partial<WordPairs> | null): Words {
  const p = { ...DEFAULT_WORD_PAIRS, ...(pairs ?? {}) } as WordPairs;
  const one = (k: WordKind) => p[k]?.singular || DEFAULT_WORD_PAIRS[k].singular;
  const many = (k: WordKind) => p[k]?.plural || DEFAULT_WORD_PAIRS[k].plural;
  const forms = (k: WordKind) => ({
    [k]: one(k), [`${k}s`]: many(k), [cap(k)]: cap(one(k)), [`${cap(k)}s`]: cap(many(k)),
    [`a${cap(k)}`]: `${article(one(k))} ${one(k)}`,
    [`A${cap(k)}`]: `${cap(article(one(k)))} ${one(k)}`,
  });
  return {
    ...forms("goal"), ...forms("project"), ...forms("task"), ...forms("step"),
    of: (kind, opts = {}) => {
      const word = opts.plural ? many(kind) : one(kind);
      return opts.capital ? cap(word) : word;
    },
    count: (n, kind) => `${n} ${n === 1 ? one(kind) : many(kind)}`,
    counted: (n, kind) => (many(kind) === `${one(kind)}s` ? `${n} ${one(kind)}(s)`
      : `${n} ${n === 1 ? one(kind) : many(kind)}`),
    were: (n, kind) => (many(kind) !== `${one(kind)}s` && n === 1 ? "was" : "were"),
  } as Words;
}

export const DEFAULT_WORDS = makeWords();

const WordsContext = createContext<Words>(DEFAULT_WORDS);

export function WordsProvider({ pairs, children }: {
  pairs?: Partial<WordPairs> | null; children: ReactNode;
}) {
  const value = useMemo(() => makeWords(pairs), [pairs]);
  return createElement(WordsContext.Provider, { value }, children);
}

/** The practice's words, for the screen being drawn. */
export function useWords(): Words {
  return useContext(WordsContext);
}
