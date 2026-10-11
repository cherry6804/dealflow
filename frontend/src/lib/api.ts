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

type DuplicateContactDetail = {
  code?: unknown;
  message?: unknown;
  fields?: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getDuplicateContactMessage(
  detail: DuplicateContactDetail,
): string | null {
  if (detail.code !== "duplicate_contact") {
    return null;
  }

  const fields = Array.isArray(detail.fields)
    ? detail.fields.filter(
        (field): field is string =>
          field === "email" || field === "phone",
      )
    : [];

  const hasEmail = fields.includes("email");
  const hasPhone = fields.includes("phone");

  if (hasEmail && hasPhone) {
    return "A contact with this email address and phone number already exists in your organization. Please check the details and try again.";
  }

  if (hasEmail) {
    return "A contact with this email address already exists in your organization. Please use a different email address.";
  }

  if (hasPhone) {
    return "A contact with this phone number already exists in your organization. Please use a different phone number.";
  }

  if (typeof detail.message === "string" && detail.message.trim()) {
    return detail.message;
  }

  return "This contact already exists in your organization. Please check the email address and phone number.";
}

/**
 * Sets the organization ID used by tenant-scoped API requests.
 * Pass null when no organization is selected or the user signs out.
 */
export function setCurrentOrganizationId(
  organizationId: string | null,
): void {
  currentOrganizationId = organizationId;
}

function buildHeaders(
  path: string,
  suppliedHeaders?: HeadersInit,
): Headers {
  const headers = new Headers(suppliedHeaders);

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

  return headers;
}

function getErrorMessage(
  responseStatus: number,
  responseData: unknown,
): string {
  const detail = isRecord(responseData)
    ? responseData.detail
    : undefined;

  if (isRecord(detail)) {
    const duplicateMessage = getDuplicateContactMessage(detail);

    if (duplicateMessage) {
      return duplicateMessage;
    }

    if (typeof detail.message === "string" && detail.message.trim()) {
      return detail.message;
    }
  }

  if (typeof detail === "string") {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
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
  }

  if (responseStatus === 401) {
    return "Your session has expired. Please sign in again.";
  }

  if (responseStatus === 403) {
    return "You don't have permission to perform this action.";
  }

  return `The request failed (${responseStatus}).`;
}

async function readErrorResponse(
  response: Response,
): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    try {
      return await response.json();
    } catch {
      return undefined;
    }
  }

  return response.text().catch(() => "");
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers = buildHeaders(path, options.headers);

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
    throw new ApiError(
      getErrorMessage(response.status, responseData),
      response.status,
      responseData,
    );
  }

  return responseData as T;
}

async function download(
  path: string,
  filename: string,
): Promise<void> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "GET",
      headers: buildHeaders(path),
      credentials: "include",
    });
  } catch {
    throw new ApiError(
      "Unable to connect to DealFlow. Check that the backend is running.",
      0,
    );
  }

  if (!response.ok) {
    const responseData = await readErrorResponse(response);

    throw new ApiError(
      getErrorMessage(response.status, responseData),
      response.status,
      responseData,
    );
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = objectUrl;
  link.download = filename;
  link.style.display = "none";

  document.body.appendChild(link);

  try {
    link.click();
  } finally {
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }
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

  download(path: string, filename: string): Promise<void> {
    return download(path, filename);
  },
};