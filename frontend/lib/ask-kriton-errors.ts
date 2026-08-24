export type AskKritonFailure = {
  status: number;
  message: string;
};

export function isRetryableAskKritonStatus(status: number | undefined): boolean {
  return status === 0 || status === 408 || status === 429 || (status !== undefined && status >= 500);
}

type ErrorLike = {
  name?: unknown;
  message?: unknown;
  status?: unknown;
};

/** Convert transport and HTTP failures into actionable, customer-safe copy.
 * This stays in the client boundary: it does not alter orchestration routes,
 * retry policy, or the backend response contract. */
export function classifyAskKritonFailure(
  error: unknown,
  online: boolean = typeof navigator === "undefined" ? true : navigator.onLine,
): AskKritonFailure | null {
  const candidate = error && typeof error === "object" ? (error as ErrorLike) : null;

  if (candidate?.name === "AbortError") {
    return {
      status: 408,
      message: "This request exceeded the two-minute response limit. Please try again.",
    };
  }

  if (!online) {
    return {
      status: 0,
      message: "Your device appears to be offline. Check your connection and try again.",
    };
  }

  const status = typeof candidate?.status === "number" ? candidate.status : null;
  if (status === 401) {
    return { status, message: "Your session has expired. Please sign in again." };
  }
  if (status === 408) {
    return { status, message: "Kriton could not complete the request in time. Please try again." };
  }
  if (status === 429) {
    return { status, message: "Kriton is temporarily busy. Please wait a moment and try again." };
  }
  if (status === 502 || status === 503 || status === 504) {
    return {
      status,
      message: "Kriton or a required data provider is temporarily unavailable. Please try again shortly.",
    };
  }
  if (status !== null && status >= 500) {
    return {
      status,
      message: "Kriton encountered a temporary service problem. Please try again shortly.",
    };
  }
  if (status !== null) {
    const safeMessage = typeof candidate?.message === "string" && candidate.message.trim()
      ? candidate.message
      : "Kriton could not process this request.";
    return { status, message: safeMessage };
  }

  // Browser fetch rejects with TypeError for DNS, CORS, refused connections,
  // and other network failures. Do not mislabel these as orchestration errors.
  if (error instanceof TypeError) {
    return {
      status: 0,
      message: "Kriton could not reach the service. Check your connection and try again.",
    };
  }

  return null;
}
