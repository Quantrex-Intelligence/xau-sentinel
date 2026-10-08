"""Offline reference of the LuxAlgo 'ICT Concepts' detection logic (Pine v5), for the audit only.

Not production code and not a port. It reproduces the Pine rules on CLOSED bars, bar by bar, so the
output can be compared with Analysis Engine V2 on identical raw data.

Pine rules that are interpreted (assumptions, to be checked against TradingView):
  A1  ta.pivothigh(src, L, R) at bar t reports the pivot at bar p = t - R when src[p] >= every src in the
      L bars before it and src[p] > every src in the R bars after it.  (pivotlow mirrors this.)
  A2  ta.atr(n) is Wilder's RMA of true range, seeded with the SMA of the first n true ranges.
  A3  The zigzag keeps 50 points, newest at index 0. A new pivot of the same direction as index 0 replaces it
      only when it is more extreme (the extension rule in the source).
  A4  Pine `switch` runs the first case whose condition is true on that bar.
  A5  Pine arrays are fixed size. Liquidity boxes and FVG boxes keep only the visible count (2 each by default),
      older ones are deleted, so their state is no longer updated.
"""
import math

import numpy as np

# Defaults from the pasted source.
MS_LEN = 5            # Market Structures 'Length' (also the meanBody window)
PERC_BODY = 0.36      # wick/body limit for the displacement candle
BX_BACK = 10          # FVG break loop limit (bxBack)
VIS_LIQ = 2           # '# Visible Liq. boxes'
LIQ_A = 10 / 4        # a = 10 / input(4) ; liquidity margin = ATR / a = ATR / 2.5
VIS_BXS = 2           # '# Visible FVG's'
OB_LEN = 10           # Order Blocks 'Swing Lookback'
SHOW_BULL = 1
SHOW_BEAR = 1
ATR_LEN = 10          # atr = ta.atr(10)
MAX_SIZE = 50


