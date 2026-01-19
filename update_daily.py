# -*- coding: utf-8 -*-
"""
update_daily.py - V2 호환 (수급 점수 제거, 안전 장치 강화)
"""
import os
import time
import yaml
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from scanner_core import calculate_signals, score_stock
# news_analyzer 제거 (불안정 요소 배제)

def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_stock_list(cfg):
    try:
        kospi = fdr.StockListing("KOSPI")
        kosdaq = fdr.StockListing("KOSDAQ")
        stocks = pd.concat([kospi, kosdaq], ignore_index=True)
        stocks = stocks[~stocks["Name"].str.contains("우|스팩", na=False, regex=True)]
        
        # 시총 필터
        if "Marcap" in stocks.columns:
            stocks = stocks[stocks["Marcap"] >= cfg["universe"]["min_mktcap_krw"]]
            stocks = stocks.sort_values("Marcap", ascending=False)
        
        stocks["Code"] = stocks["Code"].astype(str).str.zfill(6)
        
        # 백업 저장 (app.py 안전모드용)
        os.makedirs("data", exist_ok=True)
        stocks.to_csv("data/krx_tickers.csv", index=False, encoding="utf-8-sig")
        return stocks
    except Exception as e:
        print(f"[ERR] 종목 리스트 로드 실패: {e}")
        return pd.DataFrame()

def calculate_sector_rankings(stocks, top_n=500):
    # (기존 섹터 로직 유지 - 생략 가능하나 안전을 위해 포함)
    try:
        universe = stocks.head(top_n).copy()
        sector_results = []
        end = datetime.now()
        start = end - timedelta(days=90)
        
        if "Sector" not in universe.columns: return

        for sector, group in universe.groupby("Sector"):
            if len(group) < 3: continue
            returns = []
            for _, row in group.head(5).iterrows():
                try:
                    df = fdr.DataReader(row["Code"], start, end)
                    if df is not None and len(df) > 20:
                        ret = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
                        returns.append(ret)
                except: continue
            
            if returns:
                sector_results.append({
                    "Sector": sector,
                    "AvgReturn_3M": sum(returns)/len(returns),
                    "StockCount": len(group)
                })
        
        if sector_results:
            rank_df = pd.DataFrame(sector_results).sort_values("AvgReturn_3M", ascending=False)
            rank_df.to_csv("data/sector_rankings.csv", index=False, encoding="utf-8-sig")
    except: pass

def main():
    cfg = load_config()
    stocks = get_stock_list(cfg)
    
    if stocks.empty: return
    
    # 설정 로드
    top_n = int(cfg["universe"]["top_n_stocks"])
    chunk_size = int(cfg["universe"]["chunk_size"])
    chunk = int(os.environ.get("SCAN_CHUNK", "1"))
    
    # 청크 분할
    targets = stocks.head(top_n)
    start_i = (chunk - 1) * chunk_size
    end_i = chunk * chunk_size
    chunk_stocks = targets.iloc[start_i:end_i]
    
    if chunk == 1:
        calculate_sector_rankings(stocks)
    
    results = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=400) # 넉넉하게
    
    print(f"[SCAN] Chunk {chunk} ({len(chunk_stocks)}개) 시작...")
    
    for idx, row in enumerate(chunk_stocks.itertuples(), 1):
        code = str(getattr(row, "Code", "")).zfill(6)
        name = getattr(row, "Name", "")
        market = getattr(row, "Market", "KRX")
        sector = getattr(row, "Sector", "")
        
        if idx % 50 == 0: print(f"  {idx}/{len(chunk_stocks)}...")
        
        try:
            df = fdr.DataReader(code, start_date, end_date)
            if df is None or len(df) < 120: continue
            
            # [핵심] VCP 100점 로직 호출 (수급 데이터 없이 호출)
            # score_stock 함수가 내부적으로 Trend/Pattern/Volume/Memory 계산
            scores = score_stock(df, mode="daily")
            
            if scores:
                # 결과 저장
                data = {
                    "code": code,
                    "name": name,
                    "market": market,
                    "sector": sector,
                    "score": scores['score'],  # 총점
                    "close": scores['close'],
                    "trend_score": scores.get('trend_score', 0),
                    "pattern_score": scores.get('pattern_score', 0), # =Location
                    "volume_score": scores.get('volume_score', 0),
                    "memory_score": scores.get('memory_score', 0), # 새로 추가된 점수
                    "tags": scores.get('tags', '-'),
                    "scan_date": datetime.now().strftime("%Y-%m-%d")
                }
                
                # 최소 점수 컷 (너무 낮은건 저장 안함 - 파일 크기 절약)
                if data['score'] >= 10:
                    results.append(data)
                    print(f"  [OK] {name}: {data['score']:.0f}점 {data['tags']}")
            
            time.sleep(0.1) # 서버 부하 방지
            
        except Exception as e:
            continue
            
    # 저장
    scan_day = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("data/partial", exist_ok=True)
    
    if results:
        df_res = pd.DataFrame(results).sort_values("score", ascending=False)
        output_file = f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv"
        df_res.to_csv(output_file, index=False, encoding="utf-8-sig")
        print(f"[완료] {len(df_res)}개 저장됨 -> {output_file}")
    else:
        print("[알림] 조건 만족 종목 없음")

if __name__ == "__main__":
    main()
