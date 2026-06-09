import katex from "katex";

type Segment = {
  kind: "text" | "math";
  value: string;
  displayMode?: boolean;
};

const MATH_PATTERN = /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\$[^$\n]+?\$|\\\([\s\S]+?\\\))/g;

function stripMathDelimiters(raw: string): { value: string; displayMode: boolean } {
  if (raw.startsWith("$$") && raw.endsWith("$$")) {
    return { value: raw.slice(2, -2), displayMode: true };
  }
  if (raw.startsWith("\\[") && raw.endsWith("\\]")) {
    return { value: raw.slice(2, -2), displayMode: true };
  }
  if (raw.startsWith("$") && raw.endsWith("$")) {
    return { value: raw.slice(1, -1), displayMode: false };
  }
  if (raw.startsWith("\\(") && raw.endsWith("\\)")) {
    return { value: raw.slice(2, -2), displayMode: false };
  }
  return { value: raw, displayMode: false };
}

function splitMathText(text: string): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;

  for (const match of text.matchAll(MATH_PATTERN)) {
    const raw = match[0];
    const index = match.index ?? 0;
    if (index > cursor) {
      segments.push({ kind: "text", value: text.slice(cursor, index) });
    }
    const math = stripMathDelimiters(raw);
    segments.push({ kind: "math", value: math.value, displayMode: math.displayMode });
    cursor = index + raw.length;
  }

  if (cursor < text.length) {
    segments.push({ kind: "text", value: text.slice(cursor) });
  }
  return segments;
}

function renderMath(value: string, displayMode = false): string {
  return katex.renderToString(value, {
    displayMode,
    throwOnError: false,
    strict: "ignore",
    trust: false,
  });
}

export default function MathText({ text, inline = false }: { text: string; inline?: boolean }) {
  const segments = splitMathText(text);

  return (
    <>
      {segments.map((segment, index) => {
        if (segment.kind === "text") {
          return <span key={index}>{segment.value}</span>;
        }
        const displayMode = inline ? false : segment.displayMode;
        return (
          <span
            key={index}
            className={displayMode ? "block my-2 overflow-x-auto" : "inline-block max-w-full align-baseline"}
            dangerouslySetInnerHTML={{ __html: renderMath(segment.value, displayMode) }}
          />
        );
      })}
    </>
  );
}
