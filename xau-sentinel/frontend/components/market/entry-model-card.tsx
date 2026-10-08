"use client";

import { Panel } from "@/components/layout/panel";
import { Disclosure } from "@/components/layout/disclosure";
import { Badge } from "@/components/ui/badge";
import { KindTag } from "@/components/analysis/shared";
import { formatPrice } from "@/lib/format";
import { biasLabel, CHECK_MARK, FLOW_STAGES, flowStageStatus, headline, stateLabel } from "@/lib/entry-model";
import type { EntryModelChecklistItem, EntryModelEvidence, EntryModelResult } from "@/lib/types";

/** The single strongest piece of supporting evidence across the 15M and 5M layers -- whichever
 * exists first, since 5M confirmation only ever adds to a 15M setup that already has its own. Shown
 * next to the contradicting-evidence warnings so a developing/confirmed setup isn't represented by
 * its objections alone. */
function strongestEvidence(result: EntryModelResult): EntryModelEvidence | null {
  return result.setup_15m?.supporting_evidence[0] ?? result.confirmation_5m?.supporting_evidence[0] ?? null;
}

const FLOW_STATUS_CLS: Record<"done" | "active" | "pending", string> = {
  done: "bg-bullish/15 text-bullish border-bullish/30",
  active: "bg-info/15 text-info border-info/30",
  pending: "bg-muted/30 text-muted-foreground border-border",
};

function FlowDiagram({ state }: { state: string }) {
  return (
    <div className="flex items-center gap-1 overflow-x-auto">
      {FLOW_STAGES.map((s, i) => {
        const status = flowStageStatus(state, s.reachedAt);
        return (
          <div key={s.key} className="flex items-center gap-1 shrink-0">
            {i > 0 && <span className="text-muted-foreground text-xs">→</span>}
            <div className={`rounded-md border px-2 py-1 text-center ${FLOW_STATUS_CLS[status]}`}>
              <div className="text-[10px] font-semibold uppercase tracking-wide">{s.label}</div>
              <div className="text-[9px] opacity-80">{s.sub}</div>
            </div>
          </div>
        );
      })}
      <span className="text-muted-foreground text-xs">→</span>
      <div className={`rounded-md border px-2 py-1 text-center ${
        state === "ENTRY_READY" ? FLOW_STATUS_CLS.done : FLOW_STATUS_CLS.pending}`}>
        <div className="text-[10px] font-semibold uppercase tracking-wide">Entry</div>
      </div>
    </div>
  );
}

function ChecklistList({ items }: { items: EntryModelChecklistItem[] }) {
  return (
    <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
      {items.map((c) => {
        const mark = CHECK_MARK[c.status] ?? CHECK_MARK.WAITING;
        return (
          <li key={c.name} className="flex items-center gap-2 text-xs" title={c.reason}>
            <span aria-hidden className={`w-3 text-center font-semibold ${mark.cls}`}>{mark.glyph}</span>
            <span className="text-foreground">{c.name}</span>
            <span className="text-[10px] text-muted-foreground">{c.timeframe}</span>
            <span className={`ml-auto text-[10px] ${mark.cls}`}>{mark.label}</span>
          </li>
        );
      })}
    </ul>
  );
}

function EvidenceList({ items, tone }: { items: EntryModelEvidence[]; tone: "support" | "contra" }) {
  if (items.length === 0) return null;
  return (
    <ul className="flex flex-col gap-0.5">
      {items.map((e, i) => (
        <li key={`${e.kind}-${e.timestamp}-${i}`} className={tone === "contra" ? "text-warning" : "text-foreground"}>
          {tone === "contra" ? "⚠ " : ""}
          <span className="font-mono text-[10px] text-muted-foreground">{e.timeframe} {e.timestamp.slice(0, 16)}</span>{" "}
          {e.kind}{e.value !== null ? ` @ ${formatPrice(e.value)}` : ""} — {e.note}
        </li>
      ))}
    </ul>
  );
}

