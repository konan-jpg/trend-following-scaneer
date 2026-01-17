import os
import time
import yaml
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta

def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_stock_list(cfg):
    try:
        kospi = fdr.StockListing("KOSPI")
        kosdaq = fdr.StockListing("KOSDAQ")
        stocks = pd.concat([kospi, kosdaq], ignore_index=True)
        
        print(f"📊 전체 종목 수: {len(stocks)}")
        
        # 우선주/스팩 제외
        stocks = stocks[~stocks["Name"].str.contains("우|스팩", na=False, regex=True)]
        print(f"📊 우선주/스팩 제외 후: {len(stocks)}")
        
        if "Marcap" in stocks.columns:
            min_mktcap = cfg["universe"]["min_mktcap_krw"]
            print(f"📊 시총 필터 기준: {min_mktcap:,}원")
            stocks = stocks[stocks["Marcap"] >= min_mktcap]
            print(f"📊 시총 필터 후: {len(stocks)}")
            stocks = stocks.sort_values("Marcap", ascending=False)
        
        os.makedirs("data", exist_ok=True)
        stocks.to_csv("data/krx_backup.csv", index=False, encoding="utf-8-sig")
        return stocks
    except Exception as e:
        print(f"❌ 종목 리스트 로드 실패: {e}")
        import traceback
        traceback.print_exc()
        try:
            return pd.read_csv("data/krx_backup.csv")
        except Exception:
            return pd.DataFrame()

def main():
    cfg = load_config()
    stocks = get_stock_list(cfg)
    
    if stocks.empty:
        print("❌ 종목 리스트가 비어있습니다")
        return
    
    top_n = int(cfg["universe"]["top_n_stocks"])
    chunk_size = int(cfg["universe"]["chunk_size"])
    chunk = int(os.environ.get("SCAN_CHUNK", "1"))
    
    stocks = stocks.head(top_n)
    start_i = (chunk - 1) * chunk_size
    end_i = chunk * chunk_size
    stocks = stocks.iloc[start_i:end_i]
    
    print(f"\n🔍 Chunk {chunk}: {len(stocks)}개 종목 스캔 시작 (인덱스 {start_i}~{end_i})")
    print(f"🔍 첫 5개 종목: {stocks['Name'].head().tolist()}")
    
    results = []
    end = datetime.now()
    start = end - timedelta(days=400)  # 260 → 400으로 변경 (거래일 기준 약 280일)
    
    scanned_count = 0
    error_count = 0
    skip_reasons = {
        "no_data": 0,
        "short_history": 0,
        "no_volume": 0,
        "low_price": 0,
        "ma_fail": 0,
    }
    
    min_close = cfg["universe"]["min_close"]
    print(f"🔍 주가 필터 기준: {min_close:,}원\n")
    
    for idx, row in enumerate(stocks.itertuples(index=False), start=1):
        code = getattr(row, "Code", None)
        name = getattr(row, "Name", None)
        market = getattr(row, "Market", "")
        
        if not code or not name:
            continue
        
        scanned_count += 1
        
        try:
            df = fdr.DataReader(code, start, end)
            
            if df is None or len(df) == 0:
                skip_reasons["no_data"] += 1
                if scanned_count <= 10:
                    print(f"⏭️ {name} ({code}): 데이터 없음")
                continue
            
            if len(df) < 200:
                skip_reasons["short_history"] += 1
                if scanned_count <= 10:
                    print(f"⏭️ {name} ({code}): 히스토리 부족 ({len(df)}일, 필요: 200일)")
                continue
            
            if float(df["Volume"].tail(5).sum()) == 0:
                skip_reasons["no_volume"] += 1
                if scanned_count <= 10:
                    print(f"⏭️ {name} ({code}): 거래량 없음")
                continue
            
            close_price = float(df["Close"].iloc[-1])
            if close_price < min_close:
                skip_reasons["low_price"] += 1
                if scanned_count <= 10:
                    print(f"⏭️ {name} ({code}): 주가 {close_price:,}원 (기준: {min_close:,}원)")
                continue
            
            # 이동평균 계산
            try:
                ma20 = df['Close'].rolling(20).mean().iloc[-1]
                ma60 = df['Close'].rolling(60).mean().iloc[-1]
            except Exception as e:
                skip_reasons["ma_fail"] += 1
                if scanned_count <= 10:
                    print(f"⚠️ {name} ({code}): 이평 계산 실패 - {e}")
                continue
            
            # 거래량
            vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1]
            recent_vol = df['Volume'].tail(5).mean()
            
            # ⭐ 모든 종목을 일단 추가 (필터 없음)
            trend_score = 50 if ma20 > ma60 else 20
            vol_score = 30 if recent_vol > vol_ma20 * 1.2 else 10
            total_score = trend_score + vol_score
            
            results.append({
                "code": code,
                "name": name,
                "market": market,
                "close": round(close_price, 0),
                "ma20": round(ma20, 0),
                "ma60": round(ma60, 0),
                "trend_score": trend_score,
                "vol_score": vol_score,
                "total_score": total_score,
                "momentum_score": 0,
                "news_score": 0,
                "news_summary": "",
                "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "chunk": chunk,
            })
            
            if len(results) <= 10:
                print(f"✅ {name} ({code}): 주가 {close_price:,.0f}원, 점수 {total_score}점")
            
            time.sleep(0.05)  # 속도 향상
            
        except Exception as e:
            error_count += 1
            if error_count <= 10:
                print(f"❌ {name} ({code}) 에러: {e}")
                import traceback
                if error_count <= 3:
                    traceback.print_exc()
            continue
    
    print(f"\n{'='*60}")
    print(f"📊 스캔 완료 통계")
    print(f"{'='*60}")
    print(f"총 검토: {scanned_count}개")
    print(f"조건 충족: {len(results)}개")
    print(f"에러: {error_count}개")
    print(f"\n제외 사유:")
    for reason, count in skip_reasons.items():
        print(f"  - {reason}: {count}개")
    print(f"{'='*60}\n")
    
    scan_day = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("data/partial", exist_ok=True)
    output_file = f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv"
    
    if not results:
        print("⚠️ 조건에 맞는 종목이 없습니다. 빈 파일(헤더만) 생성합니다.")
        empty_df = pd.DataFrame(columns=[
            "rank", "code", "name", "market", "close", "total_score", 
            "trend_score", "vol_score", "momentum_score", "ma20", "ma60",
            "news_score", "news_summary", "scan_date", "chunk"
        ])
        empty_df.to_csv(output_file, index=False, encoding="utf-8-sig")
        return
    
    out = pd.DataFrame(results).sort_values("total_score", ascending=False)
    out.insert(0, "rank", range(1, len(out) + 1))
    out.to_csv(output_file, index=False, encoding="utf-8-sig")
    
    print(f"✅ 결과 저장 완료: {output_file}")
    print(f"✅ 상위 10개 종목:")
    for i, row in out.head(10).iterrows():
        print(f"   {row['rank']}. {row['name']} ({row['code']}): {row['total_score']}점")

if __name__ == "__main__":
    main()
