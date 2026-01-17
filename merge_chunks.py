import os
import glob
import pandas as pd
from datetime import datetime

def main():
    scan_day = datetime.now().strftime("%Y-%m-%d")
    paths = sorted(glob.glob(f"data/partial/scanner_output_{scan_day}_chunk*.csv"))

    dfs = []
    for p in paths:
        try:
            df = pd.read_csv(p)
            if df is not None and not df.empty:
                dfs.append(df)
        except Exception:
            pass

    if not dfs:
        return

    out = pd.concat(dfs, ignore_index=True)

    if "code" in out.columns:
        out = out.drop_duplicates(subset=["code"], keep="first")

    out = out.sort_values("total_score", ascending=False)

    os.makedirs("data", exist_ok=True)
    out.to_csv(f"data/scanner_output_{scan_day}.csv", index=False, encoding="utf-8-sig")
    out.to_csv("data/scanner_output_latest.csv", index=False, encoding="utf-8-sig")

if __name__ == "__main__":
    main()
