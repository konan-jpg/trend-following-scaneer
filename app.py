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
    df, filename = None, None
    merged_files = [f for f in glob.glob("data/scanner_output*.csv") if "chunk" not in f]
    if merged_files:
        def extract_date(fn):
            try: return os.path.basename(fn).replace('.csv', '').split('_')[-1]
            except: return '0000-00-00'
        latest_file = max(merged_files, key=extract_date)
        df = pd.read_csv(latest_file, dtype={'code': str})
        filename = os.path.basename(latest_file)
    else:
        chunk_files = glob.glob("data/partial/scanner_output*chunk*.csv")
        if chunk_files:
            df_list = [pd.read_csv(f, dtype={'code': str}) for f in sorted(chunk_files) if os.path.exists(f)]
            if df_list:
                df = pd.concat(df_list, ignore_index=True).drop_duplicates(subset=['code'], keep='first')
                filename = f"Merged {len(df_list)} chunks"
    sector_df = pd.read_csv("data/sector_rankings.csv") if os.path.exists("data/sector_rankings.csv") else None
    return df, sector_df, filename

@st.cache_data
def get_krx_codes():
    try:
        df = fdr.StockListing("KRX")
        if df is not None and not df.empty: return df[['Code', 'Name']]
    except: pass
    if os.path.exists("data/krx_tickers.csv"):
        return pd.read_csv("data/krx_tickers.csv", dtype={'Code': str})[['Code', 'Name']]
    df_scan, _, _ = load_data()
    if df_scan is not None:
        return df_scan[['code', 'name']].rename(columns={'code': 'Code', 'name': 'Name'}).drop_duplicates()
    return pd.DataFrame({'Code':[], 'Name':[]})

def get_setup_explanations():
    return {'R': "🔥 재돌파 - Door Knock+Squeeze", 'B': "거래량 급등 후 고점 돌파", 'A': "스퀴즈 돌파+ADX", 'C': "MA20 돌파", '-': "기준만 충족"}

def get_score_explanations():
    return {
        'trend_score': {'name': '추세 (25점)', 'description': 'MA정렬+ADX', 'components': ['현재가>20일선: +5', '현재가>50일선: +5', '현재가>200일선: +5', 'MA정렬: +5', 'ADX강도: +2~5']},
        'pattern_score': {'name': '위치 (30점)', 'description': 'Door Knock+Squeeze+RS', 'components': ['Door Knock: +10', 'Squeeze: +10', 'Setup가산: +3~5', 'RS80+: 각+5']},
        'volume_score': {'name': '거래량 (20점)', 'description': '폭발+수축+확인', 'components': ['과거폭발: +5', '수축: +5~7', '거래량확인: +5']},
        'supply_score': {'name': '수급 (15점)', 'description': '외국인/기관', 'components': ['외인연속5일+: +8', '외인연속3일+: +5', '기관순매수: +4', '외인순매수: +3']},
        'risk_score': {'name': '리스크 (10점)', 'description': '손절가거리', 'components': ['5%이하: 10점', '5~8%: -1', '8~10%: -3', '10%+: -5']}
    }

