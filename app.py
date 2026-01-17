import streamlit as st
import pandas as pd
import glob
import os
from datetime import datetime

st.set_page_config(layout="wide", page_title="추세추종 스캐너")

@st.cache_data(ttl=300)
def load_data():
    """
    data/ 폴더 내의 최신 결과 파일을 로드합니다.
    만약 합쳐진 파일이 없으면 data/partial/ 내의 chunk 파일들을 읽어 합칩니다.
    """
    # 1순위: 이미 합쳐진 최종 파일 찾기
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

    # 2순위: data/partial/ 내의 chunk 파일 찾기
    chunk_files = glob.glob("data/partial/scanner_output*chunk*.csv")
    
    if chunk_files:
        df_list = []
        for f in sorted(chunk_files):
            try:
                sub_df = pd.read_csv(f)
                df_list.append(sub_df)
            except Exception as e:
                st.warning(f"파일 읽기 실패: {f} - {e}")
                continue
        
        if df_list:
            final_df = pd.concat(df_list, ignore_index=True)
            if 'code' in final_df.columns:
                final_df.drop_duplicates(subset=['code'], keep='first', inplace=True)
            
            st.info(f"📦 Partial 파일 {len(df_list)}개를 합쳐서 표시합니다 (총 {len(final_df)}개 종목)")
            return final_df, f"Merged from {len(df_list)} chunks"

    return None, None

# 메인 앱 로직
st.title("🔍 추세추종 스캐너 (일봉/장마감)")

df, filename = load_data()

if df is None:
    st.error("❌ 결과 파일이 없습니다.")
    st.info("💡 GitHub Actions 실행 후 data/ 또는 data/partial/에 파일이 있어야 합니다.")
    st.stop()

st.success(f"✅ 데이터 로드 완료: {filename} (총 {len(df)}개 종목)")

# 점수 기준 내림차순 정렬
if 'total_score' in df.columns:
    df = df.sort_values(by='total_score', ascending=False).reset_index(drop=True)
else:
    st.error("total_score 컬럼이 없습니다. 데이터 형식을 확인해주세요.")
    st.stop()

# 필터링 및 테이블 표시
min_score = st.sidebar.slider("최소 점수", 0, 100, 50)
filtered_df = df[df['total_score'] >= min_score].copy()

st.subheader(f"🏆 상위 랭킹 종목 ({len(filtered_df)}개)")

# 표시할 컬럼 선택 (존재하는 컬럼만)
display_cols = ['rank', 'code', 'name', 'close', 'total_score', 'trend_score', 'vol_score']
display_cols = [col for col in display_cols if col in filtered_df.columns]

st.dataframe(
    filtered_df[display_cols],
    use_container_width=True,
    height=400
)

# 차트 상세 보기 (종목 선택)
if len(filtered_df) > 0:
    st.subheader("📈 종목 상세 분석")
    
    # 종목 코드를 직접 key로 사용하도록 수정
    stock_dict = {f"{row['name']} ({row['code']})": row['code'] 
                  for _, row in filtered_df.iterrows()}
    
    selected_display = st.selectbox("종목 선택", list(stock_dict.keys()))
    
    if selected_display:
        selected_code = stock_dict[selected_display]
        
        # 안전하게 종목 찾기
        try:
            matching = df[df['code'].astype(str) == str(selected_code)]
            
            if len(matching) == 0:
                st.error(f"❌ 종목 코드 '{selected_code}'를 데이터에서 찾을 수 없습니다.")
                st.info("💡 데이터가 업데이트되었을 수 있습니다. 페이지를 새로고침해주세요.")
            else:
                row = matching.iloc[0]
                
                # 메트릭 표시
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    close_val = row.get('close', 0)
                    st.metric("현재가", f"{close_val:,.0f}원" if close_val else "N/A")
                
                with col2:
                    total_val = row.get('total_score', 0)
                    st.metric("총점", f"{total_val:.0f}점" if total_val else "N/A")
                
                with col3:
                    trend_val = row.get('trend_score', 0)
                    st.metric("추세 점수", f"{trend_val:.0f}점" if trend_val else "N/A")
                
                # 추가 정보 표시
                st.markdown("### 📊 종목 상세 정보")
                info_cols = st.columns(2)
                
                with info_cols[0]:
                    if 'vol_score' in row and pd.notna(row['vol_score']):
                        st.write(f"**거래량 점수**: {row['vol_score']:.0f}점")
                    if 'rank' in row and pd.notna(row['rank']):
                        st.write(f"**순위**: {row['rank']}위")
                    if 'market' in row and pd.notna(row['market']):
                        st.write(f"**시장**: {row['market']}")
                
                with info_cols[1]:
                    if 'ma20' in row and pd.notna(row['ma20']):
                        st.write(f"**20일 이평선**: {row['ma20']:,.0f}원")
                    if 'ma60' in row and pd.notna(row['ma60']):
                        st.write(f"**60일 이평선**: {row['ma60']:,.0f}원")
                    if 'scan_date' in row and pd.notna(row['scan_date']):
                        st.write(f"**스캔 일시**: {row['scan_date']}")
                
                st.info(f"💡 선택된 종목: **{row['name']}** ({row['code']})")
                
        except Exception as e:
            st.error(f"❌ 종목 정보를 불러오는 중 에러가 발생했습니다: {e}")
            st.info("💡 Streamlit Cloud 관리 화면에서 로그를 확인해주세요.")
else:
    st.warning("⚠️ 조건에 맞는 종목이 없습니다. 필터를 조정해주세요.")

# 푸터
st.markdown("---")
st.caption(f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 데이터: {filename}")
