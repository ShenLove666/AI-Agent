import type {
  AgentProgressPayload,
  CompletionPayload,
  MessageDeltaPayload,
  StreamMetaPayload
} from "@/types";
import { storage } from "@/utils/storage";
import { ApiError } from "@/services/ApiError";

export interface StreamHandlers {
  onMeta?: (payload: StreamMetaPayload) => void;
  onMessage?: (payload: MessageDeltaPayload) => void;
  onThinking?: (payload: MessageDeltaPayload) => void;
  onAgentProgress?: (payload: AgentProgressPayload) => void;
  onFinish?: (payload: CompletionPayload) => void;
  onDone?: () => void;
  onCancel?: (payload: CompletionPayload) => void;
  onReject?: (payload: MessageDeltaPayload) => void;
  onTitle?: (payload: { title: string }) => void;
  onError?: (error: Error) => void;
  onEvent?: (event: string, payload: unknown) => void;
}

export interface StreamOptions {
  url: string;
  method?: "GET" | "POST";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  retryCount?: number;
  retryDelayMs?: number;
}

function parseData(raw: string): unknown {
  if (!raw) return "";
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

async function readSseStream(response: Response, handlers: StreamHandlers, signal?: AbortSignal) {
  if (!response.body) {
    throw new Error("流式响应为空");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let eventName = "message";
  let dataLines: string[] = [];

  const dispatchEvent = () => {
    if (dataLines.length === 0) {
      eventName = "message";
      return;
    }
    const raw = dataLines.join("\n");
    const payload = parseData(raw);
    handlers.onEvent?.(eventName, payload);

    switch (eventName) {
      case "meta":
        handlers.onMeta?.(payload as StreamMetaPayload);
        break;
      case "agent_progress":
        handlers.onAgentProgress?.(payload as AgentProgressPayload);
        break;
      case "message":
        {
          const messagePayload = payload as MessageDeltaPayload;
          if (messagePayload?.type === "think") {
            handlers.onThinking?.(messagePayload);
          }
          handlers.onMessage?.(messagePayload);
        }
        break;
      case "finish":
        handlers.onFinish?.(payload as CompletionPayload);
        break;
      case "done":
        handlers.onDone?.();
        break;
      case "cancel":
        handlers.onCancel?.(payload as CompletionPayload);
        break;
      case "reject":
        handlers.onReject?.(payload as MessageDeltaPayload);
        break;
      case "title":
        handlers.onTitle?.(payload as { title: string });
        break;
      case "error":
        {
          const detail = payload as { error?: string; messageId?: string; code?: string };
          const error = new ApiError(String(detail?.error || payload), {
            messageId: detail?.messageId,
            code: detail?.code
          });
          handlers.onError?.(error);
        }
        break;
      default:
        break;
    }

    eventName = "message";
    dataLines = [];
  };

  while (true) {
    if (signal?.aborted) {
      reader.cancel();
      break;
    }
    const { value, done } = await reader.read();
    if (done) {
      dispatchEvent();
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line) {
        dispatchEvent();
        continue;
      }
      if (line.startsWith(":")) {
        continue;
      }
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
        continue;
      }
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }
  }
}

async function streamWithRetry(
  options: StreamOptions,
  handlers: StreamHandlers
): Promise<void> {
  const { url, headers, signal, method = "GET", body } = options;
  const retryCount = options.retryCount ?? 2;
  const retryDelayMs = options.retryDelayMs ?? 600;

  let attempt = 0;
  while (attempt <= retryCount) {
    try {
      const response = await fetch(url, {
        method,
        headers: {
          Accept: "text/event-stream",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
          ...headers
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal
      });

      if (!response.ok) {
        if (response.status === 401) {
          storage.clearAuth();
          window.setTimeout(() => {
            if (window.location.pathname !== "/login") window.location.href = "/login";
          }, 800);
          throw new ApiError("登录已失效，请重新登录", { status: 401 });
        }
        let detail: { error?: { message?: string; code?: string; details?: unknown }; traceId?: string } = {};
        try {
          detail = await response.json();
        } catch {
          // Non-JSON reverse-proxy errors still retain the HTTP status.
        }
        throw new ApiError(detail.error?.message || `SSE 请求失败（${response.status}）`, {
          status: response.status,
          code: detail.error?.code,
          details: detail.error?.details,
          traceId: detail.traceId
        });
      }

      await readSseStream(response, handlers, signal);
      return;
    } catch (error) {
      const err = error as Error;
      if (signal?.aborted) {
        throw err;
      }
      if (err.message === "登录已失效，请重新登录") {
        throw err;
      }
      if (attempt >= retryCount) {
        throw err;
      }
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs * Math.pow(2, attempt)));
      attempt += 1;
    }
  }
}

export function createStreamResponse(options: StreamOptions, handlers: StreamHandlers) {
  const controller = new AbortController();
  const mergedOptions = {
    ...options,
    signal: options.signal ?? controller.signal
  };

  return {
    start: () => streamWithRetry(mergedOptions, handlers),
    cancel: () => controller.abort()
  };
}
