import { useEffect, useMemo, useState } from "react";
import { useStore, type SessionState, type ToolCallRecord } from "../../store";
import type {
  Artifact,
  ChecklistItemState,
  PathComparison,
  SearchResultCard,
  WealthSnapshot,
} from "../../types";
import { getJSON, postJSON } from "../../lib/api";
import { Button } from "../ui/button";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import {
  X,
  Loader2,
  CheckCircle2,
  XCircle,
  ExternalLink,
  Search,
  Braces,
  TerminalSquare,
} from "lucide-react";

const markdownComponents = {
  table: ({ children }: React.TableHTMLAttributes<HTMLTableElement>) => (
    <div className="my-6 overflow-x-auto rounded-2xl border border-border bg-secondary/10 shadow-sm">
      <table className="w-full min-w-[560px] border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }: React.HTMLAttributes<HTMLTableSectionElement>) => (
    <thead className="bg-secondary/50 text-left">{children}</thead>
  ),
  th: ({ children }: React.ThHTMLAttributes<HTMLTableCellElement>) => (
    <th className="border-b border-border px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
      {children}
    </th>
  ),
  td: ({ children }: React.TdHTMLAttributes<HTMLTableCellElement>) => (
    <td className="border-t border-border/70 px-4 py-3 align-top leading-6 text-foreground/95">
      {children}
    </td>
  ),
  tr: ({ children }: React.HTMLAttributes<HTMLTableRowElement>) => (
    <tr className="odd:bg-background/70 even:bg-background/40">{children}</tr>
  ),
  img: ({ src, alt }: React.ImgHTMLAttributes<HTMLImageElement>) => (
    <img
      src={src}
      alt={alt}
      className="my-6 w-full rounded-2xl border border-border bg-background shadow-sm"
    />
  ),
  a: ({ href, children }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="font-medium text-sky-400 underline decoration-sky-400/40 underline-offset-4 hover:text-sky-300"
    >
      {children}
    </a>
  ),
};

