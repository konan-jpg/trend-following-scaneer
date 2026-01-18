import os
import time
import yaml
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from scanner_core import calculate_signals, score_stock
from news_analyzer import analyze_stock_news

def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_stock_list(cfg):
    try:
        kospi = fdr.StockListing("KOSPI")
        kosdaq = fdr.StockListing("KOSDAQ")
        stocks = pd.concat([kospi, kosdaq], ignore_index=True)
        stocks = stocks[~stocks["Name"].str.contains("우|스팩", na=False, regex=True)]
        if "Marcap" in stocks.columns:
            stocks = stocks[stocks["Marcap"] >= cfg["universe"]["min_mktcap_krw"]]
            stocks = stocks.sort_values("Marcap", ascending=False)
        os.makedirs("data", exist_ok=True)
        stocks.to_csv("data/krx_backup.csv", index=False, encoding="utf-8-sig")
        return stocks
    except Exception as e:
        print(f"종목 리스트 로드 실패: {e}")
        try:
            return pd.read_csv("data/krx_backup.csv")
        except Exception:
            return pd.DataFrame()

def get_investor_data(code, days=10):
    """외국인/기관 투자자 데이터 조회"""
    try:
        from pykrx import stock as pykrx
        
        end = datetime.now()
        start = end - timedelta(days=days + 10)
        
        df = pykrx.get_market_trading_value_by_date(
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            code
        )
        
        if df is None or len(df) == 0:
            return None
        
        df = df.tail(days)
        
        foreign_col = "외국인" if "외국인" in df.columns else df.columns[2] if len(df.columns) > 2 else None
        inst_col = "기관합계" if "기관합계" in df.columns else df.columns[1] if len(df.columns) > 1 else None
        
        if foreign_col is None:
            return None
        
        foreign_values = df[foreign_col].values
        
        consecutive_buy = 0
        for val in reversed(foreign_values):
            if val > 0:
                consecutive_buy += 1
            else:
                break
        
        foreign_net_5d = float(df[foreign_col].tail(5).sum()) if len(df) >= 5 else float(df[foreign_col].sum())
        inst_net_5d = float(df[inst_col].tail(5).sum()) if inst_col and len(df) >= 5 else 0
        
        return {
            "foreign_consecutive_buy": consecutive_buy,
            "foreign_net_buy_5d": foreign_net_5d,
            "inst_net_buy_5d": inst_net_5d,
        }
        
    except Exception as e:
        print(f"투자자 데이터 조회 실패 ({code}): {e}")
        return None

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
    
    print(f"🔍 Chunk {chunk}: {len(stocks)}개 종목 스캔 시작")
    
    # 1단계: 기술적 스캔
    print("\n📊 [1단계] 기술적 스캔...")
    tech_results = []
    end = datetime.now()
    start = end - timedelta(days=400)
    
    scanned_count = 0
    error_count = 0
    
    for idx, row in enumerate(stocks.itertuples(index=False), start=1):
        code = getattr(row, "Code", None)
        name = getattr(row, "Name", None)
        market = getattr(row, "Market", "")
        mktcap = getattr(row, "Marcap", None)
        
        if not code or not name:
            continue
        
        scanned_count += 1
        if scanned_count % 10 == 0:
            print(f"진행중: {scanned_count}/{len(stocks)} ({name})")
        
        try:
            df = fdr.DataReader(code, start, end)
            if df is None or len(df) < 200:
                continue
            
            if float(df["Volume"].tail(5).sum()) == 0:
                continue
            
            if float(df["Close"].iloc[-1]) < cfg["universe"]["min_close"]:
                continue
            
            sig = calculate_signals(df, cfg)
            scored = score_stock(df, sig, cfg, mktcap=mktcap)
            
            if scored is None:
                continue
            
            tech_results.append({
                "code": code,
                "name": name,
                "market": market,
                "mktcap": mktcap,
                **scored,
            })
            
            time.sleep(0.1)
            
        except Exception as e:
            error_count += 1
            if error_count <= 5:
                print(f"⚠️ {name} ({code}) 에러: {e}")
            continue
    
    print(f"\n📊 [1단계 완료] {len(tech_results)}개 통과")
    
    if not tech_results:
        print("⚠️ 조건에 맞는 종목이 없습니다.")
        scan_day = datetime.now().strftime("%Y-%m-%d")
        os.makedirs("data/partial", exist_ok=True)
        output_file = f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv"
        empty_df = pd.DataFrame(columns=[
            "rank", "code", "name", "market", "close", "total_score", 
            "trend_score", "pattern_score", "volume_score", "supply_score", "risk_score",
            "setup", "ma20", "ma60", "scan_date", "chunk"
        ])
        empty_df.to_csv(output_file, index=False, encoding="utf-8-sig")
        return
    
    tech_df = pd.DataFrame(tech_results).sort_values("total_score", ascending=False)
    
    # 2단계: 수급 데이터 조회
    top_candidates = cfg.get("investor", {}).get("top_candidates", 100)
    candidates = tech_df.head(top_candidates)
    
    print(f"\n💰 [2단계] 상위 {len(candidates)}개 수급 조회...")
    
    final_results = []
    for idx, row in candidates.iterrows():
        code = row["code"]
        name = row["name"]
        
        investor_data = get_investor_data(code)
        
        if investor_data:
            supply_score = 0
            supply_w = cfg.get("scoring", {}).get("supply_weight", 15)
            
            foreign_consec = investor_data.get("foreign_consecutive_buy", 0)
            if foreign_consec >= 5:
                supply_score += 8
            elif foreign_consec >= 3:
                supply_score += 5
            elif foreign_consec >= 1:
                supply_score += 2
            
            if investor_data.get("inst_net_buy_5d", 0) > 0:
                supply_score += 4
            if investor_data.get("foreign_net_buy_5d", 0) > 0:
                supply_score += 3
            
            supply_score = min(supply_score, supply_w)
            
            new_total = row["trend_score"] + row["pattern_score"] + row["volume_score"] + supply_score + row["risk_score"]
            
            result = row.to_dict()
            result["supply_score"] = supply_score
            result["total_score"] = new_total
            result["foreign_consec_buy"] = foreign_consec
            result["foreign_net_5d"] = investor_data.get("foreign_net_buy_5d", 0)
            result["inst_net_5d"] = investor_data.get("inst_net_buy_5d", 0)
        else:
            result = row.to_dict()
            result["foreign_consec_buy"] = 0
            result["foreign_net_5d"] = 0
            result["inst_net_5d"] = 0
        
        news = analyze_stock_news(name, cfg)
        result.update(news)
        result["scan_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        result["chunk"] = chunk
        
        final_results.append(result)
        
        print(f"✅ {name}: {result['total_score']:.0f}점")
        
        time.sleep(0.2)
    
    print(f"\n📊 [완료] {len(final_results)}개 종목")
    
    scan_day = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("data/partial", exist_ok=True)
    output_file = f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv"
    
    out = pd.DataFrame(final_results).sort_values("total_score", ascending=False)
    out.insert(0, "rank", range(1, len(out) + 1))
    out.to_csv(output_file, index=False, encoding="utf-8-sig")
    
    print(f"✅ 저장: {output_file}")

if __name__ == "__main__":
    main()
