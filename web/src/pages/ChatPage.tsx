import * as React from "react";
import { LoaderCircle, TriangleAlert } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import { ChatInput } from "@/components/chat/ChatInput";
import { MessageList } from "@/components/chat/MessageList";
import { SourcesPanel } from "@/components/chat/SourcesPanel";
import { MainLayout } from "@/components/layout/MainLayout";
import { useChatStore } from "@/stores/chatStore";

export function ChatPage() {
  const navigate = useNavigate();
  const { sessionId } = useParams<{ sessionId: string }>();
  const {
    messages,
    isLoading,
    isStreaming,
    currentSessionId,
    sessions,
    isCreatingNew,
    fetchSessions,
    selectSession,
    createSession
  } = useChatStore();
  const showWelcome = messages.length === 0 && !isLoading;
  const showEmptyLoading = messages.length === 0 && isLoading;
  const lastMessage = messages[messages.length - 1];
  const lastMessageFailed = lastMessage?.status === "error" || lastMessage?.messageStatus === "ERROR";
  const [sessionsReady, setSessionsReady] = React.useState(false);
  const sessionExists = React.useMemo(() => {
    if (!sessionId) return false;
    return sessions.some((session) => session.id === sessionId);
  }, [sessionId, sessions]);

  React.useEffect(() => {
    let active = true;
    fetchSessions()
      .catch(() => null)
      .finally(() => {
        if (active) setSessionsReady(true);
      });
    return () => { active = false; };
  }, [fetchSessions]);

  React.useEffect(() => {
    if (sessionId) {
      if (sessionsReady && !sessionExists) {
        createSession().catch(() => null);
        navigate("/chat", { replace: true });
        return;
      }
      selectSession(sessionId).catch(() => null);
      return;
    }
    if (!sessionsReady || isCreatingNew || currentSessionId) return;
    createSession().catch(() => null);
  }, [sessionId, sessionsReady, sessionExists, isCreatingNew, currentSessionId, selectSession, createSession, navigate]);

  React.useEffect(() => {
    if (currentSessionId && currentSessionId !== sessionId) {
      navigate(`/chat/${currentSessionId}`, { replace: true });
    }
  }, [currentSessionId, sessionId, navigate]);

  return (
    <MainLayout>
      <div className="merchant-chat-shell relative flex h-full min-h-0 min-w-0">
        <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-white">
          <div className="min-h-0 flex-1">
            {showEmptyLoading ? (
              <div className="flex h-full min-h-[240px] items-center justify-center bg-[var(--merchant-surface-subtle)] px-4" role="status">
                <div className="text-center text-sm text-[var(--merchant-text-muted)]">
                  <LoaderCircle className="mx-auto mb-3 h-6 w-6 animate-spin text-[var(--merchant-cyan-strong)]" />
                  正在载入售后会话...
                </div>
              </div>
            ) : (
              <MessageList messages={messages} isLoading={isLoading} isStreaming={isStreaming} sessionKey={currentSessionId} />
            )}
          </div>
          {showWelcome ? null : (
            <div className="relative z-20 shrink-0 border-t border-[var(--merchant-border)] bg-white">
              {lastMessageFailed ? (
                <div className="mx-auto flex max-w-[840px] items-center gap-2 px-3 pt-2 text-xs text-orange-800 sm:px-6" role="status">
                  <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-[var(--merchant-alert)]" />
                  上次回答未完成，可补充信息后重新发送。
                </div>
              ) : null}
              <div className="mx-auto max-w-[840px] px-3 pb-3 pt-2 sm:px-6 sm:pb-4">
                <ChatInput />
              </div>
            </div>
          )}
        </div>
        <SourcesPanel />
      </div>
    </MainLayout>
  );
}