export function ArtifactPanel({ sessionId }: { sessionId: string }) {
  const session = useStore((s) => s.sessions[sessionId]);
  const ui = useStore((s) => s.ui);
  const closePanel = useStore((s) => s.closePanel);

  if (ui.panel.kind === "closed" || !session) return null;

  return (
    <div
      className="h-full flex flex-col border-l border-border bg-background"
      style={{ width: `${ui.panelWidthPct}%`, minWidth: 400 }}
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        {ui.panel.kind === "artifact" ? (
          <ArtifactHeader sessionId={sessionId} artifactId={ui.panel.artifactId} />
        ) : (
          <ToolHeader session={session} toolCallId={ui.panel.toolCallId} />
        )}
        <Button variant="ghost" size="icon" onClick={closePanel} aria-label="Close">
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="flex-1 overflow-auto">
        {ui.panel.kind === "artifact" ? (
          <ArtifactBody sessionId={sessionId} artifactId={ui.panel.artifactId} />
        ) : (
          <ToolBody session={session} toolCallId={ui.panel.toolCallId} />
        )}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Artifact view
 * -------------------------------------------------------------------------- */

function ArtifactHeader({
  sessionId,
  artifactId,
}: {
  sessionId: string;
  artifactId: string;
}) {
  const session = useStore((s) => s.sessions[sessionId]);
  const openArtifact = useStore((s) => s.openArtifact);
  const ui = useStore((s) => s.ui);
  const setArtifactView = useStore((s) => s.setArtifactView);
  if (!session) return null;

  const artifact = session.artifacts[artifactId];
  const order = session.artifactOrder;

  return (
    <div className="flex items-center gap-2 min-w-0">
      <select
        value={artifactId}
        onChange={(e) => openArtifact(e.target.value)}
        className="bg-transparent border border-input rounded-md px-2 py-1 text-sm max-w-[240px] truncate"
      >
        {order.map((id) => (
          <option key={id} value={id}>
            {session.artifacts[id]?.name ?? id.slice(0, 8)}
          </option>
        ))}
      </select>
      {artifact && (
        <div className="flex rounded-md border border-border overflow-hidden">
          <button
            className={`px-2 py-1 text-xs ${ui.artifactView === "preview" ? "bg-secondary" : ""}`}
            onClick={() => setArtifactView("preview")}
          >
            Preview
          </button>
          <button
            className={`px-2 py-1 text-xs ${ui.artifactView === "source" ? "bg-secondary" : ""}`}
            onClick={() => setArtifactView("source")}
          >
            Source
          </button>
        </div>
      )}
      {artifact && !artifact.finalized && (
        <span className="text-xs text-muted-foreground animate-pulse">Streaming…</span>
      )}
    </div>
  );
}

function ArtifactBody({
  sessionId,
  artifactId,
}: {
  sessionId: string;
  artifactId: string;
}) {
  const session = useStore((s) => s.sessions[sessionId]);
  const view = useStore((s) => s.ui.artifactView);
  if (!session) return null;
  const artifact = session.artifacts[artifactId];
  if (!artifact) {
    return <div className="p-4 text-muted-foreground text-sm">Artifact missing.</div>;
  }

  const content = artifact.content;

  if (view === "source") {
    const sourceLanguage =
      artifact.kind === "wealth_snapshot" || artifact.kind === "path_comparison"
        ? "json"
        : artifact.kind === "action_checklist"
          ? "markdown"
          : artifact.language ?? "text";
    return (
      <SyntaxHighlighter
        language={sourceLanguage}
        style={oneDark}
        customStyle={{ margin: 0, padding: "1rem", background: "transparent" }}
      >
        {content || " "}
      </SyntaxHighlighter>
    );
  }

  switch (artifact.kind) {
    case "app_preview": {
      const previewUrl = content.trim();
      if (!previewUrl) {
        return <div className="p-4 text-muted-foreground text-sm">Preview is not ready.</div>;
      }
      return (
        <div className="h-full bg-muted/20">
          <iframe
            title={artifact.name}
            src={previewUrl}
            sandbox="allow-scripts allow-forms"
            className="h-full w-full border-0"
          />
        </div>
      );
    }
    case "wealth_snapshot":
      return <WealthSnapshotPreview artifact={artifact} />;
    case "path_comparison":
      return <PathComparisonPreview sessionId={sessionId} artifact={artifact} />;
    case "action_checklist":
      return <ActionChecklistPreview artifact={artifact} />;
    case "pdf":
      return (
        <div className="h-full bg-muted/20">
          <iframe
            title={artifact.name}
            src={`/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}`}
            className="h-full w-full border-0"
          />
        </div>
      );
    case "image":
      return (
        <div className="flex h-full items-start justify-center bg-muted/20 p-6">
          <img
            src={`/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}`}
            alt={artifact.name}
            className="max-h-full max-w-full rounded-xl border border-border bg-background shadow-sm"
          />
        </div>
      );
    case "markdown":
      return (
        <div
          className="prose prose-sm prose-invert max-w-none px-6 py-6
                     prose-headings:mt-7 prose-headings:mb-3 prose-headings:font-semibold
                     prose-p:leading-7 prose-li:leading-7
                     prose-strong:text-foreground prose-code:text-sky-300
                     prose-pre:bg-transparent prose-pre:p-0
                     prose-hr:border-border"
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {healMarkdown(content) || " "}
          </ReactMarkdown>
        </div>
      );
    case "code":
    case "json":
    case "text":
    case "terminal_log":
      return (
        <SyntaxHighlighter
          language={
            artifact.language ??
            (artifact.kind === "json" ? "json" : artifact.kind === "terminal_log" ? "bash" : "text")
          }
          style={oneDark}
          customStyle={{ margin: 0, padding: "1rem", background: "transparent" }}
        >
          {content || " "}
        </SyntaxHighlighter>
      );
    default:
      return (
        <div className="p-4 text-sm text-muted-foreground">
          Artifact kind "{artifact.kind}" has no preview yet. Switch to Source.
        </div>
      );
  }
}

/* --------------------------------------------------------------------------
 * Tool view
 * -------------------------------------------------------------------------- */

function ToolHeader({ session, toolCallId }: { session: SessionState; toolCallId: string }) {
  const toolView = useStore((s) => s.ui.toolView);
  const setToolView = useStore((s) => s.setToolView);
  const tc = session.toolCalls[toolCallId];
  if (!tc) return null;

  return (
    <div className="flex items-center gap-2 min-w-0">
      <ToolStatusIcon tc={tc} />
      <span className="font-medium truncate">{tc.name}</span>
      <div className="flex rounded-md border border-border overflow-hidden ml-2">
        <button
          className={`px-2 py-1 text-xs ${toolView === "result" ? "bg-secondary" : ""}`}
          onClick={() => setToolView("result")}
        >
          Result
        </button>
        <button
          className={`px-2 py-1 text-xs ${toolView === "arguments" ? "bg-secondary" : ""}`}
          onClick={() => setToolView("arguments")}
        >
          Arguments
        </button>
      </div>
      {typeof tc.duration_ms === "number" && (
        <span className="text-xs text-muted-foreground ml-2">
          {Math.round(tc.duration_ms)}ms
        </span>
      )}
    </div>
  );
}

function ToolBody({ session, toolCallId }: { session: SessionState; toolCallId: string }) {
  const view = useStore((s) => s.ui.toolView);
  const tc = session.toolCalls[toolCallId];
  if (!tc) return null;

  if (view === "arguments") {
    return (
      <SyntaxHighlighter
        language="json"
        style={oneDark}
        customStyle={{ margin: 0, padding: "1rem", background: "transparent" }}
      >
        {JSON.stringify(tc.arguments, null, 2)}
      </SyntaxHighlighter>
    );
  }

  if (tc.status === "running") {
    return (
      <div className="p-6 text-sm text-muted-foreground flex items-center gap-2">
        <Loader2 className="h-4 w-4 animate-spin" /> Running…
      </div>
    );
  }

  if (tc.status === "denied") {
    return (
      <div className="p-6 text-sm text-destructive">
        Denied: {tc.reason ?? "no reason given"}
      </div>
    );
  }

  const parsed = parseStructuredContent(tc.content ?? "");
  const searchResults = tc.search_results ?? [];
  const generatedFiles = extractGeneratedFiles(tc.content ?? "");

  return (
    <div className="p-5 space-y-5">
      <ToolSummary tc={tc} parsed={parsed} />
      {searchResults.length > 0 && <SearchResultsSection cards={searchResults} />}
      {generatedFiles.length > 0 && <GeneratedFilesSection files={generatedFiles} />}
      {tc.name === "web_research" ? null : tc.name === "fetch_market_data" && parsed ? (
        <MarketDataView value={parsed} />
      ) : tc.name === "compute_indicator" && parsed ? (
        <IndicatorView value={parsed} />
      ) : tc.name === "run_backtest" && parsed ? (
        <BacktestResultView value={parsed} />
      ) : tc.name === "generate_chart" && parsed ? (
        <ChartResultView value={parsed} />
      ) : parsed ? (
        <StructuredPayloadView value={parsed} />
      ) : (
        <PlainToolOutput content={tc.content || ""} />
      )}
    </div>
  );
}

function ToolStatusIcon({ tc }: { tc: ToolCallRecord }) {
  if (tc.status === "running") {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;
  }
  if (tc.status === "completed") {
    return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  }
  return <XCircle className="h-4 w-4 text-destructive" />;
}

function healMarkdown(src: string): string {
  const fenceCount = (src.match(/^```/gm) ?? []).length;
  if (fenceCount % 2 === 1) return src + "\n```";
  return src;
}

function ToolSummary({
  tc,
  parsed,
}: {
  tc: ToolCallRecord;
  parsed: unknown;
}) {
  const stats = summarizePayload(parsed);
  return (
    <div className="rounded-2xl border border-border bg-secondary/20 p-4">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-lg bg-background/80 p-2 text-muted-foreground">
          {parsed ? <Braces className="h-4 w-4" /> : <TerminalSquare className="h-4 w-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">{prettyToolName(tc.name)}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {tc.status === "completed" ? "Completed" : "Finished with issues"}
            {typeof tc.duration_ms === "number" ? ` in ${Math.round(tc.duration_ms)}ms` : ""}
          </div>
          {stats.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {stats.map((item) => (
                <div
                  key={item.label}
                  className="rounded-full border border-border bg-background/80 px-3 py-1 text-xs"
                >
                  <span className="text-muted-foreground">{item.label}: </span>
                  <span>{item.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SearchResultsSection({ cards }: { cards: SearchResultCard[] }) {
  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Search className="h-4 w-4 text-muted-foreground" />
        <span>Sources</span>
      </div>
      <div className="grid gap-2">
        {cards.map((card) => (
          <a
            key={card.url}
            href={card.url}
            target="_blank"
            rel="noreferrer"
            className="group rounded-xl border border-border/80 bg-background/70 px-4 py-3 transition-colors hover:bg-secondary/25"
          >
            <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
              <span className="truncate">{formatCardMeta(card)}</span>
              <ExternalLink className="h-3.5 w-3.5 shrink-0 opacity-60 group-hover:opacity-100" />
            </div>
            <div className="mt-1.5 text-[15px] font-medium leading-5 text-sky-400 group-hover:underline">
              {card.title}
            </div>
            {card.snippet && (
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {card.snippet}
              </p>
            )}
          </a>
        ))}
      </div>
    </section>
  );
}

function GeneratedFilesSection({ files }: { files: string[] }) {
  return (
    <section className="space-y-3">
      <div className="text-sm font-medium">Generated Files</div>
      <div className="space-y-2">
        {files.map((file) => (
          <div
            key={file}
            className="rounded-xl border border-border bg-background/70 px-4 py-3 text-sm"
          >
            <div className="text-muted-foreground text-xs uppercase tracking-[0.14em]">
              Output
            </div>
            <div className="mt-1 break-all">{file}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function StructuredPayloadView({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return (
      <div className="space-y-3">
        {value.map((item, idx) => (
          <StructuredCard key={idx} label={`Item ${idx + 1}`} value={item} />
        ))}
      </div>
    );
  }

  if (value && typeof value === "object") {
    return (
      <div className="space-y-3">
        {Object.entries(value as Record<string, unknown>).map(([key, item]) => (
          <StructuredCard key={key} label={humanizeKey(key)} value={item} />
        ))}
      </div>
    );
  }

  return <PlainToolOutput content={String(value ?? "")} />;
}

function MarketDataView({ value }: { value: unknown }) {
  const data = asRecord(value);
  const latest = asRecord(data?.latest);
  const stats = asRecord(data?.stats);
  const recent = Array.isArray(data?.recent_data) ? data?.recent_data.slice(-3) : [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <StatCard label="Symbol" value={formatScalar(data?.symbol)} />
        <StatCard label="Range" value={formatScalar(data?.date_range || data?.period)} />
        <StatCard label="Close" value={formatPrice(latest?.close)} />
        <StatCard label="Volume" value={formatNumber(latest?.volume)} />
        <StatCard label="Period High" value={formatPrice(stats?.period_high)} />
        <StatCard label="Period Low" value={formatPrice(stats?.period_low)} />
      </div>
      {recent.length > 0 && (
        <div className="rounded-2xl border border-border bg-background/70 p-4">
          <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Recent Sessions</div>
          <div className="mt-3 space-y-2">
            {recent.map((item, idx) => {
              const row = asRecord(item);
              return (
                <div key={idx} className="flex items-center justify-between rounded-lg bg-secondary/20 px-3 py-2 text-sm">
                  <span className="text-muted-foreground">{formatScalar(row?.date)}</span>
                  <span>{formatPrice(row?.close)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function IndicatorView({ value }: { value: unknown }) {
  const data = asRecord(value);
  const latest = asRecord(data?.latest);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <StatCard label="Symbol" value={formatScalar(data?.symbol)} />
        <StatCard label="Indicator" value={formatScalar(data?.indicator)} />
        <StatCard label="Signal" value={formatScalar(data?.signal)} />
        <StatCard
          label="Latest"
          value={
            latest
              ? Object.entries(latest)
                  .map(([k, v]) => `${humanizeKey(k)} ${formatScalar(v)}`)
                  .join(" · ")
              : formatScalar(data?.latest_value)
          }
        />
      </div>
      {Array.isArray(data?.recent) && data.recent.length > 0 && (
        <div className="rounded-2xl border border-border bg-background/70 p-4">
          <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Recent Values</div>
          <div className="mt-3 space-y-2">
            {data.recent.map((item, idx) => {
              const row = asRecord(item);
              return (
                <div key={idx} className="flex items-center justify-between rounded-lg bg-secondary/20 px-3 py-2 text-sm">
                  <span className="text-muted-foreground">{formatScalar(row?.date)}</span>
                  <span>{formatScalar(row?.value)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function ChartResultView({ value }: { value: unknown }) {
  const data = asRecord(value);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <StatCard label="Symbol" value={formatScalar(data?.symbol)} />
        <StatCard label="Period" value={formatScalar(data?.period)} />
        <StatCard label="Data Points" value={formatScalar(data?.data_points)} />
        <StatCard
          label="Indicators"
          value={
            Array.isArray(data?.indicators)
              ? data.indicators.map((item) => formatScalar(item)).join(", ")
              : formatScalar(data?.indicators)
          }
        />
      </div>
      <div className="rounded-2xl border border-border bg-background/70 p-4">
        <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Saved Chart</div>
        <div className="mt-2 break-all text-sm">{formatScalar(data?.chart_saved)}</div>
      </div>
    </div>
  );
}

function BacktestResultView({ value }: { value: unknown }) {
  const data = asRecord(value);
  const trades = Array.isArray(data?.trades) ? data.trades.slice(0, 12) : [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <StatCard label="Symbol" value={formatScalar(data?.symbol)} />
        <StatCard label="Period" value={formatScalar(data?.period)} />
        <StatCard label="Initial Capital" value={formatMoney(data?.initial_capital)} />
        <StatCard label="Final Value" value={formatMoney(data?.final_value)} />
        <StatCard label="Strategy Return" value={formatPercent(data?.total_return_pct)} />
        <StatCard label="Buy & Hold" value={formatPercent(data?.buy_and_hold_return_pct)} />
        <StatCard label="Alpha" value={formatPercent(data?.alpha_pct)} />
        <StatCard label="Sharpe" value={formatMaybeNumber(data?.sharpe_ratio)} />
        <StatCard label="Max Drawdown" value={formatPercent(data?.max_drawdown_pct)} />
        <StatCard label="Win Rate" value={formatPercent(data?.win_rate_pct)} />
        <StatCard label="Trades" value={formatScalar(data?.total_trades)} />
      </div>
      {trades.length > 0 && (
        <div className="rounded-2xl border border-border bg-background/70 p-4">
          <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Recent Trades</div>
          <div className="mt-3 overflow-x-auto rounded-xl border border-border/80">
            <table className="w-full min-w-[360px] border-collapse text-sm">
              <thead className="bg-secondary/40 text-left">
                <tr>
                  <th className="px-3 py-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Date</th>
                  <th className="px-3 py-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Action</th>
                  <th className="px-3 py-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">Price</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((item, idx) => {
                  const row = asRecord(item);
                  const action = formatScalar(row?.action);
                  return (
                    <tr key={idx} className="border-t border-border/70 odd:bg-background/70 even:bg-background/40">
                      <td className="px-3 py-2 text-muted-foreground">{formatScalar(row?.date)}</td>
                      <td className="px-3 py-2">
                        <span
                          className={`rounded-full px-2 py-1 text-xs font-medium ${
                            action === "BUY"
                              ? "bg-emerald-500/15 text-emerald-400"
                              : action === "SELL"
                                ? "bg-rose-500/15 text-rose-400"
                                : "bg-secondary/40 text-foreground"
                          }`}
                        >
                          {action}
                        </span>
                      </td>
                      <td className="px-3 py-2">{formatMoney(row?.price)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function StructuredCard({ label, value }: { label: string; value: unknown }) {
  const isScalar =
    value == null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean";

  if (isScalar) {
    return (
      <div className="rounded-2xl border border-border bg-background/70 p-4">
        <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
        <div className="mt-2 text-sm leading-6">{formatScalar(value)}</div>
      </div>
    );
  }

  if (Array.isArray(value) && value.every((item) => item == null || typeof item !== "object")) {
    return (
      <div className="rounded-2xl border border-border bg-background/70 p-4">
        <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {value.map((item, idx) => (
            <span
              key={`${label}-${idx}`}
              className="rounded-full border border-border bg-secondary/30 px-3 py-1 text-xs"
            >
              {formatScalar(item)}
            </span>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-border bg-background/70 p-4">
      <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
      <div className="mt-3 grid gap-3">
        {Array.isArray(value)
          ? value.map((item, idx) => <StructuredCard key={`${label}-${idx}`} label={`Item ${idx + 1}`} value={item} />)
          : Object.entries(value as Record<string, unknown>).map(([key, item]) => (
              <StructuredCard key={`${label}-${key}`} label={humanizeKey(key)} value={item} />
            ))}
      </div>
    </div>
  );
}

function PlainToolOutput({ content }: { content: string }) {
  if (!content.trim()) {
    return (
      <div className="rounded-2xl border border-dashed border-border bg-background/60 p-6 text-sm text-muted-foreground">
        No result content.
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-border bg-background/70 p-4">
      <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Output</div>
      <div className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-foreground/95">
        {content}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-border bg-background/70 p-4">
      <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
      <div className="mt-2 text-sm leading-6">{value}</div>
    </div>
  );
}

function WealthSnapshotPreview({ artifact }: { artifact: Artifact }) {
  const data = useMemo(() => parseArtifactJson<WealthSnapshot>(artifact.content), [artifact.content]);
  if (!data) return <PlainToolOutput content={artifact.content} />;

  return (
    <div className="space-y-5 px-6 py-6">
      <div className="rounded-3xl border border-border bg-secondary/20 p-5">
        <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">Wealth Snapshot</div>
        <div className="mt-3 flex flex-wrap items-end gap-6">
          <div>
            <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Situation</div>
            <div className="mt-2 text-2xl font-semibold">{humanizeKey(data.situation)}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Net Worth</div>
            <div className="mt-2 text-lg">{formatMoney(data.net_worth)}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Liquid Net Worth</div>
            <div className="mt-2 text-lg">{formatMoney(data.liquid_net_worth)}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Emergency Buffer</div>
            <div className="mt-2 text-lg">
              {data.emergency_fund.months_covered.toFixed(1)} months
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <StatCard label="Cash" value={formatMoney(data.allocation.cash)} />
        <StatCard label="Retirement" value={formatMoney(data.allocation.retirement)} />
        <StatCard label="Brokerage" value={formatMoney(data.allocation.brokerage)} />
        <StatCard label="Employer Stock" value={formatMoney(data.allocation.rsus)} />
        <StatCard label="Home Equity" value={formatMoney(data.allocation.home_equity)} />
        <StatCard label="Debt" value={formatMoney(data.allocation.debt_total)} />
      </div>

      <div className="rounded-2xl border border-border bg-background/70 p-4">
        <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Flags</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {data.flags.length > 0 ? (
            data.flags.map((flag) => (
              <span key={flag} className="rounded-full border border-border bg-secondary/30 px-3 py-1 text-xs">
                {humanizeKey(flag)}
              </span>
            ))
          ) : (
            <span className="text-sm text-muted-foreground">No major flags.</span>
          )}
        </div>
      </div>

      <div className="rounded-2xl border border-border bg-background/70 p-4">
        <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Goals</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {data.goals.length > 0 ? (
            data.goals.map((goal) => (
              <span key={goal} className="rounded-full border border-border bg-background/70 px-3 py-1 text-xs">
                {goal}
              </span>
            ))
          ) : (
            <span className="text-sm text-muted-foreground">No goals attached.</span>
          )}
        </div>
      </div>
    </div>
  );
}

function PathComparisonPreview({
  sessionId,
  artifact,
}: {
  sessionId: string;
  artifact: Artifact;
}) {
  const data = useMemo(() => parseArtifactJson<PathComparison>(artifact.content), [artifact.content]);
  if (!data) return <PlainToolOutput content={artifact.content} />;

  async function choosePath(pathName: string) {
    await postJSON(`/sessions/${sessionId}/turns`, {
      user_input: `I want the ${pathName} path. Give me my action checklist.`,
    });
  }

  return (
    <div className="space-y-5 px-6 py-6">
      <div className="rounded-3xl border border-border bg-secondary/20 p-5">
        <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">Path Comparison</div>
        <div className="mt-2 text-lg font-medium">
          {humanizeKey(data.situation)} situation
        </div>
        <div className="mt-2 text-sm leading-6 text-muted-foreground">
          A short list of reasonable paths, framed as educational tradeoffs rather than directives.
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {data.paths.map((path) => (
          <div key={path.name} className="rounded-3xl border border-border bg-background/70 p-5">
            <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{path.name}</div>
            <div className="mt-2 text-lg font-medium">{path.headline}</div>
            <div className="mt-3 text-sm leading-6 text-muted-foreground">{path.best_for}</div>

            <div className="mt-5 grid gap-4">
              <ComparisonList title="Pros" items={path.pros} tone="positive" />
              <ComparisonList title="Tradeoffs" items={path.cons} tone="neutral" />
              <div>
                <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Concepts</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {path.required_concepts.map((concept) => (
                    <span
                      key={concept}
                      className="rounded-full border border-border bg-secondary/30 px-3 py-1 text-xs"
                    >
                      {concept}
                    </span>
                  ))}
                </div>
              </div>
              <Button className="mt-2 w-full" onClick={() => void choosePath(path.name)}>
                Choose this path
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ActionChecklistPreview({ artifact }: { artifact: Artifact }) {
  const sections = useMemo(() => parseChecklistSections(artifact.content), [artifact.content]);
  const [savedItems, setSavedItems] = useState<Record<number, ChecklistItemState>>({});
  const [pending, setPending] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const payload = await getJSON<{ items: ChecklistItemState[] }>(
          `/wealth/checklist?artifact_id=${encodeURIComponent(artifact.id)}`
        );
        if (!cancelled) {
          setSavedItems(
            Object.fromEntries(
              payload.items.map((item) => [item.item_index, item])
            )
          );
        }
      } catch {
        if (!cancelled) setSavedItems({});
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [artifact.id]);

  if (sections.length === 0) {
    return (
      <div
        className="prose prose-sm prose-invert max-w-none px-6 py-6
                   prose-headings:mt-7 prose-headings:mb-3 prose-headings:font-semibold"
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
          {healMarkdown(artifact.content) || " "}
        </ReactMarkdown>
      </div>
    );
  }

  async function toggleItem(item: ParsedChecklistItem) {
    const next = !(savedItems[item.itemIndex]?.completed ?? false);
    setPending(item.itemIndex);
    setSavedItems((current) => ({
      ...current,
      [item.itemIndex]: {
        artifact_id: artifact.id,
        item_index: item.itemIndex,
        text: item.text,
        completed: next,
      },
    }));
    try {
      await postJSON<void>("/wealth/checklist/toggle", {
        artifact_id: artifact.id,
        item_index: item.itemIndex,
        text: item.text,
        completed: next,
      });
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="space-y-5 px-6 py-6">
      {sections.map((section) => (
        <div key={section.title} className="rounded-3xl border border-border bg-background/70 p-5">
          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{section.title}</div>
          <div className="mt-4 space-y-3">
            {section.items.map((item) => {
              const checked = savedItems[item.itemIndex]?.completed ?? false;
              const disabled = pending === item.itemIndex;
              return (
                <label
                  key={item.itemIndex}
                  className={`flex items-start gap-3 rounded-2xl border px-4 py-3 transition-colors ${
                    checked
                      ? "border-emerald-500/25 bg-emerald-500/10"
                      : "border-border bg-secondary/15"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={checked}
                    disabled={disabled}
                    onChange={() => void toggleItem(item)}
                  />
                  <span className={`text-sm leading-6 ${checked ? "text-foreground/70 line-through" : ""}`}>
                    {item.text}
                  </span>
                </label>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function ComparisonList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "positive" | "neutral";
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{title}</div>
      <ul className="mt-3 space-y-2">
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-sm leading-6">
            <span className={tone === "positive" ? "text-emerald-400" : "text-muted-foreground"}>•</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type ParsedChecklistItem = { itemIndex: number; text: string };

function parseChecklistSections(content: string): Array<{ title: string; items: ParsedChecklistItem[] }> {
  const lines = content.split(/\r?\n/);
  const sections: Array<{ title: string; items: ParsedChecklistItem[] }> = [];
  let current: { title: string; items: ParsedChecklistItem[] } | null = null;
  let itemIndex = 0;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (line.startsWith("## ")) {
      current = { title: line.slice(3).trim(), items: [] };
      sections.push(current);
      continue;
    }
    const match = line.match(/^- \[( |x)\] (.+)$/i);
    if (match && current) {
      current.items.push({ itemIndex, text: match[2].trim() });
      itemIndex += 1;
    }
  }

  return sections;
}

function parseArtifactJson<T>(content: string): T | null {
  const parsed = parseStructuredContent(content);
  return parsed as T | null;
}

function parseStructuredContent(content: string): unknown | null {
  const trimmed = content.trim();
  if (!trimmed) return null;
  if (!(trimmed.startsWith("{") || trimmed.startsWith("["))) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

function extractGeneratedFiles(content: string): string[] {
  const marker = "[generated files]";
  const idx = content.indexOf(marker);
  if (idx === -1) return [];
  const tail = content.slice(idx + marker.length);
  return tail
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("- "))
    .map((line) => line.slice(2).trim())
    .filter(Boolean);
}

function summarizePayload(value: unknown): Array<{ label: string; value: string }> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const obj = value as Record<string, unknown>;
  const preferredKeys = [
    "symbol",
    "indicator",
    "signal",
    "period",
    "interval",
    "data_points",
    "chart_saved",
    "saved",
    "error",
  ];
  const out: Array<{ label: string; value: string }> = [];
  for (const key of preferredKeys) {
    const item = obj[key];
    if (item == null || typeof item === "object") continue;
    out.push({ label: humanizeKey(key), value: formatScalar(item) });
    if (out.length >= 5) break;
  }
  return out;
}

function formatScalar(value: unknown): string {
  if (value == null) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  return String(value);
}

function humanizeKey(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function prettyToolName(name: string): string {
  return name
    .split(/[_-]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function formatPrice(value: unknown): string {
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return formatScalar(value);
  return `$${num.toFixed(2)}`;
}

function formatNumber(value: unknown): string {
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return formatScalar(value);
  return new Intl.NumberFormat().format(num);
}

function formatMoney(value: unknown): string {
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return formatScalar(value);
  return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatPercent(value: unknown): string {
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return formatScalar(value);
  return `${num.toFixed(2)}%`;
}

function formatMaybeNumber(value: unknown): string {
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return formatScalar(value);
  return `${num}`;
}

function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function formatCardMeta(card: SearchResultCard): string {
  const source = card.source || hostname(card.url);
  if (card.timestamp) return `${card.timestamp} · ${source}`;
  return source;
}
