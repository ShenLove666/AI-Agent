import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ChatTurnItem } from "@/components/chat/ChatTurnItem";
import type { Message } from "@/types";
import type { ChatTurn } from "@/utils/chatTurns";

function makeMessage(id: string, role: "user" | "assistant", content: string): Message {
  return {
    id,
    role,
    content,
    status: role === "user" ? "sent" : "done",
    createdAt: "2026-08-09T12:00:00Z",
    updatedAt: "2026-08-09T12:00:00Z"
  } as Message;
}

afterEach(cleanup);

describe("ChatTurnItem Turn 渲染", () => {
  it("user + assistant 合并渲染：同一容器、data-message-id 齐全、文案都在", () => {
    const turn: ChatTurn = {
      key: "local-0",
      user: makeMessage("m1", "user", "牛肉和什么商品适合搭配推荐？"),
      assistant: makeMessage("m2", "assistant", "推荐根茎类蔬菜。")
    };
    render(<ChatTurnItem turn={turn} isLatestTurn={false} />);

    const userBox = document.querySelector('[data-message-id="m1"]');
    const assistantBox = document.querySelector('[data-message-id="m2"]');
    expect(userBox).not.toBeNull();
    expect(assistantBox).not.toBeNull();
    // 同在一个 turn 容器内
    expect(userBox!.parentElement).toBe(assistantBox!.parentElement);
    const container = userBox!.parentElement!;
    expect(container.textContent).toContain("牛肉和什么商品适合搭配推荐？");
    expect(container.textContent).toContain("推荐根茎类蔬菜。");
  });

  it("只有 user（流式中）也能渲染，且没有 assistant 内容", () => {
    const turn: ChatTurn = {
      key: "local-0",
      user: makeMessage("u1", "user", "正在处理的问题")
    };
    render(<ChatTurnItem turn={turn} isLatestTurn={true} />);
    expect(screen.getByText("正在处理的问题")).toBeInTheDocument();
    expect(document.querySelector('[data-message-id^="a"]')).toBeNull();
  });

  it("只有 assistant（孤立防御）也能渲染", () => {
    const turn: ChatTurn = {
      key: "local-0",
      assistant: makeMessage("a1", "assistant", "孤立回答")
    };
    render(<ChatTurnItem turn={turn} isLatestTurn={false} />);
    expect(screen.getByText("孤立回答")).toBeInTheDocument();
  });
});
