import { vi, type Messages } from "./vi";

// Register additional locales here (e.g. en, ja) — each must satisfy Messages.
const locales: Record<string, Messages> = { vi };

export const defaultLocale = "vi";

export function getMessages(locale: string = defaultLocale): Messages {
  return locales[locale] ?? vi;
}

export const t = getMessages();
export type { Messages };
