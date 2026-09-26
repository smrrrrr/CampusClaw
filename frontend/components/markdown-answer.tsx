"use client";

import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

/**
 * 渲染 AI 回答：Markdown（加粗/列表） + KaTeX（LaTeX 数学公式）。
 * 用于学生端 AI 解题助手，让公式以真正的数学符号展示而非源码。
 */
export default function MarkdownAnswer({ text }: { text: string }) {
  return (
    <div className="markdown-body" style={{ lineHeight: 1.8, fontSize: 14 }}>
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {text}
      </ReactMarkdown>
    </div>
  );
}