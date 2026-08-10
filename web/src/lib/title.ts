/**
 * 会话标题压缩：Header/Sidebar 展示用短标题（「这个会话讲什么」），
 * 完整标题保留在会话数据与 title 属性中。
 *
 * 规则：去首尾空白 → 去句尾标点 → 超长截断到 14 个字符并补省略号。
 * 避免把「牛肉适合搭配哪些商品？请给出推荐依据…」整句贴在标题栏。
 */

const MAX_TITLE_CHARS = 14;

const TRAILING_PUNCTUATION = /[。．.？?！!～~、，,\s]+$/;

export function shortenSessionTitle(title?: string | null): string {
  const trimmed = (title || "").trim();
  if (!trimmed) return "新对话";
  const cleaned = trimmed.replace(TRAILING_PUNCTUATION, "");
  if (cleaned.length <= MAX_TITLE_CHARS) return cleaned;
  return `${cleaned.slice(0, MAX_TITLE_CHARS)}…`;
}
