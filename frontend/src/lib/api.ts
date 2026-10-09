export class ApiError extends Error {
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

const API_BASE_URL = "/api/v1";

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
};

let currentOrganizationId: string | null = null;

/**
 * Sets the organization ID used by tenant-scoped API requests.
 * Pass null when no organization is selected or the user signs out.
 */
export function setCurrentOrganizationId(
  organizationId: string | null,
): void {
  currentOrganizationId = organizationId;
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers(options.headers);

  headers.set("Accept", "application/json");

  const isAuthenticationRequest = path.startsWith("/auth");
  const isOrganizationDiscoveryRequest = path.startsWith("/organizations");

  if (
    !isAuthenticationRequest &&
    !isOrganizationDiscoveryRequest &&
    currentOrganizationId
  ) {
    headers.set("X-Organization-ID", currentOrganizationId);
  }

  let body: BodyInit | undefined;

  if (options.body !== undefined) {
    if (
      options.body instanceof FormData ||
      options.body instanceof URLSearchParams ||
      typeof options.body === "string"
    ) {
      body = options.body;
    } else {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.body);
    }
  }

  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
      body,
      credentials: "include",
    });
  } catch {
    throw new ApiError(
      "Unable to connect to DealFlow. Check that the backend is running.",
      0,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  let responseData: unknown;

  if (contentType.includes("application/json")) {
    try {
      responseData = await response.json();
    } catch {
      responseData = undefined;
    }
  } else {
    responseData = await response.text().catch(() => "");
  }

  if (!response.ok) {
    const details =
      typeof responseData === "object" && responseData !== null
        ? (responseData as { detail?: unknown }).detail
        : undefined;

    let message: string;

    if (typeof details === "string") {
      message = details;
    } else if (Array.isArray(details)) {
      message = details
        .map((item) => {
          if (
            typeof item === "object" &&
            item !== null &&
            "msg" in item &&
            typeof item.msg === "string"
          ) {
            return item.msg;
          }

          return "The request contains invalid data.";
        })
        .join(" ");
    } else if (response.status === 401) {
      message = "Your session has expired. Please sign in again.";
    } else if (response.status === 403) {
      message = "You don't have permission to perform this action.";
    } else {
      message = `The request failed (${response.status}).`;
    }

    throw new ApiError(message, response.status, responseData);
  }

  return responseData as T;
}

export const api = {
  get<T>(
    path: string,
    options?: Omit<RequestOptions, "method" | "body">,
  ): Promise<T> {
    return request<T>(path, {
      ...options,
      method: "GET",
    });
  },

  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "POST",
      body,
    });
  },

  patch<T>(path: string, body: unknown): Promise<T> {
    return request<T>(path, {
      method: "PATCH",
      body,
    });
  },

  delete<T>(path: string): Promise<T> {
    return request<T>(path, {
      method: "DELETE",
    });
  },
};