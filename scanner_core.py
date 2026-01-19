# -*- coding: utf-8 -*-
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
    
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    vol_ma20 = vol.rolling(20).mean()
    
    # Door Knock: 현재가가 BB60 상단의 95%~102% 범위
    door_knock = (close >= upper * 0.95) & (close <= upper * 1.02)
    
    # Squeeze: 밴드폭이 최근 60일 하위 20%
    squeeze = bbw_pct <= 20
    
    # Memory: 60일 최대 거래량일 종가 계산
    memory_close = pd.Series(index=close.index, dtype=float)
    for i in range(60, len(close)):
        window_start = i - 60
        window_vol = vol.iloc[window_start:i]
        if len(window_vol) > 0:
            max_vol_day = window_vol.idxmax()
            memory_close.iloc[i] = close.loc[max_vol_day]
    
    # Memory Near: 60일 최대 거래량일 종가와 현재가 ±5% 이내
    memory_near = (close / memory_close - 1).abs() <= 0.05
    
    # 거래량 관련 신호
    vol_explosion = vol >= vol_ma20 * 3  # 과거 폭발
    vol_dryup = vol < vol_ma20 * 0.7  # 수축
    vol_dryup_count = vol_dryup.rolling(15).sum()
    
    return {
        "upper": upper,
        "lower": lower,
        "mid": mid,
        "bbw_pct": bbw_pct,
        "adx": adx_val,
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "vol_ma20": vol_ma20,
        "door_knock": door_knock,
        "squeeze": squeeze,
        "memory_close": memory_close,
        "memory_near": memory_near,
        "vol_explosion": vol_explosion,
        "vol_dryup_count": vol_dryup_count,
    }

