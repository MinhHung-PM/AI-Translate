"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { Job } from "./types";

type Query = Parameters<typeof api.get>[1];

interface State<T> {
  key: string | null;
  data: T | null;
  error: ApiError | null;
}

function toApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError(0, "network", String(err));
}

/** Fetch JSON from the API; refetches when `path` or `query` changes. Pass null to skip. */
export function useApi<T>(path: string | null, query?: Query) {
  const queryKey = JSON.stringify(query ?? {});
  const key = path === null ? null : `${path}?${queryKey}`;
  const [state, setState] = useState<State<T>>({ key: null, data: null, error: null });
  // The key currently wanted: a slower response for an older key (e.g. a filter typed
  // character by character) must not overwrite the newer one.
  const wanted = useRef(key);

  const load = useCallback((): Promise<void> => {
    if (path === null) return Promise.resolve();
    return api.get<T>(path, JSON.parse(queryKey) as Query).then(
      (data) => {
        if (wanted.current === key) setState({ key, data, error: null });
      },
      (err: unknown) => {
        if (wanted.current === key) setState((s) => ({ key, data: s.data, error: toApiError(err) }));
      },
    );
  }, [path, queryKey, key]);

  useEffect(() => {
    wanted.current = key;
    void load();
  }, [load, key]);

  const setData = useCallback((data: T) => setState((s) => ({ ...s, data })), []);
  return {
    data: state.data,
    error: state.key === key ? state.error : null,
    loading: key !== null && state.key !== key,
    reload: load,
    setData,
  };
}

/** Poll a background job until it reaches a terminal state. */
export function useJob(jobId: string | null, onDone?: (job: Job) => void, intervalMs = 1000) {
  const [job, setJob] = useState<Job | null>(null);
  const doneRef = useRef(onDone);
  useEffect(() => {
    doneRef.current = onDone;
  });

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      api.get<Job>(`/jobs/${jobId}`).then(
        (j) => {
          if (cancelled) return;
          setJob(j);
          if (["succeeded", "failed", "cancelled"].includes(j.status)) doneRef.current?.(j);
          else timer = setTimeout(tick, intervalMs);
        },
        () => {
          if (!cancelled) timer = setTimeout(tick, intervalMs);
        },
      );
    };
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, intervalMs]);

  return jobId ? job : null;
}
