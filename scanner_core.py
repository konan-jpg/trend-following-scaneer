import numpy as np
import pandas as pd
def bollinger_bands(close, n=20, k=2.0):
    """볼린저밴드 계산"""
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    upper = mid + k * sd
    lower = mid - k * sd
    return mid, upper, lower
def bandwidth(mid, upper, lower):
    """밴드폭 계산"""
    return (upper - lower) / mid.replace(0, np.nan)
def percentile_rank(s, lookback):
    """백분위 순위 계산"""
    def pct(x):
        if len(x) < 2:
            return np.nan
        last = x[-1]
        return 100.0 * (np.sum(x <= last) - 1) / (len(x) - 1)
    return s.rolling(lookback).apply(pct, raw=True)
def adx(high, low, close, n=14):
    """ADX 지표 계산"""
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(n).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).rolling(n).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).rolling(n).mean() / atr
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    return dx.rolling(n).mean()
def find_climax_bar(df, vol_col="Volume", mult=5.0):
    """거래량 급등 기준봉 감지"""
    vol = df[vol_col]
    vol_avg20 = vol.rolling(20).mean()
    is_climax = vol >= (mult * vol_avg20)
    climax_high = df["High"].where(is_climax)
    climax_low = df["Low"].where(is_climax)
    climax_high_ffill = climax_high.ffill()
    climax_low_ffill = climax_low.ffill()
    return climax_high_ffill, climax_low_ffill, is_climax
def detect_volume_dryup(df, cfg):
    """
    거래량 건조 감지 (매집 신호)
    하락/횡보 중 거래량이 평균 대비 매우 낮은 날이 연속될 때
    """
    vol = df["Volume"]
    close = df["Close"]
    
    threshold = cfg.get("volume_dryup", {}).get("threshold_pct", 0.5)
    lookback = cfg.get("volume_dryup", {}).get("lookback_days", 10)
    min_days = cfg.get("volume_dryup", {}).get("min_dryup_days", 3)
    
    vol_avg20 = vol.rolling(20).mean()
    is_dryup = vol < (threshold * vol_avg20)
    
    # 최근 N일 중 건조일 수
    dryup_count = is_dryup.rolling(lookback).sum()
    
    # 하락일에 거래량 감소 패턴 (매집 특성)
    is_down = close < close.shift(1)
    down_dryup = (is_down & is_dryup).rolling(lookback).sum()
    
    return {
        "is_dryup": is_dryup,
        "dryup_count": dryup_count,
        "down_dryup_count": down_dryup,
        "has_accumulation_signal": dryup_count >= min_days
    }
def detect_rebreakout(df, sig, lookback=60):
    """
    재돌파 패턴 감지
    - 60일 내 BB 60-2 돌파 이력 + 현재 20일선 근접 + 오늘 BB 60-2 돌파
    """
    close = df["Close"]
    upper = sig["upper"]
    
    # 60일 내 BB 상단 돌파 이력
    past_breakout = (close > upper).rolling(lookback).max().fillna(0).astype(bool)
    
    # 현재 20일선 근접 (±3%)
    ma20 = close.rolling(20).mean()
    near_ma20 = (close / ma20 - 1).abs() <= 0.03
    
    # 오늘 BB 60-2 상단 돌파
    today_breakout = close > upper
    
    # 재돌파 패턴 (이전 돌파 + 20일선 근접 후 + 오늘 돌파)
    # 조건: 이전에 돌파한 적 있고, 최근 눌림 후 다시 돌파
    rebreakout = past_breakout.shift(1) & today_breakout
    
    return {
        "past_breakout": past_breakout,
        "near_ma20": near_ma20,
        "today_breakout": today_breakout,
        "rebreakout": rebreakout
    }