def wilder_atr(h, l, c, n):
    N = len(h)
    tr = np.empty(N)
    tr[0] = h[0] - l[0]
    for i in range(1, N):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = np.full(N, np.nan)
    if N >= n:
        atr[n - 1] = tr[:n].mean()
        for i in range(n, N):
            atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def sma(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = x[i - n + 1:i + 1].mean()
    return out


def pivot_high(h, t, left, right):
    """ta.pivothigh(h, left, right) evaluated at bar t. Returns (p, value) or None. Rule A1."""
    p = t - right
    if p - left < 0 or t >= len(h):
        return None
    v = h[p]
    if all(v >= h[p - k] for k in range(1, left + 1)) and all(v > h[p + k] for k in range(1, right + 1)):
        return p, v
    return None


def pivot_low(l, t, left, right):
    p = t - right
    if p - left < 0 or t >= len(l):
        return None
    v = l[p]
    if all(v <= l[p - k] for k in range(1, left + 1)) and all(v < l[p + k] for k in range(1, right + 1)):
        return p, v
    return None


def run(o, h, l, c, mode_present=True):
    """Returns a dict of event lists. Bar indices refer to the input arrays (closed bars only)."""
    o, h, l, c = (np.asarray(a, dtype=float) for a in (o, h, l, c))
    N = len(c)
    body = np.abs(c - o)
    mx = np.maximum(c, o)
    mn = np.minimum(c, o)
    meanBody = sma(body, MS_LEN)
    atr = wilder_atr(h, l, c, ATR_LEN)

    # Candle classes (L_body, L_bodyUP, L_bodyDN) per bar.
    L_body = np.array([(h[t] - mx[t] < body[t] * PERC_BODY) and (mn[t] - l[t] < body[t] * PERC_BODY) for t in range(N)])
    ok = ~np.isnan(meanBody)
    L_bodyUP = np.zeros(N, bool)
    L_bodyDN = np.zeros(N, bool)
    for t in range(N):
        if ok[t]:
            L_bodyUP[t] = body[t] > meanBody[t] and L_body[t] and c[t] > o[t]
            L_bodyDN[t] = body[t] > meanBody[t] and L_body[t] and c[t] < o[t]

    ev = {"displacement_up": [], "displacement_dn": [], "fvg": [], "fvg_partial": [], "fvg_break": [],
          "liq_high": [], "liq_low": [], "liq_broken": [], "mss": [], "bos": [], "ob_bull": [], "ob_bear": [],
          "ob_breaker": [], "zigzag_extension": [], "fvg_dropped": []}
    for t in range(N):
        if L_bodyUP[t]:
            ev["displacement_up"].append(t)
        if L_bodyDN[t]:
            ev["displacement_dn"].append(t)

    # ---- zigzag, liquidity, MSS/BOS (the draw() routine) ----------------------------------------
    d = [0] * MAX_SIZE
    x = [0] * MAX_SIZE
    y = [0.0] * MAX_SIZE
    last_liq_B = None
    last_liq_S = None
    liq_boxes = {"high": [], "low": []}     # visible boxes per side, newest first (VIS_LIQ)
    mss_dir = 0
    bos_bl, mss_bl, bos_br, mss_br = [], [], [], []

    for t in range(N):
        a_t = atr[t]
        margin = a_t / LIQ_A if not math.isnan(a_t) else float("nan")
        ph = pivot_high(h, t, MS_LEN, 1) if t >= 1 else None
        pl = pivot_low(l, t, MS_LEN, 1) if t >= 1 else None

        if ph is not None:
            p, phv = ph
            dir_ = d[0]
            y1 = y[0]
            if dir_ < 1:
                d.insert(0, 1); x.insert(0, p); y.insert(0, h[p])
                d.pop(); x.pop(); y.pop()
            elif dir_ == 1 and phv > y1:
                x[0], y[0] = p, h[p]
                ev["zigzag_extension"].append((t, "high", p))
            if not math.isnan(margin):
                count, st_B, st_P, minP, maxP = 0, 0, 0.0, 0.0, 1e7
                for i in range(MAX_SIZE):
                    if d[i] == 1:
                        if y[i] > phv + margin:
                            break
                        if phv - margin < y[i] < phv + margin:
                            count += 1
                            st_B, st_P = x[i], y[i]
                            minP = max(minP, y[i]); maxP = min(maxP, y[i])
                if count > 2 and st_B != last_liq_B:
                    last_liq_B = st_B
                    ev["liq_high"].append({"t": t, "pivot_bar": p, "anchor_bar": st_B, "anchor_px": st_P,
                                           "count": count, "mid": (minP + maxP) / 2})
                    liq_boxes["high"].insert(0, {"anchor": st_B, "top": (minP + maxP) / 2 + margin,
                                                 "bot": (minP + maxP) / 2 - margin, "broken": False, "t0": t})
                    if len(liq_boxes["high"]) > VIS_LIQ:
                        liq_boxes["high"].pop()

        if pl is not None:
            p, plv = pl
            dir_ = d[0]
            y1 = y[0]
            if dir_ > -1:
                d.insert(0, -1); x.insert(0, p); y.insert(0, l[p])
                d.pop(); x.pop(); y.pop()
            elif dir_ == -1 and plv < y1:
                x[0], y[0] = p, l[p]
                ev["zigzag_extension"].append((t, "low", p))
            if not math.isnan(margin):
                count, st_B, st_P, minP, maxP = 0, 0, 0.0, 0.0, 1e7
                for i in range(MAX_SIZE):
                    if d[i] == -1:
                        if y[i] < plv - margin:
                            break
                        if plv - margin < y[i] < plv + margin:
                            count += 1
                            st_B, st_P = x[i], y[i]
                            minP = max(minP, y[i]); maxP = min(maxP, y[i])
                if count > 2 and st_B != last_liq_S:
                    last_liq_S = st_B
                    ev["liq_low"].append({"t": t, "pivot_bar": p, "anchor_bar": st_B, "anchor_px": st_P,
                                          "count": count, "mid": (minP + maxP) / 2})
                    liq_boxes["low"].insert(0, {"anchor": st_B, "top": (minP + maxP) / 2 + margin,
                                                "bot": (minP + maxP) / 2 - margin, "broken": False, "t0": t})
                    if len(liq_boxes["low"]) > VIS_LIQ:
                        liq_boxes["low"].pop()

        # Liquidity broken state (checked every bar on visible boxes). Broken = close beyond the far edge.
        for bx in liq_boxes["high"]:
            if not bx["broken"] and c[t] > bx["top"]:
                bx["broken"] = True
                ev["liq_broken"].append({"t": t, "side": "high", "anchor_bar": bx["anchor"]})
        for bx in liq_boxes["low"]:
            if not bx["broken"] and c[t] < bx["bot"]:
                bx["broken"] = True
                ev["liq_broken"].append({"t": t, "side": "low", "anchor_bar": bx["anchor"]})

        # MSS / BOS (every bar, Rule A4 = first matching case)
        iH = 2 if d[2] == 1 else 1
        iL = 2 if d[2] == -1 else 1
        if c[t] > y[iH] and d[iH] == 1 and mss_dir < 1:
            mss_dir = 1
            bos_bl, mss_bl = [], [y[iH]]          # Present mode clears the lines on a new MSS
            ev["mss"].append({"t": t, "dir": "bullish", "level": y[iH], "from": x[iH]})
        elif c[t] < y[iL] and d[iL] == -1 and mss_dir > -1:
            mss_dir = -1
            bos_br, mss_br = [], [y[iL]]
            ev["mss"].append({"t": t, "dir": "bearish", "level": y[iL], "from": x[iL]})
        elif mss_dir == 1 and c[t] > y[iH]:
            if bos_bl:
                add = y[iH] != bos_bl[0] and y[iH] != mss_bl[0]
            else:
                add = y[iH] != mss_bl[0]
            if add:
                bos_bl.insert(0, y[iH])
                ev["bos"].append({"t": t, "dir": "bullish", "level": y[iH], "from": x[iH]})
        elif mss_dir == -1 and c[t] < y[iL]:
            if bos_br:
                add = y[iL] != bos_br[0] and y[iL] != mss_br[0]
            else:
                add = y[iL] != mss_br[0]
            if add:
                bos_br.insert(0, y[iL])
                ev["bos"].append({"t": t, "dir": "bearish", "level": y[iL], "from": x[iL]})

    # ---- FVG (i_FVG = 'FVG'), mitigation on the visible boxes only (Rule A5) -----------------
    up_boxes, dn_boxes = [], []      # newest first
    for t in range(2, N):
        imbUP = L_bodyUP[t - 1] and l[t] > h[t - 2]
        imbDN = L_bodyDN[t - 1] and h[t] < l[t - 2]
        if imbUP:
            if t >= 1 and L_bodyUP[t - 2] and (t - 1) >= 2 and l[t - 1] > h[t - 3]:
                # consecutive imbalance: the source updates the existing box
                if up_boxes:
                    up_boxes[0].update({"top": l[t], "bot": h[t - 2]})
            else:
                up_boxes.insert(0, {"formed": t, "top": l[t], "bot": h[t - 2], "active": True, "partial": None,
                                    "break": None})
                if len(up_boxes) > VIS_BXS:
                    gone = up_boxes.pop()
                    if gone["active"]:
                        ev["fvg_dropped"].append({"t": t, "dir": "bullish", "formed": gone["formed"]})
                ev["fvg"].append({"t": t, "dir": "bullish", "top": l[t], "bot": h[t - 2], "mid_disp": True})
        if imbDN:
            if L_bodyDN[t - 2] and (t - 1) >= 2 and h[t - 1] < l[t - 3]:
                if dn_boxes:
                    dn_boxes[0].update({"top": l[t - 2], "bot": h[t]})
            else:
                dn_boxes.insert(0, {"formed": t, "top": l[t - 2], "bot": h[t], "active": True, "partial": None,
                                    "break": None})
                if len(dn_boxes) > VIS_BXS:
                    gone = dn_boxes.pop()
                    if gone["active"]:
                        ev["fvg_dropped"].append({"t": t, "dir": "bearish", "formed": gone["formed"]})
                ev["fvg"].append({"t": t, "dir": "bearish", "top": l[t - 2], "bot": h[t], "mid_disp": True})
        # mitigation, same bar, on the visible boxes (bxBack bounds the loop; visible count is the real limit)
        for bx in up_boxes[:BX_BACK]:
            if bx["active"]:
                if bx["partial"] is None and l[t] < bx["top"] and bx["formed"] < t:
                    bx["partial"] = t
                    ev["fvg_partial"].append({"t": t, "dir": "bullish", "formed": bx["formed"]})
                if l[t] < bx["bot"]:
                    bx["active"] = False
                    bx["break"] = t
                    ev["fvg_break"].append({"t": t, "dir": "bullish", "formed": bx["formed"]})
        for bx in dn_boxes[:BX_BACK]:
            if bx["active"]:
                if bx["partial"] is None and h[t] > bx["bot"] and bx["formed"] < t:
                    bx["partial"] = t
                    ev["fvg_partial"].append({"t": t, "dir": "bearish", "formed": bx["formed"]})
                if h[t] > bx["top"]:
                    bx["active"] = False
                    bx["break"] = t
                    ev["fvg_break"].append({"t": t, "dir": "bearish", "formed": bx["formed"]})

    # ---- Order blocks (swings(10) + body rules), and breakers ------------------------------------
    os_state = 0
    top_sw = None      # dict(y, x, crossed)
    btm_sw = None
    bull_obs, bear_obs = [], []
    for t in range(OB_LEN, N):
        upper = h[t - OB_LEN + 1:t + 1].max()
        lower = l[t - OB_LEN + 1:t + 1].min()
        prev = os_state
        if h[t - OB_LEN] > upper:
            os_state = 0
        elif l[t - OB_LEN] < lower:
            os_state = 1
        if os_state == 0 and prev != 0:
            top_sw = {"y": h[t - OB_LEN], "x": t - OB_LEN, "crossed": False}
        if os_state == 1 and prev != 1:
            btm_sw = {"y": l[t - OB_LEN], "x": t - OB_LEN, "crossed": False}

        if top_sw is not None and c[t] > top_sw["y"] and not top_sw["crossed"]:
            top_sw["crossed"] = True
            minima, maxima, loc = mx[t - 1], mn[t - 1], t - 1
            for j in range(t - 1, top_sw["x"], -1):
                minima = min(mn[j], minima)
                if minima == mn[j]:
                    maxima = mx[j]
                    loc = j
            bull_obs.insert(0, {"top": maxima, "btm": minima, "loc": loc, "created": t, "breaker": False})
            ev["ob_bull"].append({"t": t, "loc": loc, "top": maxima, "btm": minima, "swing_x": top_sw["x"]})
        for ob in list(bull_obs):
            if not ob["breaker"]:
                if min(c[t], o[t]) < ob["btm"]:
                    ob["breaker"] = True
                    ev["ob_breaker"].append({"t": t, "dir": "bullish", "loc": ob["loc"]})
            elif c[t] > ob["top"]:
                bull_obs.remove(ob)

        if btm_sw is not None and c[t] < btm_sw["y"] and not btm_sw["crossed"]:
            btm_sw["crossed"] = True
            maxima, minima, loc = mx[t - 1], mn[t - 1], t - 1
            maxima_ = mx[t - 1]
            minima_ = mn[t - 1]
            for j in range(t - 1, btm_sw["x"], -1):
                maxima_ = max(mx[j], maxima_)
                if maxima_ == mx[j]:
                    minima_ = mn[j]
                    loc = j
            bear_obs.insert(0, {"top": maxima_, "btm": minima_, "loc": loc, "created": t, "breaker": False})
            ev["ob_bear"].append({"t": t, "loc": loc, "top": maxima_, "btm": minima_, "swing_x": btm_sw["x"]})
        for ob in list(bear_obs):
            if not ob["breaker"]:
                if max(c[t], o[t]) > ob["top"]:
                    ob["breaker"] = True
                    ev["ob_breaker"].append({"t": t, "dir": "bearish", "loc": ob["loc"]})
            elif c[t] < ob["btm"]:
                bear_obs.remove(ob)

    ev["ohlc"] = (o, h, l, c)
    # End-of-window state, used by the chart overlay (what LuxAlgo would show as current).
    ev["state"] = {"fvg_up": up_boxes, "fvg_dn": dn_boxes, "liq_high": liq_boxes["high"],
                   "liq_low": liq_boxes["low"], "ob_bull": bull_obs, "ob_bear": bear_obs}
    return ev
