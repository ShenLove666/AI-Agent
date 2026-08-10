import type { Message } from "@/types";

/**
 * 一个完整 Chat Turn = 一轮问答（user + assistant）。
 * 规则：
 * - 优先按 turnId 配对：同 turnId 的 user 与 assistant 合并为一个 turn
 *   （regenerate 是原地替换、answerVersions 挂在 assistant 内部，数组中同一 turn 至多一个 assistant）。
 * - 无 turnId 的消息用邻接配对：user 后紧跟 assistant（本地 placeholder 流式场景）组成同一 turn。
 * - 孤立 user（无 assistant——流式中/历史缺失）→ 单独 turn（assistant 缺省）。
 * - 孤立 assistant（防御）→ 单独 turn。
 * - 顺序保持消息数组顺序；key：有 turnId → `turn-${turnId}`；
 *   无 → `local-${index}`（index 为该 turn 起始消息在数组中的下标，append-only 保证稳定）。
 */
export interface ChatTurn {
  /** 稳定 key：有 turnId → `turn-${turnId}`；无 → `local-${index}` */
  key: string;
  turnId?: number;
  user?: Message;
  assistant?: Message;
}

export function groupMessagesIntoTurns(messages: Message[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  const turnByTurnId = new Map<number, ChatTurn>();
  let lastTurn: ChatTurn | null = null;

  messages.forEach((message, index) => {
    if (message.turnId !== undefined && message.turnId !== null) {
      let turn = turnByTurnId.get(message.turnId);
      if (!turn) {
        turn = { key: `turn-${message.turnId}`, turnId: message.turnId };
        // 防御：turnId'd assistant 紧跟一个无 turnId 的孤立 user（meta 只先落到 assistant 的瞬时态）
        // → 合并进前一 turn，避免同一轮被拆成两段。
        if (message.role === "assistant") {
          const prev = turns[turns.length - 1];
          if (prev && prev.user && !prev.assistant && prev.user.turnId === undefined) {
            prev.assistant = message;
            prev.turnId = message.turnId;
            prev.key = `turn-${message.turnId}`;
            turnByTurnId.set(message.turnId, prev);
            lastTurn = prev;
            return;
          }
        }
        turnByTurnId.set(message.turnId, turn);
        turns.push(turn);
      }
      if (message.role === "user") {
        if (!turn.user) turn.user = message;
      } else if (!turn.assistant) {
        turn.assistant = message;
      }
      lastTurn = turn;
      return;
    }

    // 无 turnId
    if (message.role === "user") {
      const turn: ChatTurn = { key: `local-${index}`, user: message };
      turns.push(turn);
      lastTurn = turn;
      return;
    }

    // 无 turnId 的 assistant：与紧邻的 user（可能已带 turnId 的瞬时态）配对，否则孤立成 turn
    if (lastTurn && lastTurn.user && !lastTurn.assistant) {
      lastTurn.assistant = message;
    } else {
      const turn: ChatTurn = { key: `local-${index}`, assistant: message };
      turns.push(turn);
      lastTurn = turn;
    }
  });

  return turns;
}
