"""对话意图前置路由：把用户问题分为 direct / history_reference / research / refuse。

执行顺序从 Rewrite→Intent 改为 Intent→Rewrite→Research：
只有 research 才继续 Rewrite → Agent Planner → Tools → Evidence Reviewer
→ Generation；direct / history_reference / refuse 在意图层确定性短路，
不调用改写与 Agent 流程。

classify() 的判定顺序：
1. 确定性 fast path（先于模型，纯函数，可测试）：
   - is_trivial_direct（terminal.py）：问候/感谢/自我介绍/笑声 → direct。
   - history_reference 高置信规则：问题本身就在问「当前对话里说了什么」。
   - refuse 高置信规则：请求本身不应执行（欺骗/伪造等），与
     agentic._fallback_decision 的安全词保持一致。
2. Intent LLM 路径：输出仅 JSON {"intent": ..., "reason": ...}；
   解析失败/异常 → 规则 fallback。
3. 规则 fallback（model_router 为 None 时）：含业务词 → research，否则
   direct。这是无模型环境的保守回退：宁可 research 走一遍也不漏业务问题。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from app.infra_ai.contracts import ChatMessage, ChatRequest
from app.infra_ai.router import ChatModelRouter
from app.modules.rag.terminal import is_trivial_direct


@dataclass(frozen=True, slots=True)
class IntentDecision:
    intent: Literal["direct", "history_reference", "research", "refuse"]
    reason: str


_INTENT_LITERALS = {"direct", "history_reference", "research", "refuse"}

# 拒绝安全词：与 agentic._fallback_decision 完全一致的独立副本
# （本模块维护独立规则集，修改时必须两边同步；不得擅自扩词，
# 否则会误伤「如何防止数据造假」等合法业务问题）。
_REFUSE_TERMS = ("伪造", "欺骗", "假截图")

# 简单数学表达式（如「1+3=?」「12 × 4」）：确定性 direct，避免为这类
# trivial 请求多调用一次 Intent LLM 分类（快路径 <1ms vs ~1.4s）。
_SIMPLE_MATH_RE = re.compile(r"^[\d\s+\-*/×÷().=？?%^]+$")

# history_reference 高置信表达（normalize 后包含匹配）：
# 「我上句话问的什么」「重复一下你刚才的回答」等 —— 答案来自当前对话本身。
# 无 history 时仍返回 history_reference，由 service 分支兜底
# 「当前对话还没有历史消息」。
_HISTORY_REFERENCE_PATTERNS = (
    "我上句话问的什么",
    "我上一句话问的什么",
    "我上句话问了什么",
    "我上一句话问了什么",
    "我上句问的什么",
    "我上一句问的什么",
    "我刚才问了什么",
    "我刚才问的什么",
    "我刚才问的是什么",
    "我刚才说了什么",
    "我刚才说的是什么",
    "我上句话是什么",
    "我上一句话是什么",
    "我上一个问题",
    "我上个问题",
    "我上一个问题是什么",
    "你上一条说了什么",
    "你上一条回答",
    "你上一条的回答",
    "你上条说了什么",
    "你刚才说了什么",
    "你刚才回答了什么",
    "你刚才的回答",
    "重复一下你刚才",
    "重复一下你上一条",
    "重复一下上一条",
)

# 无模型环境的保守回退业务词：normalize 后命中任一 → research。
# 核心列表来自用户规格（订单/商品/退款/政策/搭配/推荐/销量/库存/售后/
# 知识库/客服/价格/发票/配送/退货/依据/数据/经营/指南/SOP），并补充
# agentic._fallback_decision 中同样视为业务问题的 commerce/knowledge/
# support 关键词，保持两层判定一致。
_FALLBACK_BUSINESS_TERMS = (
    "订单",
    "商品",
    "退款",
    "政策",
    "搭配",
    "推荐",
    "销量",
    "库存",
    "售后",
    "知识库",
    "客服",
    "价格",
    "发票",
    "配送",
    "退货",
    "依据",
    "数据",
    "经营",
    "指南",
    "sop",
    "流程",
    "规则",
    "法规",
    "活动",
    "安全",
    "交易",
    "关联",
    "建议",
    "购物篮",
    "工单",
    "案例",
    "客诉",
    "咨询",
    "质量",
    "取消",
)

_PUNCTUATION_WS_RE = re.compile(r"[\s，。？！!?~、]+")


def _normalize(question: str) -> str:
    """去空白、小写、去常见标点（与 terminal._normalize 同语义的本地副本）。"""
    return _PUNCTUATION_WS_RE.sub("", question.lower())


# Intent LLM 的 system prompt：四类意图定义 + 7 条 few-shot（用户规格原文）。
_SYSTEM_PROMPT = (
    "你是对话意图分类器。把用户问题归入以下四类之一，只输出 JSON："
    '{"intent": "direct|history_reference|research|refuse", "reason": "简要说明"}。\n'
    "direct: 不需要商家私有数据或知识库即可回答。包括基础数学、常识解释、文本改写、普通闲聊、概念解释。\n"
    "history_reference: 答案主要来自当前对话本身。\n"
    "research: 需要订单、商品、经营、知识库、政策、客服等商家事实。\n"
    "refuse: 请求本身不应执行。\n"
    "示例：\n"
    '- 「1 + 1 = 多少？」→ {"intent":"direct","reason":"基础数学"}\n'
    '- 「ROI 是什么意思？」→ {"intent":"direct","reason":"概念解释"}\n'
    '- 「我上句话问了什么？」→ {"intent":"history_reference","reason":"答案在当前对话里"}\n'
    '- 上一轮「牛肉适合搭配什么？」，当前「那土豆呢？」→ {"intent":"research","reason":"继承上一轮搭配语境"}\n'
    '- 「牛肉最近销量怎么样？」→ {"intent":"research","reason":"需要经营数据"}\n'
    '- 「根据知识库，退款期限是多少？」→ {"intent":"research","reason":"需要知识库政策"}\n'
    '- 「帮我伪造退款记录」→ {"intent":"refuse","reason":"请求本身不应执行"}\n'
    "只输出 JSON，不要输出任何其他内容。"
)


class ConversationIntentRouter:
    """意图分类器。model_router 为 None 时走规则 fallback。

    model_router 是可变属性：RagChatService 在每次 classify 前把服务当前的
    router 同步进来（运行期/测试可能整体替换 router 实例，避免构造时的
    陈旧绑定）；纯单元测试可自行构造实例注入 RecordingRouter。
    """

    def __init__(self, model_router: ChatModelRouter | None):
        self.model_router = model_router

    def _fast_path(
        self, question: str, history: list[ChatMessage] | None
    ) -> IntentDecision | None:
        """确定性 fast path：命中即返回，不调用模型。

        顺序严格：trivial（问候）→ history_reference → 短指代（继承语境）→
        refuse → 业务词强制 research。业务词检查在模型之前执行，防止模型把
        「牛肉适合搭配什么」误判为 direct（宁可 research 走一遍也不漏业务）。
        """
        if is_trivial_direct(question):
            return IntentDecision("direct", "普通问候/感谢/闲聊，无需业务数据")
        normalized = _normalize(question)
        # 简单数学表达式（「1+3=?」）：确定性 direct，不调用 Intent LLM
        if _SIMPLE_MATH_RE.fullmatch(normalized):
            return IntentDecision("direct", "基础数学表达式，无需业务数据")
        for pattern in _HISTORY_REFERENCE_PATTERNS:
            if pattern in normalized:
                return IntentDecision(
                    "history_reference", "答案来自当前对话本身"
                )
        # 短指代问题（「那土豆呢」「红酒呢」「这个呢」）：有上下文时按 research
        # 继承语境处理，避免模型误判为 history_reference/direct 导致语境断裂；
        # 无 history 时跳过（短闲聊不强制走检索）。
        if (
            history
            and len(normalized) <= 8
            and (
                normalized.endswith("呢")
                or normalized.startswith(("那", "这"))
            )
        ):
            return IntentDecision(
                "research", "短指代问题，继承对话语境按商家事实检索处理"
            )
        for term in _REFUSE_TERMS:
            if term in normalized:
                return IntentDecision("refuse", "请求涉及欺骗或伪造，不应执行")
        if any(term in normalized for term in _FALLBACK_BUSINESS_TERMS):
            return IntentDecision("research", "含商家业务关键词，按商家事实检索处理")
        return None

    def _fallback_decision(self, question: str) -> IntentDecision:
        """无模型/解析失败时的保守回退：宁可 research 走一遍也不漏业务。"""
        lowered = _normalize(question)
        if any(term in lowered for term in _FALLBACK_BUSINESS_TERMS):
            return IntentDecision("research", "含业务关键词，按商家事实检索处理")
        return IntentDecision("direct", "无业务关键词，按普通问题直接回答")

    async def classify(
        self, question: str, history: list[ChatMessage] | None
    ) -> IntentDecision:
        fast = self._fast_path(question, history)
        if fast is not None:
            return fast
        if self.model_router is None:
            return self._fallback_decision(question)
        # history 最近的 8 条消息（4 轮，含 role/content）拼进 user 消息；
        # history 为 None/空时只给 question。
        history_text = "\n".join(
            f"{item.role}: {item.content}" for item in (history or [])[-8:]
        )
        user_content = f"当前问题：{question}"
        if history_text:
            user_content += f"\n\n历史对话：\n{history_text}"
        request = ChatRequest(
            messages=[
                ChatMessage("system", _SYSTEM_PROMPT),
                ChatMessage("user", user_content),
            ],
            temperature=0,
            max_tokens=128,
            metadata={"agent_role": "intent_classifier"},
        )
        try:
            raw = (await self.model_router.complete(request)).strip().strip("`")
            if raw.startswith("json"):
                raw = raw[4:].lstrip()
            value = json.loads(raw)
            intent = str(value.get("intent", ""))
            if intent not in _INTENT_LITERALS:
                raise ValueError("invalid intent value")
            reason = str(value.get("reason", "")).strip() or "模型分类"
            return IntentDecision(intent, reason)  # type: ignore[arg-type]
        except Exception:
            # 网络/解析/非法值一律回退到规则，不向上抛（前置路由不能阻断主链路）
            return self._fallback_decision(question)
