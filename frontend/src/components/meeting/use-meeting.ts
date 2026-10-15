"use client";

import { useParams } from "next/navigation";
import { useApi } from "@/lib/hooks";
import type { Meeting } from "@/lib/types";

export function useMeetingId(): string {
  const params = useParams<{ id: string }>();
  return params.id;
}

export function useMeeting() {
  const id = useMeetingId();
  return { id, ...useApi<Meeting>(`/meetings/${id}`) };
}
