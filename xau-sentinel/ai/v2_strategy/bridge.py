"""Maps Analysis Engine V2 output onto the facts the A+ decision reads.

    V2 (describes market state) -> this bridge (maps fields only) -> A+ rules (decide)

The bridge never recomputes a market fact. Every field is read from V2's
structured output (AnalysisV2.observations, .observations.structure, .status),
which V2 already produced from the same primitives the legacy path uses.

Two things are deliberately NOT taken from V2, and the reason is recorded here
so the comparison can report them:

- Entry price. A+ entry uses the forming M5 close (the documented exception in
  analysis/structure.py::closed_only). V2 reports the last CLOSED close. The
  bridge keeps A+'s entry semantics, so entry is read from the raw candles.
- The M5 sequence after a sweep (MSS, displacement, retracement). V2 does not
  compute it; it lives in analysis/sequence.py. The decision step runs that
  existing module on the closed M5 bars, same as the legacy path.

The FundedNext gate is not market analysis, so it is never part of V2 or this
bridge; it is passed to the decision unchanged.
"""
from ai.strategy import rules
from analysis.structure import StructureResult, closed_only
from analysis.v2.engine import AnalysisV2
from analysis.v2.observations import TimeframeStructure
from ai.strategy.facts import StrategyFacts


class V2NotEvaluable(Exception):
    """V2 cannot support an A+ read: insufficient closed history or no usable price."""


def _structure(ts: TimeframeStructure) -> StructureResult:
    # The A+ decision reads state, reason, last_mss and last_bos only, never swings.
    return StructureResult(state=ts.state, swings=[], last_bos=ts.last_bos, last_mss=ts.last_mss, reason=ts.reason)


def facts_from_v2(analysis: AnalysisV2, candles: dict) -> StrategyFacts:
    """A+ facts read from a V2 analysis of the same `candles`. Raises V2NotEvaluable
    when V2 cannot support a read, so the caller can say so instead of guessing."""
    if analysis.status == "INSUFFICIENT_DATA" or analysis.observations is None or not analysis.observations.ready:
        issues = "; ".join(analysis.observations.data_issues) if analysis.observations else "no closed M5 bars"
        raise V2NotEvaluable(f"V2 status {analysis.status}: {issues or 'no usable data'}")

    obs = analysis.observations
    candidate_seq = _candidate_sequence(analysis, obs.sweeps)
    sequence = candidate_seq.evidence if candidate_seq is not None else None
    chronology_ok = candidate_seq.chronology_ok if candidate_seq is not None else True
    ordering = candidate_seq.ordering if candidate_seq is not None else None
    return StrategyFacts(
        h4=_structure(obs.structure["H4"]),
        h1=_structure(obs.structure["H1"]),
        m15=_structure(obs.structure["M15"]),
        m5=_structure(obs.structure["M5"]),
        zones=dict(obs.zones),
        sweeps=list(obs.sweeps),
        equal_levels=list(obs.equal_levels),
        m5_closed=closed_only({"M5": candles["M5"]})["M5"],
        current_price=float(candles["M5"]["close"].iloc[-1]),  # A+ entry semantics, see module docstring
        data_stale=analysis.status == "STALE",
        sequence=sequence,
        sequence_chronology_ok=chronology_ok,
        sequence_ordering=ordering,
    )


def _candidate_sequence(analysis: AnalysisV2, sweeps):
    """The V2 MarketSequence for the sweep A+ treats as its candidate. A+ selects the most
    recent sweep, and the sequence must belong to that same sweep. If V2 has no
    sequence for it, V2 cannot support the read. The caller reads both the evidence and
    the chronology flag from the returned sequence."""
    candidate = rules.select_candidate(list(sweeps))
    if candidate is None:
        return None
    for seq in analysis.sequences:
        if seq.sweep.kind == candidate.kind and seq.sweep.time == candidate.time:
            return seq
    raise V2NotEvaluable("V2 has no sequence for the candidate sweep at " + str(candidate.time))
