export interface ApiErrorOptions {
  status?: number;
  code?: string;
  details?: unknown;
  traceId?: string;
  messageId?: string;
}

export class ApiError extends Error {
  status?: number;
  code?: string;
  details?: unknown;
  traceId?: string;
  messageId?: string;

  constructor(message: string, options: ApiErrorOptions = {}) {
    super(message);
    this.name = "ApiError";
    Object.assign(this, options);
  }
}
