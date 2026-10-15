import clsx, { type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Joins class names; later Tailwind utilities override conflicting earlier ones (e.g. w-40 over w-full). */
export function cn(...values: ClassValue[]): string {
  return twMerge(clsx(values));
}
