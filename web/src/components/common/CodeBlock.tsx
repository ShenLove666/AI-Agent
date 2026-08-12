import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";

interface CodeBlockProps {
  language: string;
  value: string;
  dark?: boolean;
}

/**
 * 代码块高亮（按需加载）：Prism 体积大（~700KB），仅在回答里真正出现
 * 代码块时才通过 React.lazy 拉取，避免随聊天页首屏加载。
 */
export function CodeBlock({ language, value, dark }: CodeBlockProps) {
  return (
    <SyntaxHighlighter
      language={language}
      style={dark ? oneDark : oneLight}
      PreTag="div"
      customStyle={{
        margin: 0,
        padding: "0.75rem 1rem",
        background: "transparent",
        fontSize: "13px",
        lineHeight: "1.5"
      }}
      showLineNumbers={false}
      wrapLines={true}
    >
      {value}
    </SyntaxHighlighter>
  );
}
