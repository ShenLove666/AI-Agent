/**
 * 复制文本到剪贴板（全站统一入口）。
 *
 * `navigator.clipboard` 只在 secure context（HTTPS / localhost / 127.0.0.1）可用；
 * 通过 `http://局域网IP:端口` 访问时它是 undefined，直接调用会同步抛错。
 * 统一处理：secure context 优先 Clipboard API，失败/不可用时降级为
 * 临时 textarea + document.execCommand("copy")。
 *
 * @returns 是否复制成功（调用方据此提示「已复制」或「复制失败」）
 */
export async function copyText(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      if (import.meta.env.DEV) {
        console.warn("[clipboard] modern API failed, falling back", error);
      }
    }
  }

  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
    document.body.appendChild(textarea);
    textarea.select();
    textarea.setSelectionRange(0, text.length);
    const success = document.execCommand("copy");
    document.body.removeChild(textarea);
    return success;
  } catch (error) {
    if (import.meta.env.DEV) {
      console.warn("[clipboard] fallback failed", error);
    }
    return false;
  }
}
