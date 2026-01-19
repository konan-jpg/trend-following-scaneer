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

@st.cache_data(ttl=300)
def load_config():
    cfg_path = "config.yaml"
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

@st.cache_data(ttl=300)
def load_data():
    df = None
    filename = None
    merged_files = glob.glob("data/scanner_output*.csv")
    merged_files = [f for f in merged_files if "chunk" not in f]
    if merged_files:
        def extract_date(fn):
            try:
                parts = os.path.basename(fn).replace('.csv', '').split('_')
                if len(parts) >= 3: return parts[-1]
                return '0000-00-00'
            except: return '0000-00-00'
        latest_file = max(merged_files, key=extract_date)
        df = pd.read_csv(latest_file, dtype={'code': str})
        filename = os.path.basename(latest_file)
    else:
        chunk_files = glob.glob("data/partial/scanner_output*chunk*.csv")
        if chunk_files:
            df_list = []
            for f in sorted(chunk_files):
                try:
                    sub_df = pd.read_csv(f, dtype={'code': str})
                    df_list.append(sub_df)
                except: continue
            if df_list:
                df = pd.concat(df_list, ignore_index=True)
                if 'code' in df.columns:
                    df.drop_duplicates(subset=['code'], keep='first', inplace=True)
                filename = f"Merged from {len(df_list)} chunks"
    sector_df = None
    if os.path.exists("data/sector_rankings.csv"):
        sector_df = pd.read_csv("data/sector_rankings.csv")
    return df, sector_df, filename

@st.cache_data
def get_krx_codes():
    try:
        df = fdr.StockListing("KRX")
        if df is None or df.empty: raise ValueError("Empty")
        return df[['Code', 'Name']]
    except:
        try:
            if os.path.exists("data/krx_tickers.csv"):
                return pd.read_csv("data/krx_tickers.csv", dtype={'Code': str})[['Code', 'Name']]
        except: pass
        df_scan, _, _ = load_data()
        if df_scan is not None and not df_scan.empty:
            return df_scan[['code', 'name']].rename(columns={'code': 'Code', 'name': 'Name'}).drop_duplicates()
        return pd.DataFrame({'Code':[], 'Name':[]})

def get_setup_explanations():
    return {
        'R': "🔥 3조건 충족 - Door Knock + Squeeze + Memory (가장 강력)",
        'A': "2조건 충족 - Door Knock/Squeeze/Memory 중 2개",
        'B': "1조건 충족 - Door Knock/Squeeze/Memory 중 1개",
        '-': "기본 추세 및 유동성 기준만 충족",
    }

def get_score_explanations():
    return {
        'trend_score': {'name': '추세 점수 (25점)', 'description': '이동평균선 정렬과 ADX 추세 강도', 'components': ['현재가 > 20일선: +5점', '현재가 > 50일선: +5점', '현재가 > 200일선: +5점', 'MA 정렬: +5점', 'ADX 강도: +2~5점']},
        'pattern_score': {'name': '위치 점수 (30점)', 'description': 'Door Knock + Squeeze + Memory + RS', 'components': ['Door Knock (BB상단 95~102%): +10점', 'Squeeze (밴드폭 하위20%): +10점', 'Memory (60일 최대거래량일 종가±5%): +10점', 'RS 80점이상: 각 +5점']},
        'volume_score': {'name': '거래량 점수 (20점)', 'description': '3단계 거래량 분석', 'components': ['과거 폭발 (3배이상): +5점', '수축 (건조일 3일+): +5~7점', '현재 활성화: +3~8점']},
        'supply_score': {'name': '수급 점수 (15점)', 'description': '외국인/기관 연속 매수', 'components': ['외국인 연속 매수 5일+: +8점', '외국인 연속 매수 3일+: +5점', '기관 5일 순매수: +4점', '외국인 5일 순매수: +3점']},
        'risk_score': {'name': '리스크 점수 (10점)', 'description': '손절가 거리 기반', 'components': ['리스크 5% 이하: 10점', '리스크 5~8%: -1점', '리스크 8~10%: -3점', '리스크 10%+: -5점']}
    }

