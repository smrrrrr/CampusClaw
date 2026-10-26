const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

const filename = path.resolve(__dirname, "../lib/markdown-math.ts");
const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const mod = new Module(filename, module);
mod._compile(compiled, filename);
const { normalizeMathMarkdown } = mod.exports;

async function render(text) {
  const [{ default: Markdown }, { default: math }, { default: katex }] = await Promise.all([import("react-markdown"), import("remark-math"), import("rehype-katex")]);
  return renderToStaticMarkup(React.createElement(Markdown, { remarkPlugins: [math], rehypePlugins: [katex] }, normalizeMathMarkdown(text)));
}

test("standard inline temperature and math delimiters produce valid KaTeX", async () => {
  const html = await render(String.raw`气温 \(10.4\,^{\circ}\mathrm{C}\)，公式 \(\frac{a}{b}\)。`);
  assert.match(html, /class="katex"/);
  assert.doesNotMatch(html, /katex-error/);
  assert.match(html, /mfrac/);
});

test("display delimiters and existing dollar formulas remain valid", async () => {
  const html = await render(String.raw`\[\vec{a}\cdot\vec{b}=32\]` + "\n\n" + String.raw`$\sqrt{14}$`);
  assert.match(html, /katex-display/);
  assert.doesNotMatch(html, /katex-error/);
});

test("normalization preserves code examples and plain weather units", async () => {
  const code = String.raw`示例：\(x\)`;
  const input = "`" + code + "`\n\n```tex\n" + code + "\n```\n\n10.4°C，相对湿度 50%";
  assert.equal(normalizeMathMarkdown(input), input);
  const html = await render(input);
  assert.doesNotMatch(html, /class="katex"/);
  assert.match(html, /10\.4°C/);
});
