"use client";

import { useSyncExternalStore } from "react";

/** Per-browser display preferences (theme, mascot) plus the live screen's focus mode. */
export interface Prefs {
  theme: "dark" | "light";
  /** Fred the mascot; teams can hide him for client-facing meetings. */
  showFred: boolean;
}

const KEY = "memohub.prefs";
const DEFAULTS: Prefs = { theme: "dark", showFred: true };

let prefs: Prefs | null = null;
let focus = false;
const listeners = new Set<() => void>();

function load(): Prefs {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) {
      const p = JSON.parse(raw) as Partial<Prefs>;
      return { theme: p.theme === "light" ? "light" : "dark", showFred: p.showFred !== false };
    }
  } catch {
    // Storage blocked (private window, policy): fall back to the defaults.
  }
  return DEFAULTS;
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit() {
  listeners.forEach((fn) => fn());
}

export function setPrefs(patch: Partial<Prefs>) {
  prefs = { ...(prefs ?? load()), ...patch };
  document.documentElement.dataset.theme = prefs.theme;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    // Not persisted; still applies for this page view.
  }
  emit();
}

export function usePrefs(): Prefs {
  return useSyncExternalStore(
    subscribe,
    () => (prefs ??= load()),
    () => DEFAULTS,
  );
}

/** Live screen focus mode: the sidebar hides while captions are running. */
export function setFocusMode(on: boolean) {
  if (focus === on) return;
  focus = on;
  emit();
}

export function useFocusMode(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => focus,
    () => false,
  );
}

/** Inline <head> script: applies the saved theme before first paint (no light/dark flash). */
export const THEME_BOOT_SCRIPT = `try{var p=JSON.parse(localStorage.getItem("${KEY}")||"{}");document.documentElement.dataset.theme=p.theme==="light"?"light":"dark"}catch(e){document.documentElement.dataset.theme="dark"}`;
