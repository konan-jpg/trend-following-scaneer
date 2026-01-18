import streamlit as st
import pandas as pd
import glob
import os
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="추세추종 스캐너")

@st.cache_data(ttl=300)
def load_data():
    """데이터 로드"""
    merged_files = glob.glob("data/scanner_output*.csv")
    merged_files = [f for f in merged_files if 'chunk' not in f]
    
    if merged_files:
        def extract_date(filename):
            try:
                parts = os.path.basename(filename).replace('.csv', '').split('_')
                if len(parts) >= 3:
                    return parts[-1]
                return '0000-00-00'
            except:
                return '0000-00-00'
        
        latest_file = max(merged_files, key=extract_date)
        df = pd.read_csv(latest_file, dtype={'code': str})
        return df, os.path.basename(latest_file)

    chunk_files = glob.glob("data/partial/scanner_output*chunk*.csv")
    
    if chunk_files:
        df_list = []
        for f in sorted(chunk_files):
            try:
                sub_df = pd.read_csv(f, dtype={'code': str})
                df_list.append(sub_df)
            except:
                continue
        
        if df_list:
            final_df = pd.concat(df_list, ignore_index=True)
            if 'code' in final_df.columns:
                final_df.drop_duplicates(subset=['code'], keep='first', inplace=True)
            
            return final_df, f"Merged from {len(df_list)} chunks"

    return None, None

def get_setup_explanations():
    """셋업 타입 설명"""
    return {
        'R': "🔥 재돌파 패턴 - 60일 내 BB(60,2) 돌파 후 눌림 → 재돌파 (가장 강력)",
        'B': "거래량 급등(평균 5배) 후 고점 돌파 + 거래량 재확인",
        'A': "볼린저밴드(60,2) 상단 돌파 + 밴드폭 수축 + 거래량 확인 + ADX 강세",
        'C': "20일 이평선 돌파 + 거래량 증가 + ADX 상승 추세",
        '-': "기본 추세 및 유동성 기준만 충족"
    }

def get_score_explanations():
    """점수 구성요소 설명 (새 체계)"""
    return {
        'trend_score': {
            'name': '추세 점수 (25점)',
            'description': '이동평균선 정렬과 ADX 추세 강도',
            'components': [
                '현재가 > 20일선: +5점',
                '현재가 > 50일선: +5점',
                '현재가 > 200일선: +5점',
                'MA 정렬 (20>50, 50>200): +5점',
                'ADX 강도: +2~5점'
            ]
        },
        'pattern_score': {
            'name': '패턴 점수 (30점)',
            'description': '매수 타이밍 신호 (재돌파, VCP 특성)',
            'components': [
                '재돌파 패턴 (Setup R): +15점',
                '기준봉 돌파 (Setup B): +10점',
                '스퀴즈 돌파 (Setup A): +8점',
                'MA20 돌파 (Setup C): +5점',
                '밴드폭 수축 상태: +5점'
            ]
        },
        'volume_score': {
            'name': '거래량 점수 (20점)',
            'description': '거래량 급등 및 건조(매집) 신호',
            'components': [
                '돌파 시 거래량 확인: +8점',
                '거래량 건조 (매집): +5~7점',
                '하락 시 거래량 감소: +5점'
            ]
        },
        'supply_score': {
            'name': '수급 점수 (15점)',
            'description': '외국인/기관 투자자 동향',
            'components': [
                '외국인 연속 매수 5일+: +8점',
                '외국인 연속 매수 3일+: +5점',
                '기관 5일 순매수: +4점',
                '외국인 5일 순매수: +3점'
            ]
        },
        'risk_score': {
            'name': '리스크 점수 (10점)',
            'description': '손절가 거리 기반 리스크 평가',
            'components': [
                '리스크 5% 이하: 10점 (만점)',
                '리스크 5~8%: -1점',
                '리스크 8~10%: -3점',
                '리스크 10%+: -5점'
            ]
        }
    }

# 메인 앱
st.title("📊 추세추종 스캐너")