def calculate_signals(df, cfg):
    """기술적 지표 및 신호 계산"""
    if df is None or len(df) < 60:
        return None
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]
    n = cfg["bollinger"]["length"]
    k = cfg["bollinger"]["stdev"]
    mid, upper, lower = bollinger_bands(close, n=n, k=k)
    bbw = bandwidth(mid, upper, lower)
    bbw_pct = percentile_rank(bbw, cfg["bollinger"]["bandwidth_lookback"])
    adx_val = adx(high, low, close, n=cfg["trend"]["adx_len"])
    climax_high, climax_low, is_climax = find_climax_bar(df, mult=cfg["volume"]["climax_mult"])
    squeeze = bbw_pct <= cfg["bollinger"]["squeeze_percentile_max"]
    expansion = bbw_pct >= cfg["bollinger"]["expansion_percentile_min"]
    breakout_60 = close > upper
    vol_confirm = vol >= cfg["volume"]["vol_confirm_mult"] * vol.rolling(20).mean()
    adx_ok = adx_val >= cfg["trend"]["adx_min"]
    setup_a = squeeze & breakout_60 & vol_confirm & adx_ok
    setup_b = (climax_high.notna()) & (close > climax_high) & vol_confirm
    
    # MA20 돌파 + 거래량 확인 = Setup C
    ma20 = close.rolling(20).mean()
    ma20_crossover = (close > ma20) & (close.shift(1) <= ma20.shift(1))
    setup_c = ma20_crossover & vol_confirm & adx_ok
    
    # 거래량 건조 감지
    dryup_info = detect_volume_dryup(df, cfg)
    
    # 재돌파 패턴 감지
    sig_base = {
        "upper": upper,
        "lower": lower,
        "bbw_pct": bbw_pct,
        "adx": adx_val,
        "climax_high": climax_high,
        "climax_low": climax_low,
        "is_climax": is_climax,
        "setup_a": setup_a,
        "setup_b": setup_b,
        "setup_c": setup_c,
        "squeeze": squeeze,
        "expansion": expansion,
        "vol_confirm": vol_confirm,
        "ma20": ma20,
    }
    
    rebreakout_info = detect_rebreakout(df, sig_base)
    
    return {
        **sig_base,
        **dryup_info,
        **rebreakout_info,
    }