def display_stock_report(row, sector_df=None, rs_3m=None, rs_6m=None):
    st.markdown("---")
    st.subheader(f"📊 {row.get('name', 'N/A')} ({row.get('code', '')}) 상세 분석")
    if rs_3m: st.metric("3개월 RS", f"{rs_3m}")
    if rs_6m: st.metric("6개월 RS", f"{rs_6m}")
    stock_sector = row.get('sector', '기타')
    if sector_df is not None and stock_sector in sector_df.head(5)['Sector'].tolist():
        st.success(f"🏆 **주도 섹터**: {stock_sector}")
    else:
        st.info(f"📌 **업종**: {stock_sector}")
    foreign, inst_net, risk_pct = row.get('foreign_consec_buy', 0), row.get('inst_net_5d', 0), row.get('risk_pct', 0)
    st.markdown(f"""<style>.info-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:5px}}.info-box{{background:#f0f2f6;padding:8px;border-radius:5px;text-align:center}}.info-label{{font-size:11px;color:#666}}.info-value{{font-size:14px;font-weight:bold}}</style>
    <div class="info-grid"><div class="info-box"><div class="info-label">현재가</div><div class="info-value">{row['close']:,.0f}원</div></div>
    <div class="info-box"><div class="info-label">총점</div><div class="info-value">{row['total_score']:.0f}점</div></div>
    <div class="info-box"><div class="info-label">셋업</div><div class="info-value">{row.get('setup','-')}</div></div>
    <div class="info-box"><div class="info-label">리스크</div><div class="info-value">{risk_pct:.1f}%</div></div>
    <div class="info-box"><div class="info-label">외인연속</div><div class="info-value">{int(foreign)}일</div></div>
    <div class="info-box"><div class="info-label">기관5일</div><div class="info-value">{inst_net/1e8:,.0f}억</div></div></div>""", unsafe_allow_html=True)
    with st.expander(f"ℹ️ 셋업 설명 ({row.get('setup','-')})", expanded=False):
        for s, d in get_setup_explanations().items():
            st.success(f"**▶ {s}**: {d}") if s == row.get('setup') else st.write(f"**{s}**: {d}")
    st.markdown("---")
    st.markdown("#### 📈 점수 구성 (100점)")
    rs_bonus = (5 if rs_3m and rs_3m >= 80 else 0) + (5 if rs_6m and rs_6m >= 80 else 0)
    cols = st.columns(6)
    cols[0].metric("추세", f"{row.get('trend_score',0):.0f}/25")
    cols[1].metric("위치", f"{row.get('pattern_score',0):.0f}/30")
    cols[2].metric("거래량", f"{row.get('volume_score',0):.0f}/20")
    cols[3].metric("수급", f"{row.get('supply_score',0):.0f}/15")
    cols[4].metric("리스크", f"{row.get('risk_score',10):.0f}/10")
    cols[5].metric("RS가산", f"+{rs_bonus}")
    for k, v in get_score_explanations().items():
        with st.expander(f"🔹 {v['name']}", expanded=False):
            st.markdown(f"**{v['description']}**")
            for c in v['components']: st.write(f"• {c}")
    if 'foreign_net_5d' in row or 'inst_net_5d' in row:
        st.markdown("---")
        st.markdown("#### 💰 수급 현황")
        c1, c2, c3 = st.columns(3)
        c1.write(f"**외인 연속**: {int(row.get('foreign_consec_buy',0))}일")
        c2.write(f"**외인 5일**: {row.get('foreign_net_5d',0)/1e8:,.1f}억")
        c3.write(f"**기관 5일**: {row.get('inst_net_5d',0)/1e8:,.1f}억")
    # 매수 전략
    st.markdown("---")
    st.markdown("#### 🎯 매수 전략 추천")
    try:
        cp, ma20, base_stop = row['close'], row.get('ma20', row['close']), row.get('stop', row['close']*0.92)
        bb_upper = row.get('bb_upper', cp*1.05)
        pullback_price, pullback_stop = ma20, max(ma20*0.97, base_stop)
        breakout_price = bb_upper if bb_upper > cp else cp*1.02
        breakout_stop = breakout_price * 0.95
        # O'Neil 패턴 감지
        oneil_price, oneil_stop, oneil_setup, oneil_msg = 0, 0, "-", "패턴 대기중"
        try:
            sub_df = fdr.DataReader(row['code'], datetime.now()-timedelta(days=60), datetime.now())
            if sub_df is not None and len(sub_df) >= 2:
                today, prev = sub_df.iloc[-1], sub_df.iloc[-2]
                ma20_c = sub_df['Close'].rolling(20).mean().iloc[-1]
                vol_ma = sub_df['Volume'].rolling(20).mean().iloc[-1]
                if today['High'] < prev['High'] and today['Low'] > prev['Low']:
                    oneil_price, oneil_setup, oneil_msg = today['High'], "Inside Day", f"고가({int(today['High']):,}) 돌파시"
                elif today['Open'] < prev['Low'] and today['Close'] > prev['Low'] and today['Close'] > ma20_c:
                    oneil_price, oneil_setup, oneil_msg = today['Close'], "Oops Reversal", "반전 확인"
                elif today['Volume'] > vol_ma*2.5 and today['Close'] > prev['Close']*1.04:
                    oneil_price, oneil_setup, oneil_msg = today['Close'], "Pocket Pivot", "거래량 급등"
                if oneil_price > 0: oneil_stop = oneil_price * 0.93
        except: pass
        # 순위 매기기
        strats = [
            ("💎 오닐/미너비니", 100 if oneil_price > 0 else 30, oneil_msg if oneil_price > 0 else "패턴 대기중"),
            ("📉 눌림목", 95 if -2 <= (cp-ma20)/ma20*100 <= 4 else 50, "MA20 지지선"),
            ("🚀 추세 돌파", 90 if cp >= bb_upper*0.98 else 55, "BB상단 접근")
        ]
        strats.sort(key=lambda x: x[1], reverse=True)
        st.markdown("**🎯 우선순위**")
        for i, (nm, sc, rs) in enumerate(strats, 1):
            if i == 1: st.success(f"🥇 **{i}순위**: {nm} - {rs}")
            elif i == 2: st.info(f"🥈 **{i}순위**: {nm} - {rs}")
            else: st.warning(f"🥉 **{i}순위**: {nm} - {rs}")
        c1, c2, c3 = st.columns(3)
        c1.markdown(f'<div style="background:rgba(0,255,0,0.1);padding:10px;border-radius:10px"><strong>📉 눌림목</strong><br>진입: <b>{pullback_price:,.0f}원</b><br>손절: {pullback_stop:,.0f}원<br><small>리스크: {(pullback_price-pullback_stop)/pullback_price*100:.1f}%</small></div>', unsafe_allow_html=True)
        c2.markdown(f'<div style="background:rgba(255,165,0,0.1);padding:10px;border-radius:10px"><strong>🚀 추세돌파</strong><br>진입: <b>{breakout_price:,.0f}원</b><br>손절: {breakout_stop:,.0f}원<br><small>리스크: {(breakout_price-breakout_stop)/breakout_price*100:.1f}%</small></div>', unsafe_allow_html=True)
        bg = "rgba(138,43,226,0.1)" if oneil_price > 0 else "rgba(128,128,128,0.1)"
        cnt = f'진입: <b>{oneil_price:,.0f}원</b><br>손절: {oneil_stop:,.0f}원<br><small>리스크: {(oneil_price-oneil_stop)/oneil_price*100:.1f}%</small>' if oneil_price > 0 else f'<span style="color:gray">{oneil_msg}</span>'
        c3.markdown(f'<div style="background:{bg};padding:10px;border-radius:10px"><strong>💎 오닐/미너비니</strong><br><small>({oneil_setup})</small><br>{cnt}</div>', unsafe_allow_html=True)
        st.caption(f"⚠️ 기본 손절가: {base_stop:,.0f}원")
    except Exception as e: st.warning(f"전략 오류: {e}")
    # 기술적 지표
    st.markdown("---")
    st.markdown("#### 📊 기술적 지표")
    c1, c2, c3, c4 = st.columns(4)
    if 'ma20' in row and pd.notna(row['ma20']): c1.write(f"**20일선**: {row['ma20']:,.0f}원")
    if 'ma60' in row and pd.notna(row['ma60']): c2.write(f"**60일선**: {row['ma60']:,.0f}원")
    if 'adx' in row and pd.notna(row['adx']): c3.write(f"**ADX**: {row['adx']:.1f}")
    if 'stop' in row and pd.notna(row['stop']): c4.write(f"**손절최종가격**: {row['stop']:,.0f}원")
    # 차트
    st.markdown("---")
    st.markdown("#### 📉 가격 차트 (6개월)")
    try:
        chart_df = fdr.DataReader(row['code'], datetime.now()-timedelta(days=180), datetime.now())
        if chart_df is not None and len(chart_df) > 0:
            chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
            chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
            mid = chart_df['Close'].rolling(60).mean()
            std = chart_df['Close'].rolling(60).std()
            chart_df['BB_Upper'] = mid + 2*std
            fig = make_subplots(rows=2, cols=1, row_heights=[0.75,0.25], vertical_spacing=0.03, shared_xaxes=True)
            fig.add_trace(go.Candlestick(x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'], name=f'가격 {row["close"]:,.0f}', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA20'], mode='lines', name=f'MA20 ({chart_df["MA20"].iloc[-1]:,.0f})', line=dict(color='orange', width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA60'], mode='lines', name=f'MA60 ({chart_df["MA60"].iloc[-1]:,.0f})', line=dict(color='purple', width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['BB_Upper'], mode='lines', name=f'BB상단 ({chart_df["BB_Upper"].iloc[-1]:,.0f})', line=dict(color='gray', width=1, dash='dot')), row=1, col=1)
            if 'stop' in row and pd.notna(row['stop']):
                fig.add_trace(go.Scatter(x=[chart_df.index[0], chart_df.index[-1]], y=[row['stop'], row['stop']], mode='lines', name=f'손절 {row["stop"]:,.0f}', line=dict(color='red', width=1.5, dash='dash')), row=1, col=1)
            # 장대양봉+대량거래 마커
            vol_ma20 = chart_df['Volume'].rolling(20).mean()
            markers = []
            for i in range(1, len(chart_df)):
                c, p = chart_df.iloc[i], chart_df.iloc[i-1]
                body = abs(c['Close']-c['Open'])
                rng = c['High']-c['Low']
                if c['Close'] > c['Open'] and body > rng*0.6 if rng > 0 else False:
                    if pd.notna(vol_ma20.iloc[i]) and c['Volume'] > vol_ma20.iloc[i]*2 and c['Close'] > p['Close']*1.03:
                        markers.append((chart_df.index[i], c['High']*1.02))
            if markers:
                fig.add_trace(go.Scatter(x=[m[0] for m in markers], y=[m[1] for m in markers], mode='markers+text', name='🔥장대양봉', marker=dict(symbol='triangle-up', size=12, color='red'), text=['🔥']*len(markers), textposition='top center'), row=1, col=1)
            colors = ['red' if o <= c else 'blue' for o, c in zip(chart_df['Open'], chart_df['Close'])]
            fig.add_trace(go.Bar(x=chart_df.index, y=chart_df['Volume'], name='거래량', marker_color=colors, opacity=0.5), row=2, col=1)
            fig.update_layout(legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0), xaxis_rangeslider_visible=False, height=500, margin=dict(l=50, r=50, t=50, b=30))
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e: st.warning(f"차트 오류: {e}")

# Main UI
st.sidebar.title("메뉴")
mode = st.sidebar.radio("모드", ["🔍 실시간 종목 진단", "📊 당일 시장 스캐너", "🖼️ 차트 이미지 분석"])
if st.sidebar.button("🔄 새로고침"): st.cache_data.clear(); st.rerun()

if mode == "📊 당일 시장 스캐너":
    min_score = st.slider("최소 점수", 0, 100, 50)
    df, sector_df, filename = load_data()
    if df is None: st.error("❌ 데이터 없음"); st.stop()
    df['code'] = df['code'].astype(str).str.zfill(6)
    st.success(f"✅ {filename} ({len(df)}개)")
    st.markdown("### 🧭 시장 주도 섹터 분석")
    c1, c2 = st.columns(2)
    market_leaders = []
    with c1:
        st.info("📊 시장 주도 섹터 (Top-Down)")
        if sector_df is not None and len(sector_df) > 0:
            valid = sector_df[sector_df['Sector'] != '기타']
            if len(valid) > 0:
                top = valid.head(5)[['Sector', 'AvgReturn_3M', 'StockCount']]
                market_leaders = top['Sector'].tolist()
                st.dataframe(top.style.format({'AvgReturn_3M': '{:.1f}%'}), use_container_width=True, hide_index=True)
    with c2:
        st.success("🎯 스캐너 포착 섹터")
        if 'sector' in df.columns:
            valid = df[df['sector'] != '기타']['sector']
            if len(valid) > 0:
                ss = valid.value_counts().head(5).reset_index()
                ss.columns = ['Sector', 'Count']
                ss['일치'] = ss['Sector'].apply(lambda x: "✅" if x in market_leaders else "-")
                st.dataframe(ss, use_container_width=True, hide_index=True)
    st.markdown("---")
    if 'total_score' in df.columns: df = df.sort_values('total_score', ascending=False).reset_index(drop=True)
    filtered = df[df['total_score'] >= min_score].copy()
    st.subheader(f"🏆 상위 종목 ({len(filtered)}개)")
    with st.popover("ℹ️ 점수 설명"):
        st.markdown("**추세(25)+위치(30)+거래량(20)+수급(15)+리스크(10)=100점**")
    cols = ['name', 'sector', 'close', 'total_score', 'setup', 'trend_score', 'pattern_score', 'volume_score', 'supply_score']
    cols = [c for c in cols if c in filtered.columns]
    disp = filtered[cols].copy()
    disp.insert(0, '순위', range(1, len(disp)+1))
    disp = disp.rename(columns={'name':'종목명','sector':'업종','close':'현재가','total_score':'총점','setup':'셋업','trend_score':'추세','pattern_score':'위치','volume_score':'거래량','supply_score':'수급'})
    event = st.dataframe(disp, use_container_width=True, height=400, hide_index=True, on_select="rerun", selection_mode="single-row")
    if event.selection and len(event.selection.rows) > 0:
        display_stock_report(df[df['code'] == filtered.iloc[event.selection.rows[0]]['code']].iloc[0], sector_df)

elif mode == "🔍 실시간 종목 진단":
    st.subheader("🔍 실시간 종목 진단")
    stock_df = get_krx_codes()
    # text_input with autocomplete
    name_input = st.text_input("종목명 입력 (자동완성)", "")
    matched = stock_df[stock_df['Name'].str.contains(name_input, case=False, na=False)] if name_input else stock_df.head(10)
    if len(matched) > 0:
        selected_name = st.selectbox("선택", matched['Name'].tolist(), label_visibility="collapsed")
        selected_code = stock_df[stock_df['Name'] == selected_name]['Code'].iloc[0]
    else:
        st.warning("종목을 찾을 수 없습니다.")
        st.stop()
    rs_3m = st.number_input("3개월 RS", 0, 100, 0, 1)
    rs_6m = st.number_input("6개월 RS", 0, 100, 0, 1)
    inv = {}
    df_scan, sector_df, _ = load_data()
    if df_scan is not None:
        df_scan['code'] = df_scan['code'].astype(str).str.zfill(6)
        r = df_scan[df_scan['code'] == str(selected_code).zfill(6)]
        if not r.empty:
            r = r.iloc[0]
            inv = {'foreign_consecutive_buy': r.get('foreign_consec_buy', 0), 'inst_net_buy_5d': r.get('inst_net_5d', 0), 'foreign_net_buy_5d': r.get('foreign_net_5d', 0)}
    df_stock = fdr.DataReader(selected_code, datetime.now()-timedelta(days=365), datetime.now())
    if df_stock is not None and len(df_stock) > 0:
        cfg = load_config()
        sig = calculate_signals(df_stock, cfg)
        result = score_stock(df_stock, sig, cfg, rs_3m=rs_3m, rs_6m=rs_6m, investor_data=inv if inv else None)
        if result:
            row = pd.Series(result)
            row['name'], row['code'], row['sector'] = selected_name, selected_code, ''
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
                    for l in result.get("ocr_text", []): st.caption(f"- {l}")
                with c2:
                    for p in result.get("patterns", []): st.success(f"{p['name']} ({p['confidence']*100:.0f}%)")
        stock_df = get_krx_codes()
        name_input = st.text_input("종목명 입력", "", key='img_name_input')
        matched = stock_df[stock_df['Name'].str.contains(name_input, case=False, na=False)] if name_input else stock_df.head(10)
        if len(matched) > 0:
            selected_name = st.selectbox("선택", matched['Name'].tolist(), key='img_sel', label_visibility="collapsed")
            selected_code = stock_df[stock_df['Name'] == selected_name]['Code'].iloc[0]
        else: st.warning("종목 없음"); st.stop()
        rs_3m = st.number_input("3개월 RS", 0, 100, 0, 1, key='img_rs3')
        rs_6m = st.number_input("6개월 RS", 0, 100, 0, 1, key='img_rs6')
        inv = {}
        df_scan, _, _ = load_data()
        if df_scan is not None:
            r = df_scan[df_scan['code'].astype(str).str.zfill(6) == str(selected_code).zfill(6)]
            if not r.empty:
                r = r.iloc[0]
                inv = {'foreign_consecutive_buy': r.get('foreign_consec_buy', 0), 'inst_net_buy_5d': r.get('inst_net_5d', 0), 'foreign_net_buy_5d': r.get('foreign_net_5d', 0)}
        df_stock = fdr.DataReader(selected_code, datetime.now()-timedelta(days=365), datetime.now())
        if df_stock is not None and len(df_stock) > 0:
            cfg = load_config()
            sig = calculate_signals(df_stock, cfg)
            result = score_stock(df_stock, sig, cfg, rs_3m=rs_3m, rs_6m=rs_6m, investor_data=inv)
            if result:
                row = pd.Series(result)
                row['name'], row['code'], row['sector'] = selected_name, selected_code, ''
                if inv:
                    row['foreign_consec_buy'] = inv.get('foreign_consecutive_buy', 0)
                    row['foreign_net_5d'] = inv.get('foreign_net_buy_5d', 0)
                    row['inst_net_5d'] = inv.get('inst_net_buy_5d', 0)
                display_stock_report(row, None, rs_3m, rs_6m)
            else: st.error("점수 계산 실패")
        else: st.error("데이터 없음")