# 상단 필터
with st.expander("🎛️ 필터 설정", expanded=False):
    min_score = st.slider("최소 점수", 0, 100, 50)

df, filename = load_data()

if df is None:
    st.error("❌ 결과 파일이 없습니다.")
    st.stop()

if 'code' in df.columns:
    df['code'] = df['code'].astype(str).str.zfill(6)

st.success(f"✅ 데이터 로드: {filename} (총 {len(df)}개)")

if 'total_score' in df.columns:
    df = df.sort_values(by='total_score', ascending=False).reset_index(drop=True)

filtered_df = df[df['total_score'] >= min_score].copy()

# 표 표시
st.subheader(f"🏆 상위 랭킹 종목 ({len(filtered_df)}개)")

# 점수 설명 도움말 (모바일 친화적 - 터치로 열기)
with st.popover("ℹ️ 점수 구성 설명", use_container_width=True):
    st.markdown("""### 📊 점수 체계 (100점 만점)
**🔹 추세 (25점)**: MA20/50/200 정렬 + ADX 강도

**🔹 패턴 (30점)**: 재돌파(R)+15, 기준봉(B)+10, 스퀴즈(A)+8

**🔹 거래량 (20점)**: 돌파 시 거래량 확인 + 거래량 건조(매집)

**🔹 수급 (15점)**: 외국인/기관 연속매수 및 순매수

**🔹 리스크 (10점)**: 손절가 거리 (가까울수록 높은 점수)
""")

st.caption("👆 행 클릭 → 상세 분석 | ℹ️ 터치 → 점수 설명")

# 표시할 컬럼 (새 점수 체계)
display_cols = ['code', 'name', 'close', 'total_score', 'setup', 'trend_score', 'pattern_score', 'volume_score', 'supply_score']
display_cols = [col for col in display_cols if col in filtered_df.columns]

# 레거시 컬럼 대체
if 'pattern_score' not in filtered_df.columns and 'trigger_score' in filtered_df.columns:
    filtered_df['pattern_score'] = filtered_df['trigger_score']
if 'volume_score' not in filtered_df.columns and 'liq_score' in filtered_df.columns:
    filtered_df['volume_score'] = filtered_df['liq_score']
if 'supply_score' not in filtered_df.columns:
    filtered_df['supply_score'] = 0

display_cols = [col for col in display_cols if col in filtered_df.columns]

display_df = filtered_df[display_cols].copy()
display_df.insert(0, '순위', range(1, len(display_df) + 1))

# 컬럼명 한글화
rename_map = {
    '순위': '순위',
    'code': '코드',
    'name': '종목명',
    'close': '현재가',
    'total_score': '총점',
    'setup': '셋업',
    'trend_score': '추세',
    'pattern_score': '패턴',
    'volume_score': '거래량',
    'supply_score': '수급'
}
display_df = display_df.rename(columns=rename_map)

# 테이블 클릭으로 종목 선택
event = st.dataframe(
    display_df,
    use_container_width=True,
    height=400,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row"
)

# 선택된 행 처리
selected_code = None
if event.selection and len(event.selection.rows) > 0:
    selected_idx = event.selection.rows[0]
    selected_code = filtered_df.iloc[selected_idx]['code']

