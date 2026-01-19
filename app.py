# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import glob
import os
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import FinanceDataReader as fdr
import yaml
from scanner_core import calculate_signals, score_stock

st.set_page_config(layout="wide", page_title="추세추종 스캐너 Pro")

# -----------------------------
# 1. 안전한 데이터 로딩 함수 (Safe Loaders)
# -----------------------------
@st.cache_data(ttl=300)
def load_config():
    if os.path.exists("config.yaml"):
        with open("config.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

@st.cache_data
def get_krx_codes():
    """
    종목 리스트 로딩 (3중 안전장치)
    1. 실시간 크롤링 -> 2. 백업 파일 -> 3. 스캔 결과에서 추출
    """
    # 1. 실시간 시도
    try:
        df = fdr.StockListing("KRX")
        if not df.empty: return df[['Code', 'Name', 'Market']]
    except: pass

    # 2. 백업 파일 시도
    try:
        if os.path.exists("data/krx_tickers.csv"):
            df = pd.read_csv("data/krx_tickers.csv", dtype={'Code':str})
            if 'Market' not in df.columns: df['Market'] = 'KRX'
            return df[['Code', 'Name', 'Market']]
    except: pass

    # 3. 스캔 결과에서 복구
    try:
        files = glob.glob("data/scanner_output*.csv")
        if files:
            latest = max(files, key=os.path.getctime)
            df = pd.read_csv(latest, dtype={'code':str})
            df = df[['code', 'name']].rename(columns={'code':'Code', 'name':'Name'})
            df['Market'] = 'KRX'
            return df.drop_duplicates()
    except: pass
        
    return pd.DataFrame()

@st.cache_data(ttl=600)
def get_market_status():
    """지수 확인 (네이버 차단 시 야후 우회)"""
    status = {}
    indices = [("KOSPI", "KS11", "^KS11"), ("KOSDAQ", "KQ11", "^KQ11")]
    
    for name, code_n, code_y in indices:
        df = None
        try: df = fdr.DataReader(code_n, datetime.now() - timedelta(days=60)) # 네이버
        except: pass
        
        if df is None or df.empty:
            try: df = fdr.DataReader(code_y, datetime.now() - timedelta(days=60), data_source='yahoo') # 야후
            except: pass
        
        if df is not None and len(df) > 20:
            last = df['Close'].iloc[-1]
            ma20 = df['Close'].rolling(20).mean().iloc[-1]
            prev = df['Close'].iloc[-2]
            status[name] = {
                "price": last, "change": (last-prev)/prev*100,
                "is_bullish": last >= ma20
            }
        else: status[name] = None
    return status

@st.cache_data(ttl=300)
def load_scan_data():
    """스캔 데이터 로드 및 전처리"""
    files = glob.glob("data/scanner_output*.csv")
    files = [f for f in files if "chunk" not in f]
    if not files: return None, None
    
    latest_file = max(files, key=lambda x: os.path.basename(x))
    df = pd.read_csv(latest_file, dtype={'code': str})
    
    # 날짜 추출
    file_date = os.path.basename(latest_file).replace("scanner_output_", "").replace(".csv", "")
    return df, file_date

# -----------------------------
# 2. UI 컴포넌트 (Report & Chart)
# -----------------------------
def display_stock_report(row, rs_3m=None, rs_6m=None):
    """
    상세 분석 보고서 (예전 스타일 복구)
    """
    st.markdown("---")
    
    # 점수 컬럼 호환성 처리 (Old vs New)
    total_score = row.get('total_score', row.get('score', 0))
    # 태그나 셋업 정보
    setup = row.get('setup', row.get('tags', '-'))
    
    st.subheader(f"📊 {row.get('name', 'N/A')} ({row.get('code', '')})")
    
    # 1. 핵심 정보 카드 (Grid Layout)
    st.markdown(f"""
    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 15px;">
        <div style="background: #f0f2f6; padding: 10px; border-radius: 8px; text-align: center;">
            <div style="color: #666; font-size: 12px;">현재가</div>
            <div style="font-weight: bold; font-size: 16px;">{row['close']:,.0f}원</div>
        </div>
        <div style="background: #e8f5e9; padding: 10px; border-radius: 8px; text-align: center;">
            <div style="color: #2e7d32; font-size: 12px;">총점</div>
            <div style="font-weight: bold; font-size: 16px; color: #2e7d32;">{total_score:.0f}점</div>
        </div>
        <div style="background: #e3f2fd; padding: 10px; border-radius: 8px; text-align: center;">
            <div style="color: #1565c0; font-size: 12px;">셋업/태그</div>
            <div style="font-weight: bold; font-size: 16px; color: #1565c0;">{setup}</div>
        </div>
        <div style="background: #fff3e0; padding: 10px; border-radius: 8px; text-align: center;">
            <div style="color: #ef6c00; font-size: 12px;">리스크</div>
            <div style="font-weight: bold; font-size: 16px; color: #ef6c00;">{row.get('risk_pct', 0):.1f}%</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 2. 점수 상세 (호환성 확보)
    st.markdown("#### 📈 점수 구성")
    score_cols = st.columns(5)
    
    # 데이터에 있는 컬럼만 안전하게 가져오기
    trend = row.get('trend_score', 0)
    pattern = row.get('pattern_score', 0)
    volume = row.get('volume_score', 0)
    # 구버전: supply / 신버전: memory
    supply_or_mem = row.get('supply_score') if 'supply_score' in row else row.get('memory_score', 0)
    label_4 = "수급" if 'supply_score' in row else "메모리"
    
    with score_cols[0]: st.metric("추세", f"{trend:.0f}")
    with score_cols[1]: st.metric("패턴", f"{pattern:.0f}")
    with score_cols[2]: st.metric("거래량", f"{volume:.0f}")
    with score_cols[3]: st.metric(label_4, f"{supply_or_mem:.0f}")
    with score_cols[4]: st.metric("RS가산", f"+{5 if (rs_3m or 0)>=80 else 0}")

    # 3. 차트 그리기
    try:
        chart_df = fdr.DataReader(row['code'], datetime.now() - timedelta(days=180))
        if chart_df is not None:
            # 보조지표
            chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
            chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
            mid = chart_df['Close'].rolling(60).mean()
            std = chart_df['Close'].rolling(60).std()
            chart_df['Upper'] = mid + 2*std
            
            fig = make_subplots(rows=2, cols=1, row_heights=[0.7, 0.3], shared_xaxes=True, vertical_spacing=0.05)
            
            # 캔들
            fig.add_trace(go.Candlestick(x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'], name='Price'), row=1, col=1)
            # 이평선
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA20'], line=dict(color='orange', width=1), name='MA20'), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['Upper'], line=dict(color='gray', dash='dot', width=1), name='BB Upper'), row=1, col=1)
            # 거래량
            colors = ['red' if o <= c else 'blue' for o, c in zip(chart_df['Open'], chart_df['Close'])]
            fig.add_trace(go.Bar(x=chart_df.index, y=chart_df['Volume'], marker_color=colors, name='Volume'), row=2, col=1)
            
            fig.update_layout(height=500, xaxis_rangeslider_visible=False, showlegend=False, margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig, use_container_width=True)
    except:
        st.error("차트 로딩 실패")

# -----------------------------
# 3. Main App Layout
# -----------------------------
st.title("🚀 추세추종 스캐너")

# [상단] 시장 지수 (안전하게 표시)
market_data = get_market_status()
if market_data:
    m_cols = st.columns(2)
    for idx, (name, data) in enumerate(market_data.items()):
        with m_cols[idx]:
            if data:
                color = "red" if data['is_bullish'] else "blue"
                icon = "🔺" if data['is_bullish'] else "🔻"
                st.metric(label=f"{name} (20일선 {icon})", value=f"{data['price']:,.2f}", delta=f"{data['change']:.2f}%")
            else:
                st.metric(label=name, value="N/A")
else:
    st.caption("지수 데이터 로딩 중...")

st.divider()

# 사이드바 & 모드
st.sidebar.header("메뉴")
mode = st.sidebar.radio("기능 선택", ["📊 당일 시장 스캐너", "🔍 실시간 종목 진단", "🖼️ 차트 이미지 분석"])

# ==========================================
# MODE 1: 당일 시장 스캐너 (복구됨!)
# ==========================================
if mode == "📊 당일 시장 스캐너":
    st.subheader("📊 당일 시장 스캐너 결과")
    
    df, file_date = load_scan_data()
    
    if df is None:
        st.warning("⚠️ 스캔된 데이터가 없습니다. (GitHub Actions 실행 필요)")
    else:
        # 날짜 확인 및 경고
        today_str = datetime.now().strftime("%Y-%m-%d")
        if file_date != today_str:
            st.warning(f"⚠️ 주의: 오늘({today_str}) 데이터가 아닙니다. (데이터 날짜: {file_date})\n스캔이 완료되지 않았거나 실패했을 수 있습니다.")
        else:
            st.success(f"📅 데이터 기준: {file_date}")

        # 필터링
        col_f1, col_f2 = st.columns([2, 1])
        with col_f1:
            # 점수 컬럼 호환성 (total_score or score)
            score_key = 'total_score' if 'total_score' in df.columns else 'score'
            min_score = st.slider("최소 점수 필터", 0, 100, 70)
        
        filtered_df = df[df[score_key] >= min_score].copy()
        
        # [핵심] 테이블 깔끔하게 정리 (표시할 컬럼만 선택)
        # 호환성을 위해 컬럼이 있는지 확인하고 선택
        target_cols = ['name', 'code', 'close', score_key, 'setup', 'trend_score', 'pattern_score', 'volume_score']
        # supply가 있으면 넣고, memory가 있으면 넣고
        if 'supply_score' in df.columns: target_cols.append('supply_score')
        if 'memory_score' in df.columns: target_cols.append('memory_score')
        if 'tags' in df.columns: target_cols.append('tags')
        
        # 실제 존재하는 컬럼만 필터링
        display_cols = [c for c in target_cols if c in filtered_df.columns]
        
        display_df = filtered_df[display_cols].copy()
        
        # 컬럼명 한글 변환 (보기 좋게)
        rename_map = {
            'name': '종목명', 'code': '코드', 'close': '현재가', 
            score_key: '총점', 'setup': '셋업', 'tags': '태그',
            'trend_score': '추세', 'pattern_score': '패턴', 'volume_score': '거래량',
            'supply_score': '수급', 'memory_score': '메모리'
        }
        display_df = display_df.rename(columns=rename_map)
        
        # 테이블 표시 (선택 가능하게!)
        st.caption(f"총 {len(display_df)}개 종목이 검색되었습니다. 행을 클릭하면 상세 분석이 나옵니다.")
        
        event = st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            height=400
        )
        
        # 선택 시 상세 리포트 표시
        if event.selection and len(event.selection.rows) > 0:
            idx = event.selection.rows[0]
            # 원본 df에서 행 찾기 (display_df는 정렬/필터링 되었을 수 있으므로 주의)
            # st.dataframe의 인덱스는 display_df의 iloc 인덱스와 일치함
            selected_row = filtered_df.iloc[idx]
            
            # 상세 리포트 함수 호출
            display_stock_report(selected_row)

# ==========================================
# MODE 2: 실시간 종목 진단 (안전장치 적용)
# ==========================================
elif mode == "🔍 실시간 종목 진단":
    st.subheader("🔍 실시간 종목 진단")
    
    stock_list = get_krx_codes()
    
    if stock_list.empty:
        st.error("❌ 종목 리스트 로딩 실패. (data 폴더 확인 필요)")
    else:
        # 검색창 복구
        c1, c2 = st.columns([3, 1])
        with c1:
            s_name = st.selectbox("종목 선택", stock_list['Name'])
        with c2:
            use_today = st.checkbox("오늘 데이터 포함", value=True)
            
        rs_3m = st.number_input("3개월 RS (0~100)", 0, 100, 0)
        
        if s_name:
            code = stock_list[stock_list['Name'] == s_name]['Code'].iloc[0]
            
            if st.button("지금 분석하기"):
                with st.spinner("분석 중..."):
                    try:
                        df = fdr.DataReader(code, datetime.now() - timedelta(days=400))
                        if df is not None and len(df) > 60:
                            if not use_today: df = df.iloc[:-1]
                            
                            # 설정 로드
                            cfg = load_config()
                            # 시그널 계산
                            sig = calculate_signals(df, cfg)
                            # 점수 계산 (호환성: 인자 유연하게 넣기)
                            # scanner_core가 구버전이면 investor_data 필요할 수 있음 -> None 처리
                            try:
                                res = score_stock(df, sig, cfg, rs_3m=rs_3m)
                            except TypeError:
                                # 혹시 구버전 score_stock이라 인자가 안 맞으면
                                res = score_stock(df, sig, cfg) # 최소 인자 시도
                                
                            if res:
                                row = pd.Series(res)
                                row['name'] = s_name
                                row['code'] = code
                                display_stock_report(row, rs_3m=rs_3m)
                            else:
                                st.error("점수 계산 실패")
                        else:
                            st.warning("데이터가 부족합니다.")
                    except Exception as e:
                        st.error(f"오류 발생: {e}")

# ==========================================
# MODE 3: 이미지 분석
# ==========================================
elif mode == "🖼️ 차트 이미지 분석":
    st.subheader("🖼️ 차트 이미지 분석")
    uploaded = st.file_uploader("차트 이미지", type=['png', 'jpg'])
    
    if uploaded:
        st.image(uploaded, width=600)
        st.info("이미지 분석 로직 준비 중입니다. (종목명을 선택하여 실시간 분석을 병행하세요)")
        
        stock_list = get_krx_codes()
        if not stock_list.empty:
            s_name = st.selectbox("종목 매핑 (선택)", stock_list['Name'], key='img_sel')
            if s_name and st.button("분석 실행", key='img_btn'):
                # 실시간 진단 로직 재활용
                code = stock_list[stock_list['Name'] == s_name]['Code'].iloc[0]
                df = fdr.DataReader(code, datetime.now() - timedelta(days=400))
                if df is not None:
                    cfg = load_config()
                    sig = calculate_signals(df, cfg)
                    try: res = score_stock(df, sig, cfg)
                    except: res = None
                    
                    if res:
                        row = pd.Series(res)
                        row['name'] = s_name
                        row['code'] = code
                        display_stock_report(row)