export function EntryModelCard({ result }: { result: EntryModelResult | null }) {
  if (!result) {
    return (
      <Panel title="Entry model" density="compact">
        <p className="text-xs text-muted-foreground">Waiting for the first evaluation.</p>
      </Panel>
    );
  }
  const { higher_timeframe: htf, intraday, setup_15m: setup, confirmation_5m: confirmation,
    precision_1m: precision, entry_candidate: candidate, confidence: conf } = result;

  return (
    <Panel
      title="Entry model"
      density="compact"
      action={<Badge variant={result.direction && result.direction !== "CONFLICTED" ? "info" : "outline"}>
        {stateLabel(result.state)}
      </Badge>}
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm font-semibold text-foreground">{headline(result.direction, result.symbol)}</p>
          {conf && (
            <p className="text-xs text-muted-foreground">
              Setup confidence <span className="font-mono text-foreground">{conf.score}/100</span> · {conf.label}
              <span className="ml-1 text-[10px]">(heuristic)</span>
            </p>
          )}
        </div>

        <FlowDiagram state={result.state} />

        <div className="flex items-center gap-2">
          <KindTag kind="interpreted" />
          <span className="text-[10px] text-muted-foreground">derived bias/state per rung, not raw facts</span>
        </div>
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">HTF context</dt>
            <dd className="text-xs font-semibold text-foreground">{htf ? biasLabel(htf.htf_context) : "—"}</dd>
          </div>
          <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">HTF location</dt>
            <dd className="text-xs font-semibold text-foreground">{htf ? stateLabel(htf.htf_location) : "—"}</dd>
          </div>
          <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">1H bias</dt>
            <dd className="text-xs font-semibold text-foreground">{intraday ? biasLabel(intraday.intraday_bias) : "—"}</dd>
          </div>
          <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">15M setup</dt>
            <dd className="text-xs font-semibold text-foreground">{setup ? stateLabel(setup.setup_status) : "—"}</dd>
          </div>
        </dl>

        <dl className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">Entry</dt>
            <dd className="text-xs font-semibold font-mono text-foreground">
              {candidate ? formatPrice(candidate.entry) : "Waiting"}
            </dd>
          </div>
          <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">Stop</dt>
            <dd className="text-xs font-semibold font-mono text-foreground">
              {candidate?.stop ? formatPrice(candidate.stop.price) : "—"}
            </dd>
          </div>
          <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">Target</dt>
            <dd className="text-xs font-semibold font-mono text-foreground">
              {candidate?.target ? formatPrice(candidate.target.price) : "—"}
            </dd>
          </div>
          <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
            <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">R:R</dt>
            <dd className="text-xs font-semibold font-mono text-foreground">
              {candidate?.rr == null ? "—" : `1:${candidate.rr.toFixed(2)}`}
            </dd>
          </div>
        </dl>

        <div className="flex items-center gap-2">
          <KindTag kind="conditional" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
          <p>
            <span className="text-muted-foreground">Invalidated if: </span>
            <span className="text-foreground">
              {result.invalidation?.text ?? candidate?.invalidation?.basis ?? "—"}
            </span>
          </p>
          <p>
            <span className="text-muted-foreground">Next: </span>
            <span className="text-foreground">{result.next_condition?.text ?? "none"}</span>
          </p>
        </div>

        {(() => {
          const strongest = strongestEvidence(result);
          if (!strongest && result.contradicting_evidence.length === 0) return null;
          return (
            <div className="flex flex-col gap-1">
              <KindTag kind="observed" />
              {strongest && (
                <p className="text-xs text-foreground" data-testid="strongest-evidence">
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {strongest.timeframe} {strongest.timestamp.slice(0, 16)}
                  </span>{" "}
                  {strongest.kind}{strongest.value !== null ? ` @ ${formatPrice(strongest.value)}` : ""} — {strongest.note}
                </p>
              )}
              {result.contradicting_evidence.length > 0 && (
                <ul className="flex flex-col gap-0.5 text-xs text-warning">
                  {result.contradicting_evidence.map((e, i) => (
                    <li key={`${e.kind}-${i}`}>⚠ {e.note}</li>
                  ))}
                </ul>
              )}
            </div>
          );
        })()}

        <Disclosure title="Evidence and detail" summary="checklists, confidence, FVG, OTE, key areas, timestamps">
          <div className="flex flex-col gap-3 text-xs">
            {conf && (
              <div>
                <p className="mb-1 font-semibold text-foreground">Confidence breakdown</p>
                <ul className="flex flex-col gap-0.5">
                  {conf.positive.map((e, i) => (
                    <li key={`${e.name}-${i}`} className="text-foreground">+{e.points} {e.reason || e.name}</li>
                  ))}
                  {conf.negative.map((e, i) => (
                    <li key={`${e.name}-${i}`} className="text-bearish">{e.points} {e.reason}</li>
                  ))}
                </ul>
                <p className="mt-1 text-[10px] text-muted-foreground">{conf.note}</p>
              </div>
            )}

            {htf && (
              <div>
                <p className="mb-1 font-semibold text-foreground">1D / 4H — Higher-timeframe location &amp; context</p>
                <ChecklistList items={htf.checklist} />
                {htf.nearest_area && (
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    Nearest area: {htf.nearest_area.side} {formatPrice(htf.nearest_area.low)}–{formatPrice(htf.nearest_area.high)}
                    {" "}({htf.nearest_area.strength.toLowerCase()}, {htf.relation?.toLowerCase()})
                  </p>
                )}
              </div>
            )}

            {intraday && (
              <div>
                <p className="mb-1 font-semibold text-foreground">1H — Intraday bias</p>
                <ChecklistList items={intraday.checklist} />
              </div>
            )}

            {setup && (
              <div>
                <p className="mb-1 font-semibold text-foreground">15M — Setup formation</p>
                <ChecklistList items={setup.checklist} />
                {setup.fvg && (
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    FVG: {setup.fvg.direction} {formatPrice(setup.fvg.low)}–{formatPrice(setup.fvg.high)} ({setup.fvg.status.toLowerCase()})
                  </p>
                )}
                {setup.ote && (
                  <p className="text-[10px] text-muted-foreground">
                    OTE overlap: {String(setup.ote.overlap ?? "—")}
                  </p>
                )}
                <EvidenceList items={setup.supporting_evidence} tone="support" />
                <EvidenceList items={setup.contradicting_evidence} tone="contra" />
              </div>
            )}

            {confirmation && (
              <div>
                <p className="mb-1 font-semibold text-foreground">5M — Entry confirmation</p>
                <ChecklistList items={confirmation.checklist} />
                <EvidenceList items={confirmation.supporting_evidence} tone="support" />
                <EvidenceList items={confirmation.contradicting_evidence} tone="contra" />
              </div>
            )}

            {precision && precision.precision_status !== "NOT_APPLICABLE" && (
              <div>
                <p className="mb-1 font-semibold text-foreground">1M — Precision (optional)</p>
                <ChecklistList items={precision.checklist} />
                {precision.trigger && (
                  <p className="mt-1 text-[10px] text-muted-foreground">
                    Trigger: {precision.trigger.event_type} at {precision.trigger.time_utc}
                  </p>
                )}
              </div>
            )}

            <p className="text-[10px] text-muted-foreground">{result.disclaimer}</p>
          </div>
        </Disclosure>
      </div>
    </Panel>
  );
}
