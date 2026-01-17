import os
import requests
from sklearn.feature_extraction.text import TfidfVectorizer

def search_naver_news(query, client_id, client_secret, display=10):
    if not client_id or not client_secret:
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {"query": query, "display": display, "sort": "date"}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=5)
        if r.status_code != 200:
            return []
        items = r.json().get("items", [])
        cleaned = []
        for it in items:
            cleaned.append({
                "title": it.get("title","").replace("<b>","").replace("</b>",""),
                "description": it.get("description","").replace("<b>","").replace("</b>",""),
                "link": it.get("link",""),
                "pubDate": it.get("pubDate",""),
            })
        return cleaned
    except Exception:
        return []

def extract_keywords(texts, topk=8):
    if not texts:
        return []
    if all(not str(t).strip() for t in texts):
        return []
    try:
        vec = TfidfVectorizer(max_features=1000, ngram_range=(1,2))
        X = vec.fit_transform(texts)
        scores = X.sum(axis=0).A1
        terms = vec.get_feature_names_out()
        top_idx = scores.argsort()[::-1][:topk]
        return [terms[i] for i in top_idx]
    except Exception:
        return []

def analyze_stock_news(stock_name, cfg):
    client_id = os.environ.get("NAVER_CLIENT_ID") or cfg["news"].get("naver_client_id","")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET") or cfg["news"].get("naver_client_secret","")

    news = search_naver_news(stock_name, client_id, client_secret, display=10)
    if not news:
        return {"keywords": "", "news_count": 0}

    texts = [n["title"] + " " + n["description"] for n in news]
    keywords = extract_keywords(texts, topk=cfg["news"]["max_keywords"])
    return {"keywords": ", ".join(keywords[:6]), "news_count": len(news)}