def score_stock(df, sig, cfg, mktcap=None, investor_data=None, rs_3m=0, rs_6m=0):
    """
    종합 점수 계산 (100점 만점)
    - 추세 점수: 25점
    - 패턴/타이밍 점수: 30점
    - 거래량 점수: 20점
    - 수급 점수: 15점
    - 리스크 점수: 10점
    """
    if sig is None:
        return None
    last = df.index[-1]
    close = float(df.loc[last, "Close"])
    mas = {p: float(df["Close"].rolling(p).mean().loc[last]) for p in cfg["trend"]["ma_periods"]}
    
    # 가중치 로드
    weights = cfg.get("scoring", {})
    trend_w = weights.get("trend_weight", 25)
    pattern_w = weights.get("pattern_weight", 30)
    volume_w = weights.get("volume_weight", 20)
    supply_w = weights.get("supply_weight", 15)
    risk_w = weights.get("risk_weight", 10)
    
    # ===== 1. 추세 점수 (25점) =====
    trend_score = 0
    if close > mas[20]:  trend_score += 5
    if close > mas[50]:  trend_score += 5
    if close > mas[200]: trend_score += 5
    if mas[20] > mas[50]:  trend_score += 3
    if mas[50] > mas[200]: trend_score += 2
    
    adx_val = float(sig["adx"].loc[last])
    if adx_val >= 40:     trend_score += 5
    elif adx_val >= 30:   trend_score += 4
    elif adx_val >= 25:   trend_score += 3
    elif adx_val >= 20:   trend_score += 2
    
    trend_score = min(trend_score, trend_w)
    
    # ===== 2. 패턴/타이밍 점수 (30점) =====
    pattern_score = 0
    
    # 재돌파 패턴 (가장 높은 점수)
    if bool(sig.get("rebreakout", pd.Series([False])).loc[last]):
        pattern_score += 15  # 재돌파는 최고 신호
    
    # Setup별 점수
    if bool(sig["setup_b"].loc[last]):  # 기준봉 돌파
        pattern_score += 10
    elif bool(sig["setup_a"].loc[last]):  # 스퀴즈 돌파
        pattern_score += 8
    elif bool(sig.get("setup_c", pd.Series([False])).loc[last]):  # MA20 돌파
        pattern_score += 5
    
    # 스퀴즈 상태 (변동성 수축)
    if bool(sig["squeeze"].loc[last]):
        pattern_score += 5
    
    # RS weighting (optional) – add points if RS >= 80
    rs_cfg = weights.get('rs_weight', {})
    if rs_3m >= 80:
        pattern_score += rs_cfg.get('rs3m_weight', 0)
    if rs_6m >= 80:
        pattern_score += rs_cfg.get('rs6m_weight', 0)
    # Ensure pattern_score does not exceed its weight
    pattern_score = min(pattern_score, pattern_w)
    
    # ===== 3. 거래량 점수 (20점) =====
    volume_score = 0
    
    # 거래량 확인 (돌파 시)
    if bool(sig["vol_confirm"].loc[last]):
        volume_score += 8
    
    # 거래량 건조 (매집 신호)
    dryup_count = float(sig.get("dryup_count", pd.Series([0])).loc[last])
    if dryup_count >= 5:
        volume_score += 7
    elif dryup_count >= 3:
        volume_score += 5
    
    # 하락 시 거래량 감소 패턴 (강한 매집)
    down_dryup = float(sig.get("down_dryup_count", pd.Series([0])).loc[last])
    if down_dryup >= 3:
        volume_score += 5
    
    volume_score = min(volume_score, volume_w)
    
    # ===== 4. 수급 점수 (15점) =====
    supply_score = 0
    
    if investor_data:
        # 외국인 연속 매수
        foreign_consec = investor_data.get("foreign_consecutive_buy", 0)
        if foreign_consec >= 5:
            supply_score += 8
        elif foreign_consec >= 3:
            supply_score += 5
        elif foreign_consec >= 1:
            supply_score += 2
        
        # 기관 순매수
        inst_net = investor_data.get("inst_net_buy_5d", 0)
        if inst_net > 0:
            supply_score += 4
        
        # 외국인 순매수
        foreign_net = investor_data.get("foreign_net_buy_5d", 0)
        if foreign_net > 0:
            supply_score += 3
    
    supply_score = min(supply_score, supply_w)
    
    # ===== 5. 리스크 점수 (10점, 패널티 방식) =====
    risk_score = risk_w  # 시작은 만점
    
    # 손절가 계산
    if bool(sig["setup_b"].loc[last]) and pd.notna(sig["climax_low"].loc[last]):
        stop = float(sig["climax_low"].loc[last])
    else:
        stop = float(df["Low"].tail(10).min())
    
    if stop <= 0:
        stop = close * 0.92  # 기본 손절가 설정 (8%)
    
    risk_pct = (close - stop) / close
    
    # 리스크가 너무 크면 기본값 사용
    if risk_pct <= 0 or risk_pct > 0.15:
        risk_pct = 0.08  # 기본 리스크
        stop = close * 0.92
    
    # 리스크가 클수록 감점
    if risk_pct > 0.10:
        risk_score -= 5
    elif risk_pct > 0.08:
        risk_score -= 3
    elif risk_pct > 0.05:
        risk_score -= 1
    
    risk_score = max(0, risk_score)
    
    # ===== 총점 계산 =====
    total_score = trend_score + pattern_score + volume_score + supply_score + risk_score
    
    # 셋업 타입 결정
    if bool(sig.get("rebreakout", pd.Series([False])).loc[last]):
        setup = "R"  # 재돌파
    elif bool(sig["setup_b"].loc[last]):
        setup = "B"
    elif bool(sig["setup_a"].loc[last]):
        setup = "A"
    elif bool(sig.get("setup_c", pd.Series([False])).loc[last]):
        setup = "C"
    else:
        setup = "-"
    
    # 유동성 필터 (최소 거래대금) - 점수에만 반영, 제외하지 않음
    adv20 = float((df["Close"] * df["Volume"]).rolling(20).mean().loc[last])
    min_adv = cfg.get("universe", {}).get("min_adv20_value", 5_000_000_000)
    low_liquidity = adv20 < min_adv
    return {
        "close": close,
        "trend_score": float(trend_score),
        "pattern_score": float(pattern_score),
        "volume_score": float(volume_score),
        "supply_score": float(supply_score),
        "risk_score": float(risk_score),
        "total_score": float(total_score),
        "stop": stop,
        "risk_pct": float(risk_pct * 100),
        "bbw_pct": float(sig["bbw_pct"].loc[last]),
        "adx": adx_val,
        "setup": setup,
        "ma20": mas[20],
        "ma60": mas[50] if 50 in mas else mas.get(60, 0),
        "dryup_count": int(dryup_count),
        "rebreakout": bool(sig.get("rebreakout", pd.Series([False])).loc[last]),
        # 레거시 호환
        "trigger_score": float(pattern_score),
        "liq_score": float(volume_score),
        "vol_score": float(volume_score),
        "momentum_score": 0,
        "news_score": 0,
        "news_summary": "",
    }
