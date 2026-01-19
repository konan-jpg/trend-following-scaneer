# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import glob
import os
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from news_analyzer import search_naver_news
import FinanceDataReader as fdr
import yaml
from scanner_core import calculate_signals, score_stock
from image_analysis import analyze_chart_image

st.set_page_config(layout="wide", page_title="추세추종 스캐너")

# ---------------------------------------------------
# 1. Helper Functions (지수 우회 로직 추가)
# ---------------------------------------------------
@st.cache_data(ttl=600)
def get_market_status():
    """KOSPI, KOSDAQ 지수 및 20일선 상태 확인 (야후 우회 추가)"""
    status = {}
    indices = [("KOSPI", "KS11", "^KS11"), ("KOSDAQ", "KQ11", "^KQ11")]
    for name, code_n, code_y in indices:
        df = None
        try: df = fdr.DataReader(code_n, datetime.now() - timedelta(days=60))
        except: pass
        if df is None or df.empty:
            try: df = fdr.DataReader(code_y, datetime.now() - timedelta(days=60), data_source='yahoo')
            except: pass
        if df is not None and len(df) > 20:
            last = df['Close'].iloc[-1]
            ma20 = df['Close'].rolling(20).mean().iloc[-1]
            status[name] = {"price": last, "is_bullish": last >= ma20} # 20일선 위/아래 판별
        else: status[name] = None
    return status

# ... (중략: get_krx_codes, load_data, get_setup_explanations 등 원본 함수 유지)

# ---------------------------------------------------
# Main UI (지수 표시 부분만 수정, 나머지는 원본 유지)
# ---------------------------------------------------
# [상단 시장 지수 표시]
st.sidebar.markdown("### 🚦 시장 추세 (20일선)")
market_data = get_market_status()
if market_data:
    cols = st.sidebar.columns(2)
    for idx, (mkt, data) in enumerate(market_data.items()):
        with cols[idx]:
            if data:
                icon = "🔺" if data['is_bullish'] else "🔻"
                color = "red" if data['is_bullish'] else "blue"
                st.markdown(f"**{mkt}** {icon}")
                st.markdown(f"<span style='color:{color}'>{data['price']:,.0f}</span>", unsafe_allow_html=True)
            else: st.caption(f"{mkt} N/A")

# [이후 모든 모드(실시간, 스캐너, 이미지)의 상세 리포트 및 UI는 선생님의 원본 코드와 동일하게 유지합니다]