def score_stock(df, sig, cfg, mktcap=None, investor_data=None, rs_3m=0, rs_6m=0):
    """
    종합 점수 계산 (100점 만점) - 통계적 표준안
    - 추세 점수: 25점
    - 위치 점수: 30점 (Door Knock + Squeeze + Memory + RS)
    - 거래량 점수: 20점 (폭발 + 수축 + 활성화)
    - 수급 점수: 15점
    - 리스크 점수: 10점
    """
    if sig is None:
        return None

    last = df.index[-1]
    close = float(df.loc[last, "Close"])
    vol = float(df.loc[last, "Volume"])
    
    # ===== 1. 추세 점수 (25점) =====
    trend_score = 0
    ma20 = float(sig["ma20"].loc[last]) if pd.notna(sig["ma20"].loc[last]) else close
    ma50 = float(sig["ma50"].loc[last]) if pd.notna(sig["ma50"].loc[last]) else close
    ma200 = float(sig["ma200"].loc[last]) if pd.notna(sig["ma200"].loc[last]) else close
    
    if close > ma20: trend_score += 5
    if close > ma50: trend_score += 5
    if close > ma200: trend_score += 5
    if ma20 > ma50: trend_score += 3
    if ma50 > ma200: trend_score += 2
    
    adx_val = float(sig["adx"].loc[last]) if pd.notna(sig["adx"].loc[last]) else 0
    if adx_val >= 40: trend_score += 5
    elif adx_val >= 30: trend_score += 4
    elif adx_val >= 25: trend_score += 3
    elif adx_val >= 20: trend_score += 2
    
    trend_score = min(trend_score, 25)
    
    # ===== 2. 위치 점수 (30점) - Door Knock + Squeeze + Memory + RS =====
    location_score = 0
    
    # A. Door Knock (10점): BB60 상단의 95%~102%
    door_knock_signal = bool(sig["door_knock"].loc[last]) if pd.notna(sig["door_knock"].loc[last]) else False
    if door_knock_signal:
        location_score += 10
    
    # B. Squeeze (10점): 밴드폭 하위 20%
    squeeze_signal = bool(sig["squeeze"].loc[last]) if pd.notna(sig["squeeze"].loc[last]) else False
    if squeeze_signal:
        location_score += 10
    
    # C. Memory (10점): 60일 최대 거래량일 종가 ±5%
    memory_signal = bool(sig["memory_near"].loc[last]) if pd.notna(sig["memory_near"].loc[last]) else False
    if memory_signal:
        location_score += 10
    
    # RS 가산점 (80점 이상이면 각각 +5점)
    if rs_3m >= 80:
        location_score += 5
    if rs_6m >= 80:
        location_score += 5
    
    location_score = min(location_score, 30)
    
    # ===== 3. 거래량 점수 (20점) - 3단계 구조 =====
    volume_score = 0
    vol_ma20 = float(sig["vol_ma20"].loc[last]) if pd.notna(sig["vol_ma20"].loc[last]) else 1
    vol_ratio = vol / vol_ma20 if vol_ma20 > 0 else 0
    
    # 1단계: 과거 폭발 (5점) - 60일 내 거래량 >= 3x
    vol_explosion_60 = sig["vol_explosion"].tail(60).any()
    if vol_explosion_60:
        volume_score += 5
    
    # 2단계: 수축 (7점) - 최근 15일 중 건조일 >= 3일
    dryup_count = float(sig["vol_dryup_count"].loc[last]) if pd.notna(sig["vol_dryup_count"].loc[last]) else 0
    if dryup_count >= 5:
        volume_score += 7
    elif dryup_count >= 3:
        volume_score += 5
    
    # 3단계: 현재 활성화 (8점)
    if 1.2 <= vol_ratio < 2.0:
        volume_score += 5
    elif 2.0 <= vol_ratio < 3.0:
        volume_score += 8
    elif vol_ratio >= 3.0:
        volume_score += 3  # 과열은 감점 개념
    
    volume_score = min(volume_score, 20)
    
    # ===== 4. 수급 점수 (15점) =====
    supply_score = 0
    if investor_data:
        foreign_consec = investor_data.get("foreign_consecutive_buy", 0)
        if foreign_consec >= 5: supply_score += 8
        elif foreign_consec >= 3: supply_score += 5
        elif foreign_consec >= 1: supply_score += 2
        
        if investor_data.get("inst_net_buy_5d", 0) > 0: supply_score += 4
        if investor_data.get("foreign_net_buy_5d", 0) > 0: supply_score += 3
    
    supply_score = min(supply_score, 15)
    
    # ===== 5. 리스크 점수 (10점) =====
    risk_score = 10
    
    # 손절가 계산: 최근 10일 저점
    stop = float(df["Low"].tail(10).min())
    if stop <= 0:
        stop = close * 0.92
    
    risk_pct = (close - stop) / close
    if risk_pct <= 0 or risk_pct > 0.15:
        risk_pct = 0.08
        stop = close * 0.92
    
    if risk_pct > 0.10: risk_score -= 5
    elif risk_pct > 0.08: risk_score -= 3
    elif risk_pct > 0.05: risk_score -= 1
    
    risk_score = max(0, risk_score)
    
    # ===== 총점 계산 =====
    total_score = trend_score + location_score + volume_score + supply_score + risk_score
    
    # 셋업 타입 결정
    setup = "-"
    conditions_met = sum([door_knock_signal, squeeze_signal, memory_signal])
    if conditions_met >= 3:
        setup = "R"  # 3가지 조건 모두 충족 (최강)
    elif conditions_met >= 2:
        setup = "A"  # 2가지 조건
    elif conditions_met >= 1:
        setup = "B"  # 1가지 조건
    
    return {
        "close": close,
        "trend_score": float(trend_score),
        "pattern_score": float(location_score),
        "volume_score": float(volume_score),
        "supply_score": float(supply_score),
        "risk_score": float(risk_score),
        "total_score": float(total_score),
        "stop": stop,
        "risk_pct": float(risk_pct * 100),
        "bbw_pct": float(sig["bbw_pct"].loc[last]) if pd.notna(sig["bbw_pct"].loc[last]) else 0,
        "adx": adx_val,
        "setup": setup,
        "ma20": ma20,
        "ma60": ma50,
        "bb_upper": float(sig["upper"].loc[last]) if pd.notna(sig["upper"].loc[last]) else close,
        "door_knock": door_knock_signal,
        "squeeze": squeeze_signal,
        "memory_near": memory_signal,
        # 레거시 호환
        "trigger_score": float(location_score),
        "liq_score": float(volume_score),
    }
