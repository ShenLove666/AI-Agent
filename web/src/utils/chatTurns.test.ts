import { describe, expect, it } from "vitest";

import { groupMessagesIntoTurns, type ChatTurn } from "./chatTurns";
import type { Message } from "@/types";

function makeMessage(
  id: string,
  role: "user" | "assistant",
  content: string,
  extra: Partial<Message> = {}
): Message {
  return {
    id,
    role,
    content,
    status: role === "user" ? "sent" : "done",
    createdAt: "2026-08-09T12:00:00Z",
    updatedAt: "2026-08-09T12:00:00Z",
    ...extra
  } as Message;
}

describe("groupMessagesIntoTurns", () => {
  it("历史（turnId）：同 turnId 的 user 与 assistant 合并为一轮，key 为 turn-{turnId}", () => {
    const messages = [
      makeMessage("u1", "user", "问题一", { turnId: 1 }),
      makeMessage("a1", "assistant", "回答一", { turnId: 1 }),
      makeMessage("u2", "user", "问题二", { turnId: 2 }),
      makeMessage("a2", "assistant", "回答二", { turnId: 2 })
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns).toHaveLength(2);
    expect(turns[0]).toEqual({
      key: "turn-1",
      turnId: 1,
      user: messages[0],
      assistant: messages[1]
    });
    expect(turns[1]).toEqual({
      key: "turn-2",
      turnId: 2,
      user: messages[2],
      assistant: messages[3]
    });
  });

  it("实时（无 turnId 邻接）：user 后紧跟 assistant 组成同一轮，key 为 local-起始下标", () => {
    const messages = [
      makeMessage("u1", "user", "问题"),
      makeMessage("a1", "assistant", "回答")
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns).toHaveLength(1);
    expect(turns[0]).toEqual({
      key: "local-0",
      user: messages[0],
      assistant: messages[1]
    });
  });

  it("regenerate（原地替换）：同一 turnId 只有一个 assistant，不产生额外 turn", () => {
    const messages = [
      makeMessage("u1", "user", "问题", { turnId: 7 }),
      makeMessage("a1-v2", "assistant", "新回答", { turnId: 7, version: 2 })
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns).toHaveLength(1);
    expect(turns[0].turnId).toBe(7);
    expect(turns[0].user?.id).toBe("u1");
    expect(turns[0].assistant?.id).toBe("a1-v2");
  });

  it("cancelled/error assistant：与 user 仍是一轮，状态不影响分组", () => {
    const cancelled = [
      makeMessage("u1", "user", "问题"),
      makeMessage("a1", "assistant", "已停止", { status: "cancelled" })
    ];
    const error = [
      makeMessage("u2", "user", "问题"),
      makeMessage("a2", "assistant", "失败", { status: "error" })
    ];

    const [c] = groupMessagesIntoTurns(cancelled);
    const [e] = groupMessagesIntoTurns(error);

    expect(c.user?.id).toBe("u1");
    expect(c.assistant?.id).toBe("a1");
    expect(e.user?.id).toBe("u2");
    expect(e.assistant?.id).toBe("a2");
  });

  it("孤立 user（无 assistant——流式中/历史缺失）→ 单独 turn，assistant 缺省", () => {
    const messages = [
      makeMessage("u1", "user", "正在处理的问题")
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns).toHaveLength(1);
    expect(turns[0]).toEqual({
      key: "local-0",
      user: messages[0]
    });
    expect(turns[0].assistant).toBeUndefined();
  });

  it("孤立 assistant（防御）→ 单独 turn", () => {
    const messages = [
      makeMessage("a1", "assistant", "无 user 的助手消息")
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns).toHaveLength(1);
    expect(turns[0]).toEqual({
      key: "local-0",
      assistant: messages[0]
    });
    expect(turns[0].user).toBeUndefined();
  });

  it("user→assistant→user→assistant 连续轮次：拆成两轮，顺序保持数组顺序", () => {
    const messages = [
      makeMessage("u1", "user", "第一问"),
      makeMessage("a1", "assistant", "第一答"),
      makeMessage("u2", "user", "第二问"),
      makeMessage("a2", "assistant", "第二答")
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns).toHaveLength(2);
    expect(turns[0].key).toBe("local-0");
    expect(turns[0].user?.id).toBe("u1");
    expect(turns[0].assistant?.id).toBe("a1");
    expect(turns[1].key).toBe("local-2");
    expect(turns[1].user?.id).toBe("u2");
    expect(turns[1].assistant?.id).toBe("a2");
  });

  it("连续 user 后跟 assistant：首个 user 为孤立 turn，后者与 assistant 配对", () => {
    const messages = [
      makeMessage("u1", "user", "问题A"),
      makeMessage("u2", "user", "问题B"),
      makeMessage("a2", "assistant", "回答B")
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns).toHaveLength(2);
    expect(turns[0].key).toBe("local-0");
    expect(turns[0].user?.id).toBe("u1");
    expect(turns[0].assistant).toBeUndefined();
    expect(turns[1].key).toBe("local-1");
    expect(turns[1].user?.id).toBe("u2");
    expect(turns[1].assistant?.id).toBe("a2");
  });

  it("多版本（answerVersions 挂在 assistant 内部）：不产生额外 turn", () => {
    const messages = [
      makeMessage("u1", "user", "问题", { turnId: 3 }),
      makeMessage("a1", "assistant", "回答", {
        turnId: 3,
        version: 2,
        answerVersions: [
          { id: "av1", version: 1, content: "第一版" },
          { id: "av2", version: 2, content: "第二版" }
        ]
      })
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns).toHaveLength(1);
    expect(turns[0].assistant?.answerVersions).toHaveLength(2);
  });

  it("混合瞬时态：user 无 turnId + assistant 带 turnId（meta 先落到 assistant）→ 合并，key 用 turnId", () => {
    const messages = [
      makeMessage("u1", "user", "问题"),
      makeMessage("a1", "assistant", "回答", { turnId: 5 })
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns).toHaveLength(1);
    expect(turns[0]).toEqual({
      key: "turn-5",
      turnId: 5,
      user: messages[0],
      assistant: messages[1]
    });
  });

  it("混合瞬时态：user 带 turnId + assistant 无 turnId → 仍合并为一轮", () => {
    const messages = [
      makeMessage("u1", "user", "问题", { turnId: 5 }),
      makeMessage("a1", "assistant", "回答")
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns).toHaveLength(1);
    expect(turns[0]).toEqual({
      key: "turn-5",
      turnId: 5,
      user: messages[0],
      assistant: messages[1]
    });
  });

  it("空数组 → 空 turns", () => {
    expect(groupMessagesIntoTurns([])).toEqual([]);
  });

  it("同 turnId 的消息分散在数组中（防御）→ 仍合并为一轮", () => {
    const messages = [
      makeMessage("u1", "user", "问题一", { turnId: 1 }),
      makeMessage("u2", "user", "问题二", { turnId: 2 }),
      makeMessage("a2", "assistant", "回答二", { turnId: 2 }),
      makeMessage("a1", "assistant", "回答一", { turnId: 1 })
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns).toHaveLength(2);
    expect(turns[0].key).toBe("turn-1");
    expect(turns[0].user?.id).toBe("u1");
    expect(turns[0].assistant?.id).toBe("a1");
    expect(turns[1].key).toBe("turn-2");
    expect(turns[1].user?.id).toBe("u2");
    expect(turns[1].assistant?.id).toBe("a2");
  });

  it("key 的 local 下标为该 turn 起始消息在数组中的位置（append-only 稳定）", () => {
    const messages: Message[] = [
      makeMessage("a0", "assistant", "孤立助手消息"),
      makeMessage("u1", "user", "问题一"),
      makeMessage("a1", "assistant", "回答一"),
      makeMessage("u2", "user", "问题二")
    ];

    const turns = groupMessagesIntoTurns(messages);

    expect(turns.map((t: ChatTurn) => t.key)).toEqual(["local-0", "local-1", "local-3"]);
    expect(turns[2].user?.id).toBe("u2");
    expect(turns[2].assistant).toBeUndefined();
  });
});
