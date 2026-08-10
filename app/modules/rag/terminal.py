"""Agent terminal 状态判定与固定回复文案。

本模块只包含纯函数，无任何副作用：

1. is_trivial_direct(question)：判断用户 query 是否属于「无需调用业务工具的
   普通对话」（问候/感谢/自我介绍/笑声等）。用于在 Planner 调模型之前短路，
   避免模型把普通问候误判为 refuse/escalate，也用于 rewrite 阶段跳过 LLM 改写。
2. build_terminal_response(terminal_state)：返回 refuse/escalate 终态下
   不调用生成模型时的固定回复文案。
"""

from __future__ import annotations

import re
from typing import Literal

# 业务关键词黑名单：normalize 后命中任一 → 视为业务问题，不得判定为 trivial。
# 必须严格：宁可放过普通问候去走模型，也不能把业务问题误判成直接回答。
_BUSINESS_KEYWORDS = (
    "退款",
    "退货",
    "订单",
    "价格",
    "政策",
    "规则",
    "商品",
    "售后",
    "配送",
    "知识",
    "搭配",
    "推荐",
    "销量",
    "客服",
    "依据",
    "凭证",
    "赔偿",
    "投诉",
    "发票",
    "库存",
    "经营",
    "数据",
    "说明",
    "指南",
)

# 去空白、小写、去标点（中文全角与英文半角标点、波浪线、顿号、空格）
_PUNCTUATION_WS_RE = re.compile(r"[\s，。？！!?~、]+")

# ASCII 模式加词边界，避免 hi/hello/hh 命中长英文单词内部
_LETTER_GREETING_RE = re.compile(r"\b(?:hi|hello)\b", re.IGNORECASE)
_LETTER_LAUGHTER_RE = re.compile(r"\bhh+\b", re.IGNORECASE)

# 中文问候/感谢/自我介绍
_CN_GREETINGS = ("你好", "您好", "哈喽", "嗨", "在吗")
_CN_THANKS = ("谢谢", "感谢", "多谢")
_CN_SELF_INTRO = ("你是谁", "介绍一下自己", "你能做什么", "你会做什么", "介绍一下")
_CN_LAUGHTER_RE = re.compile(r"(?:哈哈+|嘻嘻+)")


def _normalize(question: str) -> str:
    """去掉空白、转小写、去掉常见标点（，。？！!?~、与空格）。"""
    return _PUNCTUATION_WS_RE.sub("", question.lower())


def is_trivial_direct(question: str) -> bool:
    """普通问候/感谢/自我介绍/笑声等无需业务工具的 query 判定。

    判定顺序（严格，不能误伤业务问题）：
    1. 长度限制：normalize（去空白、小写、去标点）后 > 24 字符 → False。
    2. 业务关键词黑名单：normalize 后含任一业务词（退款/退货/订单/价格/政策/
       规则/商品/售后/配送/知识/搭配/推荐/销量/客服/依据/凭证/赔偿/投诉/
       发票/库存/经营/数据/说明/指南）→ False。
    3. 模式命中（任一）→ True：问候（你好|您好|哈喽|嗨|hello|hi|在吗）、
       感谢（谢谢|感谢|多谢）、自我介绍询问（你是谁|介绍一下自己|你能做什么|
       你会做什么|介绍一下）、笑声（哈哈+ 或 嘻嘻+ 或 hh+）。

    示例：「你好哈哈哈」→ True；「你好，我想问退款政策」→ False（含退款/政策）；
    「哈哈」→ True；「你是谁？」→ True；「牛肉适合搭配什么？」→ False（含搭配）。
    """
    normalized = _normalize(question)
    if not normalized or len(normalized) > 24:
        return False
    if any(keyword in normalized for keyword in _BUSINESS_KEYWORDS):
        return False
    if any(greeting in normalized for greeting in _CN_GREETINGS):
        return True
    if any(thanks in normalized for thanks in _CN_THANKS):
        return True
    if any(intro in normalized for intro in _CN_SELF_INTRO):
        return True
    if _LETTER_GREETING_RE.search(normalized):
        return True
    if _CN_LAUGHTER_RE.search(normalized) or _LETTER_LAUGHTER_RE.search(normalized):
        return True
    return False


_TERMINAL_REPLIES: dict[str, str] = {
    "refused": "该请求无法协助执行。如您有正当业务需求，请描述具体问题，我会尽力协助。",
    "escalated": "当前资料不足，暂时无法可靠确认。您可以补充订单号、商品或具体时间等信息，或转人工客服复核。",
}


def build_terminal_response(terminal_state: Literal["refused", "escalated"]) -> str:
    """refuse/escalate 终态的固定回复文案（纯函数，不调用模型）。"""
    return _TERMINAL_REPLIES[terminal_state]
