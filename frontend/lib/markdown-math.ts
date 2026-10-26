/** 仅规范公式定界符和已知命令，保留代码块/代码跨度的原始内容。 */
const COMMANDS = new Set(`
overrightarrow underrightarrow overleftrightarrow longrightarrow longleftarrow
overset underset stackrel overline underline mathbb mathbf boldsymbol dfrac tfrac lVert rVert
vec frac sqrt cdot times div pm mp sum prod int iint oint lim max min
left right big Big bigg Bigg bigl bigr Bigl Bigr middle vert lvert rvert Vert
pi alpha beta gamma delta epsilon varepsilon varphi theta lambda mu nu xi phi omega sigma rho tau eta zeta chi psi
Gamma Delta Theta Lambda Sigma Omega Pi cos sin tan cot sec csc arcsin arccos arctan log ln exp
leq geq leqq geqq leqslant geqslant neq ne approx equiv sim cong propto perp parallel nmid mid
in notin subset subseteq supset supseteq subsetneq cup cap setminus emptyset varnothing
to rightarrow leftarrow Rightarrow Leftarrow leftrightarrow Leftrightarrow mapsto
angle ell ldots cdots vdots ddots dots text mathrm textbf textit quad qquad begin end circ
`.trim().split(/\s+/));

function normalizeProse(text: string): string {
  // remark-math 支持 $/$$；模型也经常输出标准的 \(...\) 和 \[...\]。
  const delimited = text
    .replace(/(?<!\\)\\\[([\s\S]*?)\\\]/g, (_, body: string) => `\n\n$$\n${body.trim()}\n$$\n\n`)
    .replace(/(?<!\\)\\\(([\s\S]*?)\\\)/g, (_, body: string) => `$${body.trim()}$`);
  return delimited.replace(/\$\$([^$]+?)\$\$|\$([^$]+?)\$/g, (whole, block, inline) => {
    const body: string = block !== undefined ? block : inline;
    const fixed = body.replace(/(^|[^a-zA-Z\\])([a-zA-Z]+)/g, (match: string, prefix: string, command: string) =>
      COMMANDS.has(command) ? `${prefix}\\${command}` : match);
    return block !== undefined ? `$$${fixed}$$` : `$${fixed}$`;
  });
}

export function normalizeMathMarkdown(text: string): string {
  return text.split(/(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g)
    .map((part, index) => index % 2 ? part : normalizeProse(part)).join("");
}
