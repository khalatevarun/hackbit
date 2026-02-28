/**
 * Lightweight Groq API client for server-side Next.js routes.
 * Uses llama-3.1-8b-instant — fast enough for classification (~300ms).
 */

const GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions";
const GROQ_MODEL = "llama-3.1-8b-instant";

export async function groqComplete(
  systemPrompt: string,
  userMessage: string,
): Promise<string> {
  const res = await fetch(GROQ_API_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.GROQ_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: GROQ_MODEL,
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: userMessage },
      ],
      temperature: 0.1,
      max_tokens: 512,
    }),
  });

  if (!res.ok) {
    throw new Error(`Groq API error ${res.status}: ${await res.text()}`);
  }

  const data = await res.json();
  return data.choices[0].message.content as string;
}

export function parseGroqJSON<T>(text: string): T {
  const cleaned = text
    .replace(/^```(?:json)?\s*/m, "")
    .replace(/\s*```\s*$/m, "")
    .trim();
  return JSON.parse(cleaned) as T;
}
