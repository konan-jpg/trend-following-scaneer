import streamlit as st
import pandas as pd
import glob
import os
from datetime import datetime
import plotly.graph_objects as go

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
        df = pd.read_csv(latest_file)
        return df, os.path.basename(latest_file)

    chunk_files = glob.glob("data/partial/scanner_output*chunk*.csv")
    
    if chunk_files:
        df_list = []
        for f in sorted(chunk_files):
            try:
                sub_df = pd.read_csv(f)
                df_list.append(sub_df)
            except Exception as e:
                st.warning(f"파일 읽기 실패: {f}")
                continue
        
        if df_list:
            final_df = pd.concat(df_list, ignore_index=True)
            if 'code' in final_df.columns:
                final_df.drop_duplicates(subset=['code'], keep='first', inplace=True)
            
            st.info(f"📦 Partial 파일 {len(df_list)}개를 합쳐서 표시합니다")
            return final_df, f"Merged from {len(df_list)} chunks"

    return None, None

# 메인 앱
st.title("🔍 추세추종 스캐너 (일봉/장마감)")

df, filename = load_data()

if df is None:
    st.error("❌ 결과 파일이 없습니다.")
    st.stop()

st.success(f"✅ 데이터 로드 완료: {filename} (총 {len(df)}개 종목)")

# 점수 정렬
if 'total_score' in df.columns:
    df = df.sort_values(by='total_score', ascending=False).reset_index(drop=True)
else:
    st.error("total_score 컬럼이 없습니다.")
    st.stop()

# 사이드바 필터
st.sidebar.title("🎛️ 필터 설정")
min_score = st.sidebar.slider("최소 점수", 0, 100, 50)

filtered_df = df[df['total_score'] >= min_score].copy()

# 표 표시 (rank 컬럼 제외, 인덱스도 숨김)
st.subheader(f"🏆 상위 랭킹 종목 ({len(filtered_df)}개)")

display_cols = ['code', 'name', 'close', 'total_score', 'trend_score', 'vol_score']
display_cols = [col for col in display_cols if col in filtered_df.columns]

# 표시용 데이터프레임 생성 (순위 추가)
display_df = filtered_df[display_cols].copy()
display_df.insert(0, '순위', range(1, len(display_df) + 1))

# 컬럼명 한글화
column_config = {
    '순위': st.column_config.NumberColumn('순위', width='small'),
    'code': st.column_config.TextColumn('종목코드', width='small'),
    'name': st.column_config.TextColumn('종목명', width='medium'),
    'close': st.column_config.NumberColumn('현재가', format='%d원'),
    'total_score': st.column_config.NumberColumn('총점', format='%d점'),
    'trend_score': st.column_config.NumberColumn('추세', format='%d점'),
    'vol_score': st.column_config.NumberColumn('거래량', format='%d점'),
}

# 클릭 가능한 테이블
event = st.dataframe(
    display_df,
    use_container_width=True,
    height=400,
    column_config=column_config,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row"
)

# 선택된 행 처리
if event.selection and len(event.selection.rows) > 0:
    selected_idx = event.selection.rows[0]
    selected_code = display_df.iloc[selected_idx]['code']
    
    # 원본 데이터에서 종목 찾기
    matching = df[df['code'].astype(str) == str(selected_code)]
    
    if len(matching) > 0:
        row = matching.iloc[0]
        
        st.markdown("---")
        st.subheader(f"📊 {row['name']} ({row['code']}) 상세 분석")
        
        # 메트릭 표시
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("현재가", f"{row['close']:,.0f}원")
        with col2:
            st.metric("총점", f"{row['total_score']:.0f}점")
        with col3:
            st.metric("추세 점수", f"{row['trend_score']:.0f}점")
        with col4:
            if 'setup' in row and pd.notna(row['setup']):
                st.metric("셋업", row['setup'])
        
        # 상세 정보
        col_left, col_right = st.columns(2)
        
        with col_left:
            st.markdown("#### 📈 기술적 지표")
            if 'ma20' in row and pd.notna(row['ma20']):
                st.write(f"**20일 이평선**: {row['ma20']:,.0f}원")
            if 'ma60' in row and pd.notna(row['ma60']):
                st.write(f"**60일 이평선**: {row['ma60']:,.0f}원")
            if 'adx' in row and pd.notna(row['adx']):
                st.write(f"**ADX**: {row['adx']:.1f}")
            if 'bbw_pct' in row and pd.notna(row['bbw_pct']):
                st.write(f"**밴드폭 백분위**: {row['bbw_pct']:.1f}%")
        
        with col_right:
            st.markdown("#### 🎯 리스크 관리")
            if 'stop' in row and pd.notna(row['stop']):
                st.write(f"**손절가**: {row['stop']:,.0f}원")
            if 'risk_pct' in row and pd.notna(row['risk_pct']):
                st.write(f"**리스크**: {row['risk_pct']:.1f}%")
            if 'liq_score' in row and pd.notna(row['liq_score']):
                st.write(f"**유동성 점수**: {row['liq_score']:.0f}점")
            if 'trigger_score' in row and pd.notna(row['trigger_score']):
                st.write(f"**트리거 점수**: {row['trigger_score']:.0f}점")
        
        # 차트 표시 (FinanceDataReader로 최근 데이터 가져오기)
        st.markdown("#### 📉 가격 차트 (최근 6개월)")
        
        try:
            import FinanceDataReader as fdr
            from datetime import timedelta
            
            end_date = datetime.now()
            start_date = end_date - timedelta(days=180)
            
            chart_df = fdr.DataReader(row['code'], start_date, end_date)
            
            if chart_df is not None and len(chart_df) > 0:
                # 이동평균선 계산
                chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
                chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
                
                # Plotly 차트 생성
                fig = go.Figure()
                
                # 캔들스틱
                fig.add_trace(go.Candlestick(
                    x=chart_df.index,
                    open=chart_df['Open'],
                    high=chart_df['High'],
                    low=chart_df['Low'],
                    close=chart_df['Close'],
                    name='가격'
                ))
                
                # 이동평균선
                fig.add_trace(go.Scatter(
                    x=chart_df.index,
                    y=chart_df['MA20'],
                    mode='lines',
                    name='MA20',
                    line=dict(color='orange', width=1)
                ))
                
                fig.add_trace(go.Scatter(
                    x=chart_df.index,
                    y=chart_df['MA60'],
                    mode='lines',
                    name='MA60',
                    line=dict(color='blue', width=1)
                ))
                
                # 손절가 라인 추가
                if 'stop' in row and pd.notna(row['stop']):
                    fig.add_hline(
                        y=row['stop'],
                        line_dash="dash",
                        line_color="red",
                        annotation_text=f"손절: {row['stop']:,.0f}원"
                    )
                
                # 레이아웃 설정
                fig.update_layout(
                    title=f"{row['name']} ({row['code']})",
                    yaxis_title="가격 (원)",
                    xaxis_title="날짜",
                    height=500,
                    xaxis_rangeslider_visible=False,
                    hovermode='x unified'
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
            else:
                st.warning("차트 데이터를 불러올 수 없습니다.")
                
        except Exception as e:
            st.error(f"차트 생성 중 에러: {e}")
            st.info("FinanceDataReader 설치가 필요할 수 있습니다.")
    
    else:
        st.error(f"종목 {selected_code}를 찾을 수 없습니다.")

else:
    st.info("👆 위 표에서 종목을 클릭하면 상세 차트와 분석 정보가 표시됩니다.")

# 푸터
st.markdown("---")
st.caption(f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 데이터: {filename}")
