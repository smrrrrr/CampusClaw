"use client";

import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { normalizeMathMarkdown } from "@/lib/markdown-math";

export default function MarkdownAnswer({ text }: { text: string }) {
  return (
    <div className="markdown-body" style={{ lineHeight: 1.8, fontSize: 14 }}>
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {normalizeMathMarkdown(text)}
      </ReactMarkdown>
    </div>
  );
}