# 종목 상세 분석
if selected_code:
    matching = df[df['code'] == selected_code]
    
    if len(matching) > 0:
        row = matching.iloc[0]
        
        st.markdown("---")
        st.subheader(f"📊 {row['name']} ({row['code']}) 상세 분석")
        
        # 메트릭 (5열)
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("현재가", f"{row['close']:,.0f}원")
        with col2:
            st.metric("총점", f"{row['total_score']:.0f}점")
        with col3:
            setup_type = row.get('setup', '-')
            st.metric("셋업", setup_type)
        with col4:
            if 'risk_pct' in row and pd.notna(row['risk_pct']):
                st.metric("리스크", f"{row['risk_pct']:.1f}%")
        with col5:
            foreign = row.get('foreign_consec_buy', 0)
            if pd.notna(foreign) and foreign > 0:
                st.metric("외국인 연속매수", f"{int(foreign)}일")
        
        # 셋업 설명
        with st.expander(f"ℹ️ 셋업 설명 (현재: Setup {setup_type})", expanded=False):
            setup_explanations = get_setup_explanations()
            for stype, desc in setup_explanations.items():
                if stype == setup_type:
                    st.success(f"**▶ Setup {stype}** (현재): {desc}")
                else:
                    st.write(f"**Setup {stype}**: {desc}")
        
        st.markdown("---")
        
        # 점수 구성 상세 (5개 카테고리)
        st.markdown("#### 📈 점수 구성 상세 (100점 만점)")
        
        score_info = get_score_explanations()
        
        # 점수 바 차트
        score_data = {
            '추세': row.get('trend_score', 0),
            '패턴': row.get('pattern_score', row.get('trigger_score', 0)),
            '거래량': row.get('volume_score', row.get('liq_score', 0)),
            '수급': row.get('supply_score', 0),
            '리스크': row.get('risk_score', 10)
        }
        
        score_cols = st.columns(5)
        max_scores = [25, 30, 20, 15, 10]
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7']
        
        for i, (label, score) in enumerate(score_data.items()):
            with score_cols[i]:
                st.metric(label, f"{score:.0f}/{max_scores[i]}")
        
        # 상세 설명 (접기)
        for key, info in score_info.items():
            score_val = score_data.get(info['name'].split('(')[0].strip().replace('점수', '').strip(), 0)
            with st.expander(f"🔹 {info['name']}", expanded=False):
                st.markdown(f"**{info['description']}**")
                for comp in info['components']:
                    st.write(f"• {comp}")
        
        # 수급 정보 (있으면 표시)
        if 'foreign_net_5d' in row or 'inst_net_5d' in row:
            st.markdown("---")
            st.markdown("#### 💰 최근 수급 현황")
            sup_cols = st.columns(3)
            with sup_cols[0]:
                foreign_consec = row.get('foreign_consec_buy', 0)
                if pd.notna(foreign_consec):
                    st.write(f"**외국인 연속 매수**: {int(foreign_consec)}일")
            with sup_cols[1]:
                foreign_net = row.get('foreign_net_5d', 0)
                if pd.notna(foreign_net):
                    st.write(f"**외국인 5일 순매수**: {foreign_net/1e8:,.1f}억")
            with sup_cols[2]:
                inst_net = row.get('inst_net_5d', 0)
                if pd.notna(inst_net):
                    st.write(f"**기관 5일 순매수**: {inst_net/1e8:,.1f}억")
        
        # 기술적 지표
        st.markdown("---")
        st.markdown("#### 📊 기술적 지표")
        
        indicator_cols = st.columns(4)
        with indicator_cols[0]:
            if 'ma20' in row and pd.notna(row['ma20']):
                st.write(f"**20일선**: {row['ma20']:,.0f}원")
        with indicator_cols[1]:
            if 'ma60' in row and pd.notna(row['ma60']):
                st.write(f"**60일선**: {row['ma60']:,.0f}원")
        with indicator_cols[2]:
            if 'adx' in row and pd.notna(row['adx']):
                st.write(f"**ADX**: {row['adx']:.1f}")
        with indicator_cols[3]:
            if 'stop' in row and pd.notna(row['stop']):
                st.write(f"**손절가**: {row['stop']:,.0f}원")
        
        # 차트
        st.markdown("---")
        st.markdown("#### 📉 가격 차트 (최근 6개월)")
        
        try:
            import FinanceDataReader as fdr
            from datetime import timedelta
            import numpy as np
            
            end_date = datetime.now()
            start_date = end_date - timedelta(days=180)
            
            chart_df = fdr.DataReader(row['code'], start_date, end_date)
            
            if chart_df is not None and len(chart_df) > 0:
                # 이동평균 및 볼린저밴드
                chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
                chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
                
                bb_mid = chart_df['Close'].rolling(60).mean()
                bb_std = chart_df['Close'].rolling(60).std()
                chart_df['BB_Upper'] = bb_mid + (2 * bb_std)
                chart_df['BB_Lower'] = bb_mid - (2 * bb_std)
                
                # 거래량 급등 감지
                vol_ma = chart_df['Volume'].rolling(20).mean()
                chart_df['Vol_Spike'] = chart_df['Volume'] > vol_ma * 2
                
                # 차트 생성
                fig = make_subplots(
                    rows=2, cols=1,
                    row_heights=[0.75, 0.25],
                    vertical_spacing=0.03,
                    subplot_titles=("", "")
                )
                
                # 현재가 가져오기
                current_price = chart_df['Close'].iloc[-1]
                
                # 캔들스틱
                fig.add_trace(
                    go.Candlestick(
                        x=chart_df.index,
                        open=chart_df['Open'],
                        high=chart_df['High'],
                        low=chart_df['Low'],
                        close=chart_df['Close'],
                        name=f'가격 {current_price:,.0f}',
                        increasing_line_color='red',
                        increasing_fillcolor='red',
                        decreasing_line_color='blue',
                        decreasing_fillcolor='blue'
                    ),
                    row=1, col=1
                )
                
                # 이동평균선
                fig.add_trace(
                    go.Scatter(x=chart_df.index, y=chart_df['MA20'],
                              mode='lines', name='MA20',
                              line=dict(color='orange', width=1.5)),
                    row=1, col=1
                )
                fig.add_trace(
                    go.Scatter(x=chart_df.index, y=chart_df['MA60'],
                              mode='lines', name='MA60',
                              line=dict(color='purple', width=1.5)),
                    row=1, col=1
                )
                
                # 볼린저밴드 상단
                fig.add_trace(
                    go.Scatter(x=chart_df.index, y=chart_df['BB_Upper'],
                              mode='lines', name='BB상단',
                              line=dict(color='gray', width=1, dash='dot')),
                    row=1, col=1
                )
                
                # 손절가 라인 (범례에 표시되도록 Scatter로 구현)
                if 'stop' in row and pd.notna(row['stop']):
                    stop_price = row['stop']
                    fig.add_trace(
                        go.Scatter(
                            x=[chart_df.index[0], chart_df.index[-1]],
                            y=[stop_price, stop_price],
                            mode='lines',
                            name=f'손절 {stop_price:,.0f}',
                            line=dict(color='red', width=1.5, dash='dash'),
                            hoverinfo='name+y'
                        ),
                        row=1, col=1
                    )
                
                # 거래량 바
                colors = ['red' if chart_df.loc[i, 'Close'] >= chart_df.loc[i, 'Open'] 
                         else 'blue' for i in chart_df.index]
                
                fig.add_trace(
                    go.Bar(x=chart_df.index, y=chart_df['Volume'],
                          name='거래량', marker_color=colors, showlegend=False),
                    row=2, col=1
                )
                
                # 레이아웃
                fig.update_layout(
                    height=550,
                    xaxis_rangeslider_visible=False,
                    hovermode='x unified',
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="center",
                        x=0.5,
                        font=dict(size=12),
                        itemsizing='constant',
                        itemwidth=50
                    ),
                    margin=dict(l=5, r=5, t=40, b=5)
                )
                
                fig.update_xaxes(showticklabels=False, row=1, col=1)
                fig.update_xaxes(showticklabels=True, row=2, col=1, tickfont=dict(size=10))
                fig.update_yaxes(title_text="", row=1, col=1)
                fig.update_yaxes(title_text="", row=2, col=1)
                
                st.plotly_chart(fig, use_container_width=True)
                
            else:
                st.warning("차트 데이터를 불러올 수 없습니다.")
                
        except Exception as e:
            st.error(f"차트 생성 중 에러: {e}")

else:
    st.info("👆 테이블에서 종목 행을 클릭하면 상세 분석이 표시됩니다.")

st.markdown("---")
st.caption(f"업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {filename}")