def display_stock_report(row, sector_df=None, rs_3m=None, rs_6m=None):
    st.markdown("---")
    st.subheader(f"📊 {row.get('name', 'N/A')} ({row.get('code', '')}) 상세 분석")
    if rs_3m is not None: st.metric("3개월 RS", f"{rs_3m}")
    if rs_6m is not None: st.metric("6개월 RS", f"{rs_6m}")
    stock_sector = row.get('sector', '기타')
    is_leader = sector_df is not None and stock_sector in sector_df.head(5)['Sector'].tolist()
    if is_leader: st.success(f"🏆 **주도 섹터**: {stock_sector}")
    else: st.info(f"📌 **업종**: {stock_sector}")
    foreign = row.get('foreign_consec_buy', 0)
    inst_net = row.get('inst_net_5d', 0)
    risk_pct = row.get('risk_pct', 0)
    st.markdown(f"""
    <style>.info-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-bottom:10px}}.info-box{{background:#f0f2f6;padding:8px;border-radius:5px;text-align:center}}.info-label{{font-size:11px;color:#666}}.info-value{{font-size:14px;font-weight:bold}}</style>
    <div class="info-grid">
        <div class="info-box"><div class="info-label">현재가</div><div class="info-value">{row['close']:,.0f}원</div></div>
        <div class="info-box"><div class="info-label">총점</div><div class="info-value">{row['total_score']:.0f}점</div></div>
        <div class="info-box"><div class="info-label">셋업</div><div class="info-value">{row.get('setup', '-')}</div></div>
        <div class="info-box"><div class="info-label">리스크</div><div class="info-value">{risk_pct:.1f}%</div></div>
        <div class="info-box"><div class="info-label">외인연속</div><div class="info-value">{int(foreign)}일</div></div>
        <div class="info-box"><div class="info-label">기관5일</div><div class="info-value">{inst_net/1e8:,.0f}억</div></div>
    </div>""", unsafe_allow_html=True)
    setup_type = row.get('setup', '-')
    with st.expander(f"ℹ️ 셋업 설명 (현재: {setup_type})", expanded=False):
        for s, d in get_setup_explanations().items():
            if s == setup_type: st.success(f"**▶ {s}** (현재): {d}")
            else: st.write(f"**{s}**: {d}")
    st.markdown("---")
    st.markdown("#### 📈 점수 구성 (100점 만점)")
    rs3_bonus = 5 if rs_3m and rs_3m >= 80 else 0
    rs6_bonus = 5 if rs_6m and rs_6m >= 80 else 0
    score_data = {'추세': row.get('trend_score', 0), '위치': row.get('pattern_score', 0), '거래량': row.get('volume_score', 0), '수급': row.get('supply_score', 0), '리스크': row.get('risk_score', 10)}
    cols = st.columns(6)
    with cols[0]: st.metric("추세", f"{score_data['추세']:.0f}/25")
    with cols[1]: st.metric("위치", f"{score_data['위치']:.0f}/30")
    with cols[2]: st.metric("거래량", f"{score_data['거래량']:.0f}/20")
    with cols[3]: st.metric("수급", f"{score_data['수급']:.0f}/15")
    with cols[4]: st.metric("리스크", f"{score_data['리스크']:.0f}/10")
    with cols[5]: st.metric("RS가산", f"+{rs3_bonus+rs6_bonus}")
    for key, info in get_score_explanations().items():
        with st.expander(f"🔹 {info['name']}", expanded=False):
            st.markdown(f"**{info['description']}**")
            for c in info['components']: st.write(f"• {c}")
    if 'foreign_net_5d' in row or 'inst_net_5d' in row:
        st.markdown("---")
        st.markdown("#### 💰 수급 현황")
        c1, c2, c3 = st.columns(3)
        with c1: st.write(f"**외국인 연속**: {int(row.get('foreign_consec_buy', 0))}일")
        with c2: st.write(f"**외국인 5일**: {row.get('foreign_net_5d', 0)/1e8:,.1f}억")
        with c3: st.write(f"**기관 5일**: {row.get('inst_net_5d', 0)/1e8:,.1f}억")
    st.markdown("---")
    st.markdown("#### 🎯 매수 전략")
    try:
        current_price, ma20 = row['close'], row.get('ma20', row['close'])
        base_stop = row.get('stop', current_price * 0.92)
        bb_upper = row.get('bb_upper', current_price * 1.05)
        c1, c2 = st.columns(2)
        with c1:
            pullback_stop = max(ma20 * 0.97, base_stop)
            st.markdown(f'<div style="background:rgba(0,255,0,0.1);padding:10px;border-radius:10px;"><strong>📉 눌림목</strong><br>진입: {ma20:,.0f}원<br>손절: {pullback_stop:,.0f}원</div>', unsafe_allow_html=True)
        with c2:
            breakout_price = bb_upper if bb_upper > current_price else current_price * 1.02
            st.markdown(f'<div style="background:rgba(255,165,0,0.1);padding:10px;border-radius:10px;"><strong>🚀 돌파</strong><br>진입: {breakout_price:,.0f}원<br>손절: {breakout_price*0.95:,.0f}원</div>', unsafe_allow_html=True)
        st.caption(f"⚠️ 기본 손절가: {base_stop:,.0f}원")
    except Exception as e: st.warning(f"전략 계산 오류: {e}")
    st.markdown("---")
    st.markdown("#### 📊 기술적 지표")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if 'ma20' in row and pd.notna(row['ma20']): st.write(f"**20일선**: {row['ma20']:,.0f}원")
    with c2:
        if 'ma60' in row and pd.notna(row['ma60']): st.write(f"**60일선**: {row['ma60']:,.0f}원")
    with c3:
        if 'adx' in row and pd.notna(row['adx']): st.write(f"**ADX**: {row['adx']:.1f}")
    with c4:
        if 'stop' in row and pd.notna(row['stop']): st.write(f"**손절가**: {row['stop']:,.0f}원")
    st.markdown("---")
    st.markdown("#### 📉 차트 (6개월)")
    try:
        chart_df = fdr.DataReader(row['code'], datetime.now() - timedelta(days=180), datetime.now())
        if chart_df is not None and len(chart_df) > 0:
            chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
            chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
            mid = chart_df['Close'].rolling(60).mean()
            std = chart_df['Close'].rolling(60).std()
            chart_df['BB_Upper'] = mid + 2 * std
            fig = make_subplots(rows=2, cols=1, row_heights=[0.75, 0.25], vertical_spacing=0.03, shared_xaxes=True)
            fig.add_trace(go.Candlestick(x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'], name='가격', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA20'], mode='lines', name='MA20', line=dict(color='orange', width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA60'], mode='lines', name='MA60', line=dict(color='purple', width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['BB_Upper'], mode='lines', name='BB상단', line=dict(color='gray', width=1, dash='dot')), row=1, col=1)
            if 'stop' in row and pd.notna(row['stop']):
                fig.add_trace(go.Scatter(x=[chart_df.index[0], chart_df.index[-1]], y=[row['stop'], row['stop']], mode='lines', name='손절', line=dict(color='red', width=1.5, dash='dash')), row=1, col=1)
            colors = ['red' if o <= c else 'blue' for o, c in zip(chart_df['Open'], chart_df['Close'])]
            fig.add_trace(go.Bar(x=chart_df.index, y=chart_df['Volume'], name='거래량', marker_color=colors, opacity=0.5), row=2, col=1)
            fig.update_layout(legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0), xaxis_rangeslider_visible=False, height=500, margin=dict(l=50, r=50, t=50, b=30))
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e: st.warning(f"차트 오류: {e}")

# Main UI
st.sidebar.title("메뉴")
mode = st.sidebar.radio("모드 선택", ["🔍 실시간 종목 진단", "📊 당일 시장 스캐너", "🖼️ 차트 이미지 분석"])
if st.sidebar.button("🔄 새로고침"):
    st.cache_data.clear()
    st.rerun()

if mode == "📊 당일 시장 스캐너":
    min_score = st.slider("최소 점수", 0, 100, 50)
    df, sector_df, filename = load_data()
    if df is None: st.error("❌ 데이터 없음"); st.stop()
    df['code'] = df['code'].astype(str).str.zfill(6)
    st.success(f"✅ {filename} ({len(df)}개)")
    st.markdown("### 🧭 섹터 분석")
    c1, c2 = st.columns(2)
    with c1:
        st.info("📊 주도 섹터")
        if sector_df is not None:
            top = sector_df[sector_df['Sector'] != '기타'].head(5)[['Sector', 'AvgReturn_3M', 'StockCount']]
            st.dataframe(top.style.format({'AvgReturn_3M': '{:.1f}%'}), use_container_width=True, hide_index=True)
    with c2:
        st.success("🎯 포착 섹터")
        if 'sector' in df.columns:
            ss = df[df['sector'] != '기타']['sector'].value_counts().head(5).reset_index()
            ss.columns = ['Sector', 'Count']
            st.dataframe(ss, use_container_width=True, hide_index=True)
    st.markdown("---")
    if 'total_score' in df.columns: df = df.sort_values('total_score', ascending=False).reset_index(drop=True)
    filtered = df[df['total_score'] >= min_score].copy()
    st.subheader(f"🏆 상위 종목 ({len(filtered)}개)")
    with st.popover("ℹ️ 점수 설명"):
        st.markdown("**추세(25)** + **위치(30)** + **거래량(20)** + **수급(15)** + **리스크(10)** = 100점")
    cols = ['name', 'sector', 'close', 'total_score', 'setup', 'trend_score', 'pattern_score', 'volume_score', 'supply_score']
    cols = [c for c in cols if c in filtered.columns]
    disp = filtered[cols].copy()
    disp.insert(0, '순위', range(1, len(disp)+1))
    disp = disp.rename(columns={'name':'종목명','sector':'업종','close':'현재가','total_score':'총점','setup':'셋업','trend_score':'추세','pattern_score':'위치','volume_score':'거래량','supply_score':'수급'})
    event = st.dataframe(disp, use_container_width=True, height=400, hide_index=True, on_select="rerun", selection_mode="single-row")
    if event.selection and len(event.selection.rows) > 0:
        code = filtered.iloc[event.selection.rows[0]]['code']
        display_stock_report(df[df['code'] == code].iloc[0], sector_df)

elif mode == "🔍 실시간 종목 진단":
    st.subheader("🔍 실시간 종목 진단")
    stock_df = get_krx_codes()
    name = st.selectbox("종목명", stock_df['Name'])
    code = stock_df[stock_df['Name'] == name]['Code'].iloc[0]
    rs_3m = st.number_input("3개월 RS", 0, 100, 0, 1)
    rs_6m = st.number_input("6개월 RS", 0, 100, 0, 1)
    inv = {}
    df_scan, sector_df, _ = load_data()
    if df_scan is not None:
        df_scan['code'] = df_scan['code'].astype(str).str.zfill(6)
        r = df_scan[df_scan['code'] == str(code).zfill(6)]
        if not r.empty:
            r = r.iloc[0]
            inv = {'foreign_consecutive_buy': r.get('foreign_consec_buy', 0), 'inst_net_buy_5d': r.get('inst_net_5d', 0), 'foreign_net_buy_5d': r.get('foreign_net_5d', 0)}
    df_stock = fdr.DataReader(code, datetime.now() - timedelta(days=365), datetime.now())
    if df_stock is not None and len(df_stock) > 0:
        cfg = load_config()
        sig = calculate_signals(df_stock, cfg)
        result = score_stock(df_stock, sig, cfg, rs_3m=rs_3m, rs_6m=rs_6m, investor_data=inv if inv else None)
        if result:
            row = pd.Series(result)
            row['name'], row['code'], row['sector'] = name, code, ''
            if inv:
                row['foreign_consec_buy'] = inv.get('foreign_consecutive_buy', 0)
                row['foreign_net_5d'] = inv.get('foreign_net_buy_5d', 0)
                row['inst_net_5d'] = inv.get('inst_net_buy_5d', 0)
            display_stock_report(row, sector_df, rs_3m, rs_6m)
        else: st.error("점수 계산 실패")
    else: st.error("데이터 없음")

elif mode == "🖼️ 차트 이미지 분석":
    st.subheader("🖼️ 차트 이미지 분석")
    uploaded = st.file_uploader("차트 업로드", type=["png","jpg","jpeg"])
    if uploaded:
        st.image(uploaded, caption="업로드된 차트", use_column_width=True)
        from PIL import Image
        result = analyze_chart_image(Image.open(uploaded))
        if result:
            with st.expander("🔍 분석 결과", expanded=True):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**OCR**")
                    for l in result.get("ocr_text", []): st.caption(f"- {l}")
                with c2:
                    st.markdown("**패턴**")
                    for p in result.get("patterns", []): st.success(f"{p['name']} ({p['confidence']*100:.0f}%)")
        stock_df = get_krx_codes()
        name = st.selectbox("종목명", stock_df['Name'], key='img_name')
        code = stock_df[stock_df['Name'] == name]['Code'].iloc[0]
        rs_3m = st.number_input("3개월 RS", 0, 100, 0, 1, key='img_rs3')
        rs_6m = st.number_input("6개월 RS", 0, 100, 0, 1, key='img_rs6')
        inv = {}
        df_scan, _, _ = load_data()
        if df_scan is not None:
            r = df_scan[df_scan['code'].astype(str).str.zfill(6) == str(code).zfill(6)]
            if not r.empty:
                r = r.iloc[0]
                inv = {'foreign_consecutive_buy': r.get('foreign_consec_buy', 0), 'inst_net_buy_5d': r.get('inst_net_5d', 0), 'foreign_net_buy_5d': r.get('foreign_net_5d', 0)}
        df_stock = fdr.DataReader(code, datetime.now() - timedelta(days=365), datetime.now())
        if df_stock is not None and len(df_stock) > 0:
            cfg = load_config()
            sig = calculate_signals(df_stock, cfg)
            result = score_stock(df_stock, sig, cfg, rs_3m=rs_3m, rs_6m=rs_6m, investor_data=inv)
            if result:
                row = pd.Series(result)
                row['name'], row['code'], row['sector'] = name, code, ''
                if inv:
                    row['foreign_consec_buy'] = inv.get('foreign_consecutive_buy', 0)
                    row['foreign_net_5d'] = inv.get('foreign_net_buy_5d', 0)
                    row['inst_net_5d'] = inv.get('inst_net_buy_5d', 0)
                display_stock_report(row, None, rs_3m, rs_6m)
            else: st.error("점수 계산 실패")
        else: st.error("데이터 없음")
