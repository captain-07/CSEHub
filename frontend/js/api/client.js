const API_BASE_URL = window.CSEHUB_API_BASE_URL.replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status, details) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export async function request(path, { signal } = {}) {
  let response;
  try {
    response = await fetch(path.startsWith("http") ? path : `${API_BASE_URL}${path}`, {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("CSEHub could not reach the API. Please try again shortly.");
  }

  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const message = response.status === 503
      ? "The learning service is temporarily unavailable. Please try again shortly."
      : body?.detail || body?.message || "Something went wrong while loading this content.";
    throw new ApiError(message, response.status, body);
  }
  return body;
}
