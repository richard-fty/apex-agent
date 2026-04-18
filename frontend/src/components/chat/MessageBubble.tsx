import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

interface Props {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

export function MessageBubble({ role, content, streaming }: Props) {
  if (role === "user") {
    // User: right-aligned pill, full-width container.
    return (
      <div className="flex justify-end">
        <div className="rounded-2xl bg-secondary px-4 py-2 max-w-[85%] whitespace-pre-wrap text-sm leading-relaxed">
          {content}
        </div>
      </div>
    );
  }

  // Empty + streaming → show a "Thinking…" shimmer instead of a blank bubble.
  if (streaming && !content.trim()) {
    return (
      <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
        <span className="inline-flex gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-bounce [animation-delay:-0.3s]" />
          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-bounce [animation-delay:-0.15s]" />
          <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/60 animate-bounce" />
        </span>
        <span className="bg-gradient-to-r from-muted-foreground via-foreground to-muted-foreground bg-[length:200%_100%] bg-clip-text text-transparent animate-shimmer">
          Thinking…
        </span>
      </div>
    );
  }

  // Assistant: flush-left markdown, no bubble background.
  return (
    <div className="prose prose-sm prose-invert max-w-none leading-relaxed
                    prose-p:my-3 prose-headings:mt-6 prose-headings:mb-3
                    prose-pre:bg-transparent prose-pre:p-0 prose-pre:my-3
                    prose-code:text-foreground prose-code:before:content-none
                    prose-code:after:content-none
                    prose-a:text-sky-400 hover:prose-a:text-sky-300">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code(props) {
            const { className, children, ...rest } = props as any;
            const match = /language-(\w+)/.exec(className ?? "");
            const isBlock = String(children).includes("\n") || match;
            if (!isBlock) {
              return (
                <code
                  className="rounded bg-secondary px-1.5 py-0.5 text-[0.875em] font-mono"
                  {...rest}
                >
                  {children}
                </code>
              );
            }
            return (
              <div className="rounded-lg border border-border overflow-hidden my-3">
                {match && (
                  <div className="bg-secondary/50 px-3 py-1 text-xs text-muted-foreground font-mono">
                    {match[1]}
                  </div>
                )}
                <SyntaxHighlighter
                  language={match?.[1] ?? "text"}
                  style={oneDark}
                  customStyle={{
                    margin: 0, padding: "0.75rem", background: "transparent",
                    fontSize: "0.85em",
                  }}
                  PreTag="div"
                >
                  {String(children).replace(/\n$/, "")}
                </SyntaxHighlighter>
              </div>
            );
          },
        }}
      >
        {healMarkdown(content) || " "}
      </ReactMarkdown>
      {streaming && (
        <span className="inline-block w-2 h-4 ml-1 bg-foreground animate-pulse align-middle" />
      )}
    </div>
  );
}

/** Close unterminated code fences so partial streams don't look broken. */
function healMarkdown(src: string): string {
  const fenceCount = (src.match(/^```/gm) ?? []).length;
  if (fenceCount % 2 === 1) return src + "\n```";
  return src;
}
