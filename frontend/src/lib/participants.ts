export function parseParticipants(text: string): { display_name: string; organization: string | null }[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, org] = line.split("|").map((s) => s.trim());
      return { display_name: name.slice(0, 200), organization: org ? org.slice(0, 200) : null };
    });
}
