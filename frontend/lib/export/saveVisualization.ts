import { createSavedVisualization, getAuthToken, type SavedVisualizationCreateRequest } from "@/lib/api";

/** Persists the validated visualization payload the app already rendered —
 * never a PNG snapshot, never LLM reasoning fields (the payload types don't
 * define any). One Idempotency-Key per logical save attempt so retries of
 * the exact same click never create a duplicate row server-side. */
export async function saveVisualization(
  payload: SavedVisualizationCreateRequest,
  idempotencyKey: string,
): Promise<boolean> {
  const token = getAuthToken();
  await createSavedVisualization(token, payload, idempotencyKey);
  return true;
}
