#!/usr/bin/env python3
"""
인도 펀드 대시보드 업데이터
- NIFTY50 데이터를 Yahoo Finance에서 자동으로 가져옴
- 대시보드 HTML을 최신 데이터로 업데이트
"""

import json
import re
import os
import sys
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime

# 필요한 라이브러리 자동 설치
def install(pkg):
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])

try:
    import yfinance as yf
except ImportError:
    print("yfinance 설치 중...")
    install('yfinance')
    import yfinance as yf

# ── 설정 파일 로드 ──────────────────────────────────────────────
CONFIG_FILE = os.path.join(os.path.dirname(__file__), '설정.json')

def load_config():
    default = {
        "매수단가": 797.6,
        "투자금_만원": 1400,
        "추가투자_만원": 2800,
        "손절기준가": 718,
        "anthropic_api_key": ""
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        default.update(saved)
    else:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
        print(f"설정 파일 생성됨: {CONFIG_FILE}")
        print("AI 질문 기능을 쓰려면 설정.json 에 anthropic_api_key 를 입력해주세요.\n")
    return default

# ── 펀드 기준가 자동 가져오기 (공공데이터포털) ──────────────────────
def fetch_fund_nav(api_key, days=90):
    """
    공공데이터포털 '금융위원회_펀드공시정보' API로 기준가 이력 가져오기
    https://www.data.go.kr → 금융위원회_펀드공시정보 → getFundPriceInfo
    """
    import urllib.parse
    from datetime import datetime, timedelta

    end_dt   = datetime.today()
    start_dt = end_dt - timedelta(days=days)

    # 1단계: 펀드 코드 검색 (최초 1회)
    def find_fund_code():
        params = urllib.parse.urlencode({
            "serviceKey": api_key,
            "numOfRows": "10",
            "pageNo": "1",
            "resultType": "json",
            "FND_NM": "KB스타 NIFTY50",
        })
        url = f"https://apis.data.go.kr/1160100/service/GetFundInfoService/getFundList?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        # (H) S 포함된 펀드 코드 우선
        for item in items:
            name = item.get("fndNm", "")
            if "NIFTY50" in name and "(H)" in name:
                return item.get("fndCd", "")
        return items[0].get("fndCd", "") if items else None

    # 2단계: 기준가 이력 가져오기
    def fetch_prices(fund_code):
        params = urllib.parse.urlencode({
            "serviceKey": api_key,
            "numOfRows": "100",
            "pageNo": "1",
            "resultType": "json",
            "FND_CD": fund_code,
            "START_DT": start_dt.strftime("%Y%m%d"),
            "END_DT": end_dt.strftime("%Y%m%d"),
        })
        url = f"https://apis.data.go.kr/1160100/service/GetFundInfoService/getFundPriceInfo?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        result = []
        for item in items:
            date_str = str(item.get("standardDt", ""))  # YYYYMMDD
            nav = float(item.get("standardCo", 0))
            if date_str and nav:
                label = f"{date_str[4:6]}.{date_str[6:8]}"
                result.append({"날짜": label, "기준가": nav})
        # 최신순 정렬
        result.sort(key=lambda x: x["날짜"], reverse=True)
        return result

    try:
        print("펀드 기준가 데이터 가져오는 중...")
        fund_code = find_fund_code()
        if not fund_code:
            print("  펀드 코드를 찾지 못했습니다.")
            return None
        history = fetch_prices(fund_code)
        print(f"  기준가 이력 {len(history)}건 가져옴 (최신: {history[0]['날짜']} {history[0]['기준가']})")
        return history
    except Exception as e:
        print(f"  기준가 자동 가져오기 실패: {e}")
        return None

# ── NIFTY50 데이터 가져오기 ──────────────────────────────────────
def fetch_period(ticker, period, interval, fmt):
    h = ticker.history(period=period, interval=interval)
    labels, prices = [], []
    for date, row in h.iterrows():
        labels.append(date.strftime(fmt))
        prices.append(int(row['Close']))
    return labels, prices

def fetch_index(symbol, name, fallback):
    print(f"{name} 데이터 가져오는 중...")
    ticker = yf.Ticker(symbol)

    d1_h = ticker.history(period="1d", interval="5m")
    d1_labels = [d.strftime("%H:%M") for d in d1_h.index]
    d1_prices = [int(r['Close']) for _, r in d1_h.iterrows()]

    d5_labels, d5_prices   = fetch_period(ticker, "5d",  "1d",  "%-m/%-d")
    d30_labels, d30_prices = fetch_period(ticker, "1mo", "1d",  "%-m/%-d")
    mo3_labels, mo3_prices = fetch_period(ticker, "3mo", "1wk", "%-m/%-d")
    mo6_labels, mo6_prices = fetch_period(ticker, "6mo", "1wk", "%-m/%-d")
    yr1_labels, yr1_prices = fetch_period(ticker, "1y",  "1wk", "%-m/%-d")

    today_h = ticker.history(period="1d", interval="1d")
    if not today_h.empty:
        row = today_h.iloc[-1]
        open_p, high_p, low_p = int(row['Open']), int(row['High']), int(row['Low'])
        today_close = int(row['Close'])
        today_label = today_h.index[-1].strftime("%-m/%-d")
    else:
        open_p = high_p = low_p = today_close = 0
        today_label = ""

    try:
        fi = ticker.fast_info
        current = int(fi.last_price) if fi.last_price else today_close
    except Exception:
        current = today_close if today_close else (d1_prices[-1] if d1_prices else fallback)

    prev_close = d5_prices[-2] if len(d5_prices) >= 2 else current
    change_val = current - prev_close
    change_pct = round(change_val / prev_close * 100, 2)

    for lbl_list, prc_list in [(mo6_labels, mo6_prices), (yr1_labels, yr1_prices)]:
        if today_label and lbl_list and today_label != lbl_list[-1]:
            lbl_list.append(today_label)
            prc_list.append(current)

    return {
        "current": current, "change_val": change_val, "change_pct": change_pct,
        "open": open_p, "high": high_p, "low": low_p,
        "d1":  {"labels": d1_labels,  "prices": d1_prices},
        "d5":  {"labels": d5_labels,  "prices": d5_prices},
        "d30": {"labels": d30_labels, "prices": d30_prices},
        "mo3": {"labels": mo3_labels, "prices": mo3_prices},
        "mo6": {"labels": mo6_labels, "prices": mo6_prices},
        "yr1": {"labels": yr1_labels, "prices": yr1_prices},
        "labels": yr1_labels,
        "prices": yr1_prices,
    }

def fetch_nifty():
    return fetch_index("^NSEI", "NIFTY50", 23622)

def fetch_sensex():
    return fetch_index("^BSESN", "SENSEX", 77000)

# ── 매크로 지표 자동 가져오기 ───────────────────────────────────────
def fetch_macro_signals():
    """USD/INR, VIX, 브렌트유, NIFTY P/E를 야후 파이낸스에서 실시간으로 가져옴"""
    result = {"usdinr": None, "vix": None, "india_vix": None, "crude": None, "nifty_pe": None}
    try:
        result["usdinr"] = round(yf.Ticker("USDINR=X").fast_info.last_price, 2)
        print(f"  USD/INR: ₹{result['usdinr']}")
    except Exception as e:
        print(f"  USD/INR 가져오기 실패: {e}")
    try:
        result["vix"] = round(yf.Ticker("^VIX").fast_info.last_price, 2)
        print(f"  VIX(미국): {result['vix']}")
    except Exception as e:
        print(f"  VIX 가져오기 실패: {e}")
    try:
        result["india_vix"] = round(yf.Ticker("^INDIAVIX").fast_info.last_price, 2)
        print(f"  India VIX: {result['india_vix']}")
    except Exception as e:
        print(f"  India VIX 가져오기 실패: {e}")
    try:
        result["crude"] = round(yf.Ticker("BZ=F").fast_info.last_price, 1)
        print(f"  브렌트유: ${result['crude']}")
    except Exception as e:
        print(f"  브렌트유 가져오기 실패: {e}")
    try:
        from datetime import timedelta
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        # NSE 아카이브 CSV — 최근 5일 중 가장 최신 파일 시도
        for delta in range(6):
            d = datetime.now().date() - timedelta(days=delta)
            date_str = d.strftime("%d%m%Y")
            url = f"https://archives.nseindia.com/content/indices/ind_close_all_{date_str}.csv"
            try:
                req_csv = urllib.request.Request(url, headers={"User-Agent": ua})
                with urllib.request.urlopen(req_csv, timeout=8) as r:
                    content = r.read().decode("utf-8", errors="ignore")
                header = content.split("\n")[0].split(",")
                pe_col = next((i for i, h in enumerate(header) if "P/E" in h.upper()), None)
                if pe_col is None:
                    break
                for line in content.split("\n")[1:]:
                    parts = line.split(",")
                    if len(parts) > pe_col and "Nifty 50" in parts[0]:
                        pe_val = parts[pe_col].strip()
                        if pe_val:
                            result["nifty_pe"] = round(float(pe_val), 1)
                            print(f"  NIFTY P/E: {result['nifty_pe']} ({d})")
                        break
                if result["nifty_pe"]:
                    break
            except Exception:
                continue
    except Exception as e:
        print(f"  NIFTY P/E 가져오기 실패: {e}")

    # 몬순 시즌 여부 (매년 6월~9월)
    month = datetime.now().month
    result["monsoon"] = 6 <= month <= 9

    return result

# ── 뉴스 헤드라인 수집 ──────────────────────────────────────────────
def _fetch_google_rss(query, n=5):
    import urllib.parse, xml.etree.ElementTree as ET
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            tree = ET.parse(r)
        items = tree.getroot().findall('.//item')[:n]
        out = []
        for item in items:
            title = item.findtext('title', '').split(' - ')[0].strip()
            date  = item.findtext('pubDate', '')[:16]
            out.append(f"[{date}] {title}")
        return out
    except:
        return []

def _fetch_newsapi(query, key, n=5):
    import urllib.parse
    params = urllib.parse.urlencode({
        "q": query, "apiKey": key,
        "language": "en", "sortBy": "publishedAt", "pageSize": n,
    })
    url = f"https://newsapi.org/v2/everything?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        out = []
        for a in data.get("articles", []):
            date  = a.get("publishedAt", "")[:10]
            title = a.get("title", "")
            out.append(f"[{date}] {title}")
        return out
    except:
        return []

def _fetch_fed_rate():
    """FRED에서 미국 기준금리 가져오기 (API 키 불필요)"""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            lines = r.read().decode().strip().split('\n')
        last = lines[-1].split(',')
        return float(last[1]), last[0]  # (rate, date)
    except:
        return None, None

# ── 뉴스 신호 AI 판단 ────────────────────────────────────────────────
TOPICS = [
    {"key": "FII",    "label": "FII 자금 흐름",   "rss": "India FII foreign investors flow buy sell",   "api": "India FII investment flow"},
    {"key": "DII",    "label": "DII 자금 흐름",   "rss": "India DII domestic institutional investors",   "api": "India DII domestic investors buy sell"},
    {"key": "RBI",    "label": "RBI 금리",         "rss": "RBI India central bank interest rate policy", "api": "RBI rate hike cut hold"},
    {"key": "mideast","label": "중동 정세",         "rss": "Middle East conflict war oil geopolitics",    "api": "Middle East war conflict ceasefire"},
    {"key": "trade",  "label": "미-인도 무역",      "rss": "India US trade deal tariff agreement",        "api": "India United States trade agreement tariff"},
    {"key": "cpi",    "label": "인도 CPI",          "rss": "India CPI inflation consumer price index",    "api": "India inflation CPI data"},
    {"key": "pmi",    "label": "인도 PMI",          "rss": "India PMI manufacturing services index",      "api": "India PMI purchasing managers index"},
    {"key": "fed",    "label": "미국 연준",          "rss": "Federal Reserve interest rate FOMC decision", "api": "Federal Reserve rate policy FOMC"},
]

def fetch_news_signals(claude_api_key, newsapi_key=None):
    """Google RSS + NewsAPI 헤드라인을 모아 Claude에게 신호 판단 요청"""
    print("뉴스 헤드라인 수집 중...")

    # 연준 금리는 FRED에서 정확한 수치로 먼저 가져옴
    fed_rate, fed_date = _fetch_fed_rate()
    if fed_rate:
        print(f"  연준 기준금리: {fed_rate}% ({fed_date})")

    # 각 토픽별 헤드라인 수집
    all_headlines = {}
    for t in TOPICS:
        lines = _fetch_google_rss(t["rss"], n=4)
        if newsapi_key:
            lines += _fetch_newsapi(t["api"], newsapi_key, n=4)
        # 중복 제거 후 최대 6개
        seen, uniq = set(), []
        for l in lines:
            key = l[18:].lower()[:40]
            if key not in seen:
                seen.add(key)
                uniq.append(l)
        all_headlines[t["key"]] = {"label": t["label"], "headlines": uniq[:6]}
        print(f"  {t['label']}: {len(uniq[:6])}개 헤드라인")

    if not claude_api_key:
        # Claude 없으면 헤드라인만 반환
        return {k: {"badge": "badge-b", "text": "뉴스 수집됨 (AI 분석 없음)", "headlines": v["headlines"]}
                for k, v in all_headlines.items()}

    # Claude에게 일괄 판단 요청
    print("Claude AI 뉴스 분석 중...")
    fed_note = f"\n* 연준 기준금리 실제값(FRED): {fed_rate}% ({fed_date})" if fed_rate else ""

    news_block = ""
    for t in TOPICS:
        k = t["key"]
        label = t["label"]
        headlines = all_headlines[k]["headlines"]
        news_block += f"[{label}]\n"
        if headlines:
            news_block += "\n".join(f"• {h}" for h in headlines)
        else:
            news_block += "• (헤드라인 없음)"
        news_block += "\n\n"

    prompt = f"""오늘은 {datetime.now().strftime('%Y년 %m월 %d일')}입니다.{fed_note}

아래는 각 주제별 최신 뉴스 헤드라인입니다. 인도 주식 펀드 투자자 관점에서 각 항목을 판단해주세요.

{news_block}
각 항목마다 다음 JSON으로만 답하세요 (다른 텍스트 없이):
{{
  "FII":     {{"badge": "g/y/r/b", "text": "한국어 12자 이내 핵심 요약"}},
  "DII":     {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "RBI":     {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "mideast": {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "trade":   {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "cpi":     {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "pmi":     {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}},
  "fed":     {{"badge": "g/y/r/b", "text": "한국어 12자 이내"}}
}}

badge 기준: g=호재(초록), y=중립/주의(노랑), r=악재(빨강), b=정보(파랑)"""

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={"Content-Type": "application/json",
                 "x-api-key": claude_api_key,
                 "anthropic-version": "2023-06-01"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read())
        raw = resp["content"][0]["text"].strip()
        # JSON 블록만 추출
        m = re.search(r'\{[\s\S]+\}', raw)
        judgments = json.loads(m.group()) if m else {}
    except Exception as e:
        print(f"  Claude 분석 실패: {e}")
        judgments = {}

    result = {}
    badge_map = {"g": "badge-g", "y": "badge-y", "r": "badge-r", "b": "badge-b"}
    for t in TOPICS:
        k = t["key"]
        j = judgments.get(k, {})
        badge_raw = j.get("badge", "b")
        result[k] = {
            "badge": badge_map.get(badge_raw, "badge-b"),
            "text":  j.get("text", "분석 중"),
            "headlines": all_headlines[k]["headlines"],
        }
    # 연준은 실제 금리 수치도 함께
    if fed_rate and "fed" in result:
        result["fed"]["rate"] = fed_rate

    return result

# ── 액션 가이드 AI 생성 ──────────────────────────────────────────────
def generate_action_guide(nifty, metrics, indicators, macro, news, claude_api_key, events=None):
    if not claude_api_key:
        return None

    ind = indicators or {}
    mac = macro or {}
    nws = news or {}

    # 뉴스 신호 요약
    news_summary = ""
    label_map = {"FII":"FII 자금흐름","RBI":"RBI 금리","mideast":"중동 정세",
                 "trade":"미-인도 무역","cpi":"인도 CPI","fed":"미국 연준"}
    for k, lbl in label_map.items():
        n = nws.get(k, {})
        news_summary += f"- {lbl}: {n.get('text','정보없음')} (판단: {n.get('badge','').replace('badge-','')})\n"

    # 다가오는 이벤트 정리
    events_note = ""
    if events:
        from datetime import date as _date
        today = _date.today()
        upcoming = []
        for ev in sorted(events, key=lambda x: x["날짜"]):
            try:
                diff = (_date.fromisoformat(ev["날짜"]) - today).days
                if 0 <= diff <= 30:
                    upcoming.append(f"D-{diff}: {ev['내용']}")
            except Exception:
                pass
        if upcoming:
            events_note = "\n[30일 내 주요 이벤트]\n" + "\n".join(f"- {e}" for e in upcoming)

    prompt = f"""당신은 인도 주식 펀드 전문 매니저입니다. 아래 현재 지표를 보고 액션 가이드를 작성해주세요.

[포트폴리오]
- 펀드: KB스타 NIFTY50 인덱스 (H) S
- 매수단가: {metrics['buy_price']}원 / 현재 기준가: {metrics['current_price']:.2f}원
- 현재 손익: {metrics['pnl_pct']:+}% ({metrics['pnl_amount']:+}만원)
- 투자금: {metrics['invest_man']}만원 / 추가 투자 예정: {metrics['add_invest_man']}만원
- 손절 기준가: {metrics['sl_price']}원 (현재까지 {metrics['sl_gap']}%)

[기술적 지표]
- NIFTY50: {nifty['current']:,} ({nifty['change_pct']:+}%)
- RSI(14주): {ind.get('rsi','?')} / 이평 배열: {ind.get('ma_signal','?')}
- 4주 모멘텀: {ind.get('momentum',0):+}% / 변동성: ±{ind.get('vol',0)}%
- 52주 고점 대비: {ind.get('from_high',0)}% / 저점 대비: +{ind.get('from_low',0)}%

[매크로]
- USD/INR: ₹{mac.get('usdinr','?')} / VIX: {mac.get('vix','?')} / 브렌트유: ${mac.get('crude','?')}

[뉴스 신호]
{news_summary}{events_note}
JSON으로만 답하세요. 각 desc는 1문장씩:
{{"now":{{"action":"보유유지","type":"hold","title":"📌 지금 — [한 마디]","desc":"[현황 요약]"}},"buy1":{{"title":"🟢 1차 매수 조건","desc":"[조건+금액]"}},"buy2":{{"title":"🟢 2차 매수 조건","desc":"[조건+금액]"}},"sell":{{"title":"🔴 손절 조건","desc":"[트리거]"}}}}"""

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 900,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={"Content-Type": "application/json",
                 "x-api-key": claude_api_key,
                 "anthropic-version": "2023-06-01"}
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            resp = json.loads(r.read())
        raw = resp["content"][0]["text"].strip()
        raw = re.sub(r'```json\s*', '', raw)
        raw = re.sub(r'```\s*', '', raw)
        raw = re.sub(r',\s*([}\]])', r'\1', raw)
        m = re.search(r'\{[\s\S]+\}', raw)
        return json.loads(m.group()) if m else None
    except Exception as e:
        print(f"  액션 가이드 생성 실패: {e}")
        return None

# ── 손익 계산 ───────────────────────────────────────────────────
def calc_metrics(cfg, nifty_current):
    # 현재 기준가 = 매수단가 × (NIFTY50현재/NIFTY50매수시점)
    # 정확한 기준가는 매일 직접 입력이 필요하지만, 근사치로 계산
    buy_price = cfg["매수단가"]
    sl_price = cfg["손절기준가"]

    # 현재 기준가는 설정에 있으면 그걸 쓰고, 없으면 NIFTY50 비율로 추정
    current_price = cfg.get("현재기준가", None)
    if current_price is None:
        # NIFTY50 매수 시점 지수 (2024년말 기준 약 24,200 근사)
        nifty_at_buy = cfg.get("NIFTY50_매수시점", 24200)
        current_price = round(buy_price * (nifty_current / nifty_at_buy), 2)

    pnl_pct = round((current_price - buy_price) / buy_price * 100, 2)
    pnl_amount = round(cfg["투자금_만원"] * pnl_pct / 100, 1)
    sl_gap = round((sl_price - current_price) / current_price * 100, 1)
    loss_used = min(abs(pnl_pct) / 10 * 100, 100) if pnl_pct < 0 else 0

    # 추가매수 시뮬레이션
    add_man = cfg["추가투자_만원"]
    add1_man = add_man // 2  # 1차
    add2_man = add_man // 2  # 2차
    invest_man = cfg["투자금_만원"]
    # 1차 추가매수 후 평균단가 (현재가로 매수 가정)
    total_units = invest_man / buy_price
    add1_units  = (add1_man * 10000) / current_price / 10000  # 만원 단위 맞추기
    avg1 = round((invest_man + add1_man) / (invest_man / buy_price + add1_man / current_price), 2)
    avg1_pnl = round((current_price - avg1) / avg1 * 100, 2)
    # 2차 추가매수 후 평균단가
    avg2 = round((invest_man + add_man) / (invest_man / buy_price + add1_man / current_price + add2_man / current_price), 2)
    avg2_pnl = round((current_price - avg2) / avg2 * 100, 2)
    breakeven = buy_price  # 현재 손익분기점 = 매수단가

    return {
        "current_price": current_price,
        "buy_price": buy_price,
        "pnl_pct": pnl_pct,
        "pnl_amount": pnl_amount,
        "sl_price": sl_price,
        "sl_gap": sl_gap,
        "loss_used_pct": round(loss_used, 1),
        "invest_man": invest_man,
        "add_invest_man": add_man,
        "add1_man": add1_man,
        "add2_man": add2_man,
        "avg1": avg1,
        "avg1_pnl": avg1_pnl,
        "avg2": avg2,
        "avg2_pnl": avg2_pnl,
        "breakeven": breakeven,
        "nifty_buy_point": cfg.get("NIFTY50_매수시점", 24200),
    }

# ── 기술적 지표 계산 ─────────────────────────────────────────────
def calc_indicators(prices):
    n = len(prices)
    current = prices[-1]
    prev = prices[-2] if n >= 2 else current

    # 주간 등락
    week_chg = round((current - prev) / prev * 100, 2)

    # 이동평균 (주 단위: MA5=5주, MA13=13주≈3개월, MA26=26주≈6개월)
    ma5  = round(sum(prices[-5:]) / min(5, n))  if n >= 5  else None
    ma13 = round(sum(prices[-13:]) / min(13, n)) if n >= 13 else None
    ma26 = round(sum(prices[-26:]) / min(26, n)) if n >= 26 else None

    # 52주 고점/저점
    high52 = max(prices)
    low52  = min(prices)
    from_high = round((current - high52) / high52 * 100, 1)
    from_low  = round((current - low52)  / low52  * 100, 1)

    # RSI (14주)
    gains, losses = [], []
    for i in range(max(1, n-14), n):
        diff = prices[i] - prices[i-1]
        (gains if diff > 0 else losses).append(abs(diff))
    avg_gain = sum(gains) / 14 if gains else 0
    avg_loss = sum(losses) / 14 if losses else 0.0001
    rsi = round(100 - 100 / (1 + avg_gain / avg_loss), 1)

    # 변동성 (최근 8주 주간 변동률의 표준편차)
    returns = [(prices[i]-prices[i-1])/prices[i-1]*100 for i in range(max(1,n-8), n)]
    avg_r = sum(returns) / len(returns) if returns else 0
    vol = round((sum((r-avg_r)**2 for r in returns)/len(returns))**0.5, 2) if returns else 0

    # 단기 모멘텀 (4주 vs 8주 전)
    momentum = round((prices[-1] - prices[-5]) / prices[-5] * 100, 1) if n >= 5 else 0

    # 손절선(23,000) 대비 거리
    sl_dist = round((current - 23000) / 23000 * 100, 1)

    # MA 배열 판단 (정배열: 현재 > MA5 > MA13)
    if ma5 and ma13:
        if current > ma5 > ma13:
            ma_signal = "정배열(상승)"
        elif current < ma5 < ma13:
            ma_signal = "역배열(하락)"
        else:
            ma_signal = "혼조"
    else:
        ma_signal = "데이터 부족"

    return {
        "current": current, "week_chg": week_chg,
        "ma5": ma5, "ma13": ma13, "ma26": ma26, "ma_signal": ma_signal,
        "high52": high52, "low52": low52, "from_high": from_high, "from_low": from_low,
        "rsi": rsi, "vol": vol, "momentum": momentum, "sl_dist": sl_dist,
    }

# ── AI 차트 분석 생성 ────────────────────────────────────────────
def generate_chart_analysis(nifty, api_key):
    if not api_key:
        return "AI 분석을 보려면 설정.json에 anthropic_api_key를 입력해주세요."

    ind = calc_indicators(nifty["prices"])
    # 실제 전일 대비 등락률 사용 (헤더와 동일)
    actual_chg = nifty["change_pct"]
    actual_chg_str = f"{'+' if actual_chg >= 0 else ''}{actual_chg}%"

    prompt = f"""NIFTY50 주간 차트 지표를 바탕으로 분석해줘.

[지표]
현재: {ind['current']:,} (전일 대비 {actual_chg_str})
5주 이평: {ind['ma5']:,} / 13주 이평: {ind['ma13']:,} / 26주 이평: {ind['ma26']:,}
이평 배열: {ind['ma_signal']}
52주 고점: {ind['high52']:,} (현재 {ind['from_high']}%) / 52주 저점: {ind['low52']:,} (현재 +{ind['from_low']}%)
RSI(14): {ind['rsi']} (30이하=과매도, 70이상=과매수)
단기 모멘텀(4주): {'+' if ind['momentum']>=0 else ''}{ind['momentum']}%
주간 변동성: ±{ind['vol']}%
손절선(23,000) 대비: {'+' if ind['sl_dist']>=0 else ''}{ind['sl_dist']}%

아래 항목을 불릿(•)으로 각각 한 줄씩 정리해줘. 마크다운 **볼드** 사용 가능:
• **현재 지수**: 오늘 수치와 전주 등락 요약
• **추세 (이평)**: MA 배열로 본 매수세/매도세 판단
• **모멘텀**: RSI와 4주 모멘텀으로 본 단기 힘
• **변동성**: 최근 시장이 얼마나 출렁이는지
• **위치**: 52주 고점 대비 얼마나 내려왔는지, 저점 대비 얼마나 회복했는지
• **손절선**: 23,000선과의 거리와 위험도
• **한 줄 결론**: 지금 상황을 한 문장으로

한국어, 숫자 콤마 포함, 간결하게."""

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            return data["content"][0]["text"]
    except Exception as e:
        return f"분석 생성 실패: {e}"

def md2html(text):
    import re as _re
    h = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    return h.replace('\n', '<br>')

def index_section_html(data, chart_analysis, name, chart_id, period_prefix, sl=None):
    """NIFTY50 / SENSEX 공통 섹션 HTML 생성 (JS 초기화는 제외 — 하단 스크립트에서 처리)"""
    chg = data["change_pct"]
    chg_class = "up" if chg >= 0 else "down"
    chg_sign = "▲" if chg >= 0 else "▼"
    chg_val = f"{'+' if data['change_val']>=0 else ''}{data['change_val']:,.0f}"
    sl_legend = f'<span style="display:flex;align-items:center;gap:4px;"><span style="width:12px;height:2px;border-top:2px dashed #E24B4A;display:inline-block;"></span>손절선 {sl:,}</span>' if sl else ""
    analysis_card = ""
    if chart_analysis:
        analysis_html = md2html(chart_analysis)
        analysis_card = f"""
  <div class="card" style="margin-top:-4px;">
    <div class="card-title" style="font-size:12px;color:var(--text2);font-weight:500;margin-bottom:10px;">📊 AI 차트 분석 — {name}</div>
    <div style="font-size:13px;line-height:2;color:var(--text);">{analysis_html}</div>
  </div>"""

    return f"""
  <div class="nifty-header">
    <div class="nifty-name">{name}</div>
    <div class="nifty-price {chg_class}">{data["current"]:,}</div>
    <div class="nifty-change {chg_class}">{chg_sign} {chg_val} &nbsp;({'+' if chg>=0 else ''}{chg}%)</div>
    <div class="ohlc-row">
      <div class="ohlc-item"><div class="ohlc-label">시가</div><div class="ohlc-val">{data["open"]:,}</div></div>
      <div class="ohlc-item"><div class="ohlc-label">고가</div><div class="ohlc-val up">{data["high"]:,}</div></div>
      <div class="ohlc-item"><div class="ohlc-label">저가</div><div class="ohlc-val down">{data["low"]:,}</div></div>
    </div>
  </div>
  <div class="period-tabs" id="{period_prefix}-tabs">
    <div class="period-tab active" onclick="switchChart('{chart_id}','{period_prefix}','d1',this)">일</div>
    <div class="period-tab" onclick="switchChart('{chart_id}','{period_prefix}','d5',this)">5일</div>
    <div class="period-tab" onclick="switchChart('{chart_id}','{period_prefix}','d30',this)">1개월</div>
    <div class="period-tab" onclick="switchChart('{chart_id}','{period_prefix}','mo3',this)">3개월</div>
    <div class="period-tab" onclick="switchChart('{chart_id}','{period_prefix}','mo6',this)">6개월</div>
    <div class="period-tab" onclick="switchChart('{chart_id}','{period_prefix}','yr1',this)">1년</div>
  </div>
  <div class="card" style="padding:12px 12px 10px;">
    <div class="chart-wrap"><canvas id="{chart_id}"></canvas></div>
    <div style="display:flex;gap:16px;font-size:11px;color:var(--text2);margin-top:4px;">
      <span style="display:flex;align-items:center;gap:4px;"><span style="width:12px;height:2px;background:#378ADD;display:inline-block;border-radius:1px;"></span>{name}</span>
      {sl_legend}
    </div>
  </div>{analysis_card}"""

def make_periods_js(data, name, sl=None):
    return json.dumps({
        "name": name,
        "sl":   sl,
        "d1":  data["d1"], "d5":  data["d5"], "d30": data["d30"],
        "mo3": data["mo3"],"mo6": data["mo6"],"yr1": data["yr1"],
    }, ensure_ascii=False)

def build_nav_section_html(history, buy_price=797.6, nifty_data=None, nifty_buy_point=24200):
    """기준가 이력 차트 + 테이블 HTML (수동 입력 데이터만 사용)"""
    if not history or len(history) < 2:
        return '<div style="color:var(--text2);font-size:13px;">이력 없음 — 설정.json의 기준가_이력을 업데이트해주세요.</div>', "{}", buy_price

    # 오래된 순으로 정렬
    rev = list(reversed(history))
    def slice_period(n):
        sliced = rev[-n:] if len(rev) > n else rev
        return {"labels": [h["날짜"] for h in sliced], "prices": [h["기준가"] for h in sliced]}

    periods = {
        "mo1": slice_period(22),
        "mo3": slice_period(66),
        "mo6": slice_period(130),
        "yr1": slice_period(252),
        "all": slice_period(9999),
    }
    periods_js = json.dumps({"name": "기준가", "sl": buy_price, **periods}, ensure_ascii=False)

    # 헤더 정보
    cur = history[0]["기준가"]
    prev = history[1]["기준가"]
    diff = round(cur - prev, 2)
    pct = round(diff / prev * 100, 2)
    chg_class = "up" if diff >= 0 else "down"
    chg_sign = "▲" if diff >= 0 else "▼"
    plus = "+" if diff >= 0 else ""

    # 테이블 (최신순)
    rows = ""
    for i, item in enumerate(history):
        nav = item["기준가"]
        if i < len(history) - 1:
            p = history[i + 1]["기준가"]
            d = round(nav - p, 2)
            pc = round(d / p * 100, 2)
            sg = "▲" if d > 0 else "▼"
            cl = "up" if d > 0 else "down"
            pl = "+" if d > 0 else ""
            diff_str = f'<span class="{cl}">{sg} {abs(d):.2f}</span>'
            pct_str  = f'<span class="{cl}">{pl}{pc:.2f}%</span>'
        else:
            diff_str = "<span>—</span>"
            pct_str  = "<span>—</span>"
        rows += f"""
    <tr>
      <td>{item["날짜"]}</td>
      <td style="font-weight:600;">{nav:.2f}</td>
      <td>{diff_str}</td>
      <td>{pct_str}</td>
    </tr>"""

    html = f"""
  <div class="nifty-header">
    <div class="nifty-name">KB스타 NIFTY50 인덱스 (H) S</div>
    <div class="nifty-price {chg_class}">{cur:.2f}</div>
    <div class="nifty-change {chg_class}">{chg_sign} {abs(diff):.2f} &nbsp;({plus}{pct:.2f}%)</div>
  </div>
  <div style="font-size:11px;color:var(--text3);margin-bottom:10px;">* 기준가 이력이 쌓이면 기간 탭이 활성화됩니다</div>
  <div class="card" style="padding:12px 12px 10px;">
    <div class="chart-wrap"><canvas id="chartNav"></canvas></div>
    <div style="display:flex;gap:16px;font-size:11px;color:var(--text2);margin-top:4px;">
      <span style="display:flex;align-items:center;gap:4px;"><span style="width:12px;height:2px;background:#378ADD;display:inline-block;border-radius:1px;"></span>기준가</span>
      <span style="display:flex;align-items:center;gap:4px;"><span style="width:12px;height:2px;border-top:2px dashed #E24B4A;display:inline-block;"></span>매수단가 {buy_price}</span>
    </div>
  </div>
  <div class="card" style="margin-top:-4px;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="color:var(--text2);font-size:11px;border-bottom:1px solid var(--border);">
          <th style="text-align:left;padding:6px 0;font-weight:500;">기준일</th>
          <th style="text-align:right;padding:6px 0;font-weight:500;">기준가</th>
          <th style="text-align:right;padding:6px 0;font-weight:500;">대비</th>
          <th style="text-align:right;padding:6px 0;font-weight:500;">등락률</th>
        </tr>
      </thead>
      <tbody style="line-height:2;">{rows}
      </tbody>
    </table>
    <div style="margin-top:10px;font-size:11px;color:var(--text3);">* KB앱에서 확인 후 설정.json의 기준가_이력에 최신 값 추가하면 자동 반영돼요</div>
  </div>"""
    return html, periods_js, buy_price

# ── HTML 생성 ───────────────────────────────────────────────────
def build_html(nifty, sensex, metrics, api_key, updated_at, nifty_analysis, sensex_analysis, nav_history=None, indicators=None, macro=None, news=None, action_guide=None, events=None):
    import re as _re

    pnl_class = "up" if metrics["pnl_pct"] >= 0 else "down"
    pnl_sign = "+" if metrics["pnl_pct"] >= 0 else ""
    pnl_amt_sign = "+" if metrics["pnl_amount"] >= 0 else ""
    sl_class = "up" if metrics["sl_gap"] < -5 else "down"

    nifty_section = index_section_html(nifty, nifty_analysis, "NIFTY 50", "chartNifty", "nifty", sl=23000)
    sensex_section = index_section_html(sensex, sensex_analysis, "SENSEX", "chartSensex", "sensex", sl=None)
    nifty_periods_js = make_periods_js(nifty, "NIFTY 50", sl=23000)
    sensex_periods_js = make_periods_js(sensex, "SENSEX", sl=None)
    nav_table, nav_periods_js, nav_buy_price = build_nav_section_html(
        nav_history or [], buy_price=metrics["buy_price"]
    )

    # 기술적 신호 (자동 계산)
    ind = indicators or {}
    def sig_row(name, badge_cls, text, badge_id=""):
        id_attr = f' id="{badge_id}"' if badge_id else ''
        return f'<div class="signal-row"><span class="signal-name">{name}</span><span class="badge {badge_cls}"{id_attr} data-sg="tech">{text}</span></div>'

    rsi = ind.get("rsi", 50)
    if rsi <= 30:   rsi_cls, rsi_txt = "badge-g", f"RSI {rsi} — 과매도 (매수 기회)"
    elif rsi >= 70: rsi_cls, rsi_txt = "badge-r", f"RSI {rsi} — 과매수 (주의)"
    else:           rsi_cls, rsi_txt = "badge-b", f"RSI {rsi} — 중립"

    ma_sig = ind.get("ma_signal", "데이터 부족")
    if "정배열" in ma_sig: ma_cls = "badge-g"
    elif "역배열" in ma_sig: ma_cls = "badge-r"
    else: ma_cls = "badge-y"

    mom = ind.get("momentum", 0)
    mom_cls = "badge-g" if mom > 1 else ("badge-r" if mom < -1 else "badge-y")
    mom_txt = f"{'▲' if mom>=0 else '▼'} {abs(mom)}% (4주 변화)"

    vol = ind.get("vol", 0)
    vol_cls = "badge-r" if vol > 2 else ("badge-y" if vol > 1 else "badge-g")
    vol_txt = f"주간 ±{vol}% — {'고변동' if vol > 2 else ('보통' if vol > 1 else '안정')}"

    fh = ind.get("from_high", 0)
    fl = ind.get("from_low", 0)
    pos_cls = "badge-g" if fh > -10 else ("badge-y" if fh > -20 else "badge-r")
    pos_txt = f"52주 고점 대비 {fh}% / 저점 대비 +{fl}%"

    sl_dist = ind.get("sl_dist", 0)
    sl_cls = "badge-g" if sl_dist > 5 else ("badge-y" if sl_dist > 2 else "badge-r")
    sl_txt = f"손절선까지 {sl_dist:+.1f}% — {'여유' if sl_dist>5 else ('주의' if sl_dist>2 else '위험')}"

    # NIFTY P/E 밸류에이션
    pe = (macro or {}).get("nifty_pe")
    if pe:
        if pe < 18:   pe_cls, pe_txt = "badge-g", f"P/E {pe} — 저평가 (역사 평균 이하)"
        elif pe < 22: pe_cls, pe_txt = "badge-b", f"P/E {pe} — 적정 수준"
        elif pe < 26: pe_cls, pe_txt = "badge-y", f"P/E {pe} — 다소 고평가"
        else:         pe_cls, pe_txt = "badge-r", f"P/E {pe} — 고평가 주의"
    else:
        pe_cls, pe_txt = "badge-b", "P/E 데이터 없음"

    tech_signals_html = (
        sig_row("RSI (14주)", rsi_cls, rsi_txt, "ind-rsi") +
        sig_row("이평선 배열", ma_cls, ma_sig, "ind-ma") +
        sig_row("단기 모멘텀", mom_cls, mom_txt, "ind-mom") +
        sig_row("변동성", vol_cls, vol_txt, "ind-vol") +
        sig_row("52주 가격 위치", pos_cls, pos_txt, "ind-pos") +
        sig_row("NIFTY 밸류에이션", pe_cls, pe_txt, "ind-pe") +
        sig_row("손절선 거리", sl_cls, sl_txt, "ind-sl")
    )

    # ── 매크로 신호 자동 계산 ──────────────────────────────────────
    macro = macro or {}

    # NIFTY 23,000 지지 여부 (이미 있는 데이터로)
    nifty_cur = nifty["current"]
    if nifty_cur >= 24000:
        nifty_sup_cls, nifty_sup_txt = "badge-g", f"✓ {nifty_cur:,} — 여유 있음"
    elif nifty_cur >= 23000:
        nifty_sup_cls, nifty_sup_txt = "badge-y", f"⚠ {nifty_cur:,} — 지지선 근접"
    else:
        nifty_sup_cls, nifty_sup_txt = "badge-r", f"✗ {nifty_cur:,} — 23,000 이탈!"

    # USD/INR 환율 — (H) 환헤지 펀드라 직접 영향 제한적
    usdinr = macro.get("usdinr")
    if usdinr:
        if usdinr < 83:
            usdinr_cls, usdinr_txt = "badge-g", f"₹{usdinr} — 루피 강세"
        elif usdinr < 86:
            usdinr_cls, usdinr_txt = "badge-b", f"₹{usdinr} — 안정권"
        elif usdinr < 88:
            usdinr_cls, usdinr_txt = "badge-y", f"₹{usdinr} — 루피 약세"
        else:
            usdinr_cls, usdinr_txt = "badge-r", f"₹{usdinr} — 루피 급락"
    else:
        usdinr_cls, usdinr_txt = "badge-b", "데이터 없음"

    # 미국 VIX
    vix = macro.get("vix")
    if vix:
        if vix < 15:   vix_cls, vix_txt = "badge-g", f"US VIX {vix} — 매우 안정"
        elif vix < 20: vix_cls, vix_txt = "badge-g", f"US VIX {vix} — 안정"
        elif vix < 25: vix_cls, vix_txt = "badge-y", f"US VIX {vix} — 보통"
        elif vix < 30: vix_cls, vix_txt = "badge-y", f"US VIX {vix} — 불안 주의"
        else:          vix_cls, vix_txt = "badge-r", f"US VIX {vix} — 공포 구간"
    else:
        vix_cls, vix_txt = "badge-b", "데이터 없음"

    # India VIX (인도 자체 공포지수 — 더 직접적)
    india_vix = macro.get("india_vix")
    if india_vix:
        if india_vix < 13:   ivix_cls, ivix_txt = "badge-g", f"India VIX {india_vix} — 매우 안정"
        elif india_vix < 18: ivix_cls, ivix_txt = "badge-g", f"India VIX {india_vix} — 안정"
        elif india_vix < 22: ivix_cls, ivix_txt = "badge-y", f"India VIX {india_vix} — 보통"
        elif india_vix < 28: ivix_cls, ivix_txt = "badge-y", f"India VIX {india_vix} — 주의"
        else:                ivix_cls, ivix_txt = "badge-r", f"India VIX {india_vix} — 공포"
    else:
        ivix_cls, ivix_txt = "badge-b", "데이터 없음"

    # 브렌트유
    crude = macro.get("crude")
    if crude:
        if crude < 70:
            crude_cls, crude_txt = "badge-g", f"${crude} 저유가 (호재)"
        elif crude < 80:
            crude_cls, crude_txt = "badge-g", f"${crude} 안정 (호재)"
        elif crude < 90:
            crude_cls, crude_txt = "badge-y", f"${crude} 보통"
        elif crude < 100:
            crude_cls, crude_txt = "badge-y", f"${crude} 다소 높음"
        else:
            crude_cls, crude_txt = "badge-r", f"${crude} 고유가 (악재)"
    else:
        crude_cls, crude_txt = "badge-b", "데이터 없음"

    # ── 뉴스 기반 매크로 신호 카드 생성 ─────────────────────────────
    news = news or {}
    auto_tag = '<span style="font-size:10px;color:var(--text3);margin-left:4px;">자동</span>'

    def news_row(label, key, auto=True):
        n = news.get(key, {})
        badge_cls = n.get("badge", "badge-b")
        text = n.get("text", "수집 중...")
        tag = auto_tag if auto else ""
        headlines = n.get("headlines", [])
        tooltip = " | ".join(h[18:] for h in headlines[:3]) if headlines else ""
        tooltip_attr = f'title="{tooltip}"' if tooltip else ""
        badge_id = f'ind-{key.lower()}'
        return (f'<div class="signal-row" {tooltip_attr}>'
                f'<span class="signal-name">{label}{tag}</span>'
                f'<span class="badge {badge_cls}" id="{badge_id}" data-sg="news">{text}</span>'
                f'</div>')

    # 연준 금리는 실제 수치 표시
    fed_n = news.get("fed", {})
    fed_rate_val = fed_n.get("rate")
    fed_badge = fed_n.get("badge", "badge-b")
    fed_text = f"{fed_rate_val}% — {fed_n.get('text','')}" if fed_rate_val else fed_n.get("text","수집 중...")

    # 몬순 시즌 경고 배너
    monsoon = (macro or {}).get("monsoon", False)
    monsoon_banner = ""
    if monsoon:
        monsoon_banner = '<div style="background:#e8f4fd;border-left:3px solid #1565c0;padding:8px 10px;border-radius:6px;font-size:12px;color:#1565c0;margin-bottom:8px;">🌧 몬순 시즌 (6~9월) — 강수량에 따라 인도 농업·소비·인플레이션 영향 있어요</div>'

    news_card_html = f"""  <div class="card" style="margin-top:-4px;">
    <div class="card-title" style="margin-bottom:8px;">🌏 매크로 신호 <span style="font-size:11px;font-weight:400;color:var(--text3);">— 업데이트 실행 시 갱신</span></div>
    {monsoon_banner}
    <div class="signal-row">
      <span class="signal-name">NIFTY50 23,000 지지</span>
      <span class="badge {nifty_sup_cls}" id="ind-niftysup" data-sg="macro">{nifty_sup_txt}</span>
    </div>
    <div class="signal-row">
      <span class="signal-name">루피/달러{auto_tag} <span style="font-size:10px;color:var(--text3);">(환헤지 펀드·직접 영향 낮음)</span></span>
      <span class="badge {usdinr_cls}" id="ind-usdinr" data-sg="macro">{usdinr_txt}</span>
    </div>
    <div class="signal-row">
      <span class="signal-name">India VIX{auto_tag} <span style="font-size:10px;color:var(--text3);">(인도 공포지수)</span></span>
      <span class="badge {ivix_cls}" id="ind-ivix" data-sg="macro">{ivix_txt}</span>
    </div>
    <div class="signal-row">
      <span class="signal-name">공포지수 VIX{auto_tag} <span style="font-size:10px;color:var(--text3);">(미국)</span></span>
      <span class="badge {vix_cls}" id="ind-vix" data-sg="macro">{vix_txt}</span>
    </div>
    <div class="signal-row">
      <span class="signal-name">브렌트유{auto_tag}</span>
      <span class="badge {crude_cls}" id="ind-crude" data-sg="macro">{crude_txt}</span>
    </div>
    {news_row("FII 외국인 자금", "FII")}
    {news_row("DII 국내기관 자금", "DII")}
    {news_row("RBI 금리", "RBI")}
    {news_row("인도 PMI", "pmi")}
    {news_row("인도 CPI", "cpi")}
    {news_row("미-인도 무역", "trade")}
    {news_row("중동 정세", "mideast")}
    <div class="signal-row">
      <span class="signal-name">미국 연준 금리{auto_tag}</span>
      <span class="badge {fed_badge}" id="ind-fed" data-sg="news">{fed_text}</span>
    </div>
    <div style="margin-top:10px;font-size:11px;color:var(--text3);">* 뉴스 항목은 마우스를 올리면 원문 헤드라인을 볼 수 있어요</div>
  </div>"""

    # ── 액션 가이드 HTML ──────────────────────────────────────────
    ag = action_guide
    if ag:
        now_type = ag.get("now", {}).get("type", "hold")
        now_cls  = {"hold": "action-hold", "buy": "action-buy", "sell": "action-sell"}.get(now_type, "action-hold")
        action_guide_html = f"""
  <div class="action {now_cls}">
    <div class="action-title">{ag['now']['title']}</div>
    <div class="action-desc">{ag['now']['desc']}</div>
  </div>
  <div class="action action-buy">
    <div class="action-title">{ag['buy1']['title']}</div>
    <div class="action-desc">{ag['buy1']['desc']}</div>
  </div>
  <div class="action action-buy">
    <div class="action-title">{ag['buy2']['title']}</div>
    <div class="action-desc">{ag['buy2']['desc']}</div>
  </div>
  <div class="action action-sell">
    <div class="action-title">{ag['sell']['title']}</div>
    <div class="action-desc">{ag['sell']['desc']}</div>
  </div>"""
    else:
        action_guide_html = f"""
  <div class="action action-hold">
    <div class="action-title">📌 지금 — 보유 유지</div>
    <div class="action-desc">데이터 수집 중입니다. 다시 열어주세요.</div>
  </div>
  <div class="action action-buy">
    <div class="action-title">🟢 1차 매수 조건</div>
    <div class="action-desc">NIFTY50 23,000 지지 유지 + FII 순매수 전환 확인 시 → {metrics['add_invest_man']//2:,}만원 투입</div>
  </div>
  <div class="action action-buy">
    <div class="action-title">🟢 2차 매수 조건</div>
    <div class="action-desc">NIFTY50 24,000 회복 + 추세 확인 시 → {metrics['add_invest_man']//2:,}만원 추가</div>
  </div>
  <div class="action action-sell">
    <div class="action-title">🔴 손절 조건</div>
    <div class="action-desc">펀드 기준가 {metrics['sl_price']}원 이탈 OR NIFTY50 23,000 붕괴 시 → 전량 매도 검토</div>
  </div>"""

    # ── 목표수익률 계산기 ────────────────────────────────────────
    exit_rows = ""
    nifty_buy_pt = metrics["nifty_buy_point"]
    buy_p = metrics["buy_price"]
    invest = metrics["invest_man"]
    for tgt in [5, 10, 20, 30]:
        t_nav   = round(buy_p * (1 + tgt / 100), 2)
        t_nifty = round(nifty_buy_pt * (1 + tgt / 100))
        t_profit = round(invest * tgt / 100, 1)
        already = metrics["pnl_pct"] >= tgt
        cls = "color:var(--text3);" if already else ""
        done = " ✓" if already else ""
        exit_rows += f"""<tr style="{cls}">
          <td>+{tgt}%{done}</td>
          <td style="text-align:right;font-weight:600;">{t_nav}원</td>
          <td style="text-align:right;">{t_nifty:,}</td>
          <td style="text-align:right;color:var(--up);">+{t_profit}만원</td>
        </tr>"""

    # ── 종합 신호 스코어카드 ──────────────────────────────────────
    _bmap = {"badge-g": 1, "badge-y": 0, "badge-r": -1, "badge-b": 0}
    _tech_badges  = [rsi_cls, ma_cls, mom_cls, vol_cls, pos_cls, pe_cls, sl_cls]
    _macro_badges = [nifty_sup_cls, ivix_cls, vix_cls, usdinr_cls, crude_cls]
    _news_badges  = [news.get(k, {}).get("badge", "badge-b")
                     for k in ["FII","DII","RBI","pmi","cpi","trade","mideast","fed"]]

    tech_score  = sum(_bmap.get(b, 0) * 1.5 for b in _tech_badges)
    macro_score = sum(_bmap.get(b, 0) * 1.0 for b in _macro_badges)
    news_score  = sum(_bmap.get(b, 0) * 0.8 for b in _news_badges)
    total_score = tech_score + macro_score + news_score
    max_score   = len(_tech_badges)*1.5 + len(_macro_badges)*1.0 + len(_news_badges)*0.8

    score_pct = int((total_score + max_score) / (2 * max_score) * 100)
    score_pct = max(0, min(100, score_pct))

    if total_score >= max_score * 0.5:
        sc_label, sc_color, sc_bg, sc_emoji = "강매수", "#2d6a0a", "#e8fde8", "🔥"
    elif total_score >= max_score * 0.15:
        sc_label, sc_color, sc_bg, sc_emoji = "매수", "#2d8a4e", "#f0faf0", "🟢"
    elif total_score >= -max_score * 0.15:
        sc_label, sc_color, sc_bg, sc_emoji = "보유", "#BA7517", "#fff8e1", "📌"
    elif total_score >= -max_score * 0.5:
        sc_label, sc_color, sc_bg, sc_emoji = "매도 검토", "#c0392b", "#fff0f0", "⚠️"
    else:
        sc_label, sc_color, sc_bg, sc_emoji = "강매도", "#9b2020", "#fde8e8", "🔴"

    # 실제 수치 기반 구체적 설명 생성
    _usdinr = (macro or {}).get("usdinr")
    _fii_badge = news.get("FII", {}).get("badge", "badge-b")
    _rbi_badge = news.get("RBI", {}).get("badge", "badge-b")
    _fii_txt   = news.get("FII", {}).get("text", "")
    _rbi_txt   = news.get("RBI", {}).get("text", "")
    _cpi_badge = news.get("cpi", {}).get("badge", "badge-b")
    _pmi_badge = news.get("pmi", {}).get("badge", "badge-b")

    if sc_label == "강매수":
        sc_desc = (
            f"기술·매크로·뉴스 신호가 전반적으로 긍정적입니다. "
            f"RSI {rsi}로 과열 없이 상승 여력이 있으며, 이평선 {ma_sig} 상태입니다. "
            + (f"루피(₹{_usdinr}) 안정으로 외국인 수익률도 유리합니다. " if _usdinr and _usdinr < 85 else "")
            + "지금은 분할 매수를 적극 고려할 수 있는 시점입니다."
        )
    elif sc_label == "매수":
        sc_desc = (
            f"RSI {rsi}로 중립 수준이며, 이평선 {ma_sig} 상태입니다. "
            + (f"4주 모멘텀 {mom:+}%로 " + ("상승 흐름 중입니다. " if mom > 0 else "약세이나 반등 여지가 있습니다. "))
            + (f"FII 자금: {_fii_txt}. " if _fii_txt else "")
            + "전체 신호가 완전히 갖춰지기 전까지 소규모 선진입으로 접근하세요."
        )
    elif sc_label == "보유":
        bad_parts = []
        if _usdinr and _usdinr >= 88: bad_parts.append(f"루피 약세(₹{_usdinr})")
        if _fii_badge == "badge-r": bad_parts.append("FII 외국인 유출")
        if _cpi_badge == "badge-r": bad_parts.append("물가 상승 압력")
        if _pmi_badge == "badge-r": bad_parts.append("PMI 제조업 둔화")
        sc_desc = (
            f"RSI {rsi}, 이평선 {ma_sig}으로 기술적 신호는 중립입니다. "
            + (f"{', '.join(bad_parts)} 등 리스크가 남아 있어 추가 매수보다는 현 포지션을 유지하는 것이 유리합니다. " if bad_parts else "신호가 혼재해 추가 매수보다 현 포지션 유지를 권장합니다. ")
            + f"손절선까지 {sl_dist:+.1f}% 거리를 점검하세요."
        )
    elif sc_label == "매도 검토":
        sc_desc = (
            f"부정적 신호가 우세합니다. RSI {rsi}, 이평선 {ma_sig} 상태입니다. "
            + (f"루피가 ₹{_usdinr}까지 약세로 외국인 수익률이 악화되고 있으며, " if _usdinr and _usdinr >= 88 else "")
            + (f"FII 자금도 유출 중입니다. " if _fii_badge == "badge-r" else "")
            + f"손절선까지 {sl_dist:+.1f}% — 손절 기준을 재확인하고 비중 축소를 고려하세요."
        )
    else:
        sc_desc = (
            f"복수의 위험 신호가 동시에 켜져 있습니다. RSI {rsi}, 이평선 {ma_sig}, 4주 모멘텀 {mom:+}%로 기술적 약세가 뚜렷합니다. "
            + (f"루피(₹{_usdinr}) 급락으로 외국인 자금 이탈이 가속화될 수 있습니다. " if _usdinr and _usdinr >= 90 else "")
            + "비중 축소 또는 현금 보유를 우선 고려하고 추세 반전 확인 후 재진입하세요."
        )

    scorecard_html = f"""<div style="background:{sc_bg};border:1px solid {sc_color}33;border-radius:18px;padding:18px 20px;margin-bottom:20px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <div>
        <div style="font-size:11px;font-weight:600;color:{sc_color};letter-spacing:0.08em;text-transform:uppercase;margin-bottom:4px;">종합 투자 신호</div>
        <div id="sc-emoji" style="font-size:28px;font-weight:700;color:{sc_color};">{sc_emoji} {sc_label}</div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:11px;color:var(--text3);margin-bottom:4px;">신호 강도</div>
        <div id="sc-pct" style="font-size:24px;font-weight:700;color:{sc_color};">{score_pct}점</div>
        <div style="font-size:10px;color:var(--text3);">/ 100점</div>
      </div>
    </div>
    <div style="background:rgba(0,0,0,0.08);border-radius:6px;height:8px;overflow:hidden;margin-bottom:10px;">
      <div id="sc-bar" style="width:{score_pct}%;height:100%;border-radius:6px;background:{sc_color};transition:width 0.6s;"></div>
    </div>
    <div style="display:flex;gap:16px;font-size:11px;color:var(--text2);">
      <span>기술적 <strong id="sc-tech" style="color:{sc_color};">{'+' if tech_score>=0 else ''}{tech_score:.1f}</strong></span>
      <span>매크로 <strong id="sc-macro" style="color:{sc_color};">{'+' if macro_score>=0 else ''}{macro_score:.1f}</strong></span>
      <span>뉴스 <strong id="sc-news" style="color:{sc_color};">{'+' if news_score>=0 else ''}{news_score:.1f}</strong></span>
    </div>
    <div id="sc-desc" style="margin-top:10px;font-size:12px;color:var(--text2);line-height:1.6;padding:10px 12px;background:rgba(0,0,0,0.04);border-radius:10px;">{sc_desc}</div>
  </div>"""

    # ── 이벤트 일정 카드 ──────────────────────────────────────────
    events_html = ""
    if events:
        today = datetime.now().date()
        rows = ""
        for ev in sorted(events, key=lambda x: x["날짜"]):
            try:
                from datetime import date as date_cls
                ev_date = date_cls.fromisoformat(ev["날짜"])
                diff = (ev_date - today).days
                if diff < 0:
                    continue  # 지난 이벤트 제외
                if diff == 0:
                    d_txt, d_cls = "오늘", "color:var(--down);font-weight:700;"
                elif diff <= 7:
                    d_txt, d_cls = f"D-{diff}", "color:var(--down);font-weight:600;"
                elif diff <= 30:
                    d_txt, d_cls = f"D-{diff}", "color:var(--warn-text);font-weight:500;"
                else:
                    d_txt, d_cls = f"D-{diff}", "color:var(--text3);"
                rows += f'<tr><td style="color:var(--text2);">{ev["날짜"][5:]}</td><td>{ev["내용"]}</td><td style="text-align:right;{d_cls}">{d_txt}</td></tr>'
            except Exception:
                pass
        if rows:
            events_html = f"""<div class="section-label">주요 이벤트 일정</div>
  <div class="card" style="margin-bottom:16px;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <tbody style="line-height:2.2;">{rows}</tbody>
    </table>
    <div style="margin-top:8px;font-size:11px;color:var(--text3);">* 설정.json의 주요이벤트에서 수정할 수 있어요</div>
  </div>
  <hr class="divider" style="margin-top:0;">"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>인도 펀드 대시보드</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --bg: #f5f5f7;
  --card-bg: #ffffff;
  --text: #1d1d1f;
  --text2: #6e6e73;
  --text3: #aeaeb2;
  --border: rgba(0,0,0,0.1);
  --up: #2d8a4e;
  --down: #c0392b;
  --warn-bg: #fff8e1;
  --warn-text: #BA7517;
  --buy-bg: #f0faf0;
  --buy-text: #2d6a0a;
  --sell-bg: #fff0f0;
  --sell-text: #9b2020;
  --info-bg: #e8f4fd;
  --info-text: #1565c0;
  --badge-r-bg: #fde8e8;
  --badge-r: #c0392b;
  --badge-g-bg: #e8fde8;
  --badge-g: #2d6a0a;
  --badge-y-bg: #fdf6e8;
  --badge-y: #BA7517;
  --badge-b-bg: #e8f0fe;
  --badge-b: #1565c0;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #1c1c1e;
    --card-bg: #2c2c2e;
    --text: #f2f2f7;
    --text2: #aeaeb2;
    --text3: #636366;
    --border: rgba(255,255,255,0.1);
    --up: #4cd964;
    --down: #ff453a;
    --warn-bg: #2a2200;
    --warn-text: #ffd60a;
    --buy-bg: #0d2200;
    --buy-text: #4cd964;
    --sell-bg: #2a0000;
    --sell-text: #ff453a;
    --info-bg: #001a33;
    --info-text: #64b5f6;
    --badge-r-bg: #2a0a0a;
    --badge-r: #ff6b6b;
    --badge-g-bg: #0a1a0a;
    --badge-g: #6fcf97;
    --badge-y-bg: #1a1200;
    --badge-y: #f2c94c;
    --badge-b-bg: #001a2a;
    --badge-b: #56ccf2;
  }}
}}
body {{ font-family: -apple-system, 'Apple SD Gothic Neo', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; padding: 0; }}
.container {{ max-width: 480px; margin: 0 auto; padding: 20px 16px 40px; }}
.header {{ margin-bottom: 24px; }}
.header h1 {{ font-size: 22px; font-weight: 700; }}
.header p {{ font-size: 13px; color: var(--text2); margin-top: 4px; }}
.nifty-badge {{ display: inline-flex; align-items: center; gap: 6px; background: var(--card-bg); border-radius: 20px; padding: 4px 12px; font-size: 13px; font-weight: 500; border: 0.5px solid var(--border); margin-top: 10px; }}
.section-label {{ font-size: 11px; font-weight: 600; color: var(--text3); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; }}
.metric-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px; }}
.metric {{ background: var(--card-bg); border-radius: 14px; padding: 14px 16px; border: 0.5px solid var(--border); }}
.metric-label {{ font-size: 12px; color: var(--text2); margin-bottom: 4px; }}
.metric-value {{ font-size: 22px; font-weight: 600; }}
.metric-sub {{ font-size: 12px; margin-top: 3px; color: var(--text2); }}
.up {{ color: var(--up); }}
.down {{ color: var(--down); }}
table td {{ padding: 5px 0; border-bottom: 1px solid var(--border); }}
table td:not(:first-child) {{ text-align: right; }}
.card {{ background: var(--card-bg); border-radius: 16px; padding: 16px; margin-bottom: 16px; border: 0.5px solid var(--border); }}
.card-title {{ font-size: 14px; font-weight: 600; margin-bottom: 14px; }}
.loss-section {{ margin-bottom: 20px; }}
.loss-bar-bg {{ background: var(--border); border-radius: 6px; height: 10px; overflow: hidden; margin: 8px 0 6px; }}
.loss-bar-fill {{ height: 100%; border-radius: 6px; background: linear-gradient(90deg, #4cd964, #ffd60a, #ff453a); transition: width 0.6s ease; }}
.loss-label {{ display: flex; justify-content: space-between; font-size: 11px; color: var(--text3); }}
.nifty-header {{ background: var(--card-bg); border-radius: 16px; padding: 16px; margin-bottom: 12px; border: 0.5px solid var(--border); }}
.nifty-name {{ font-size: 13px; color: var(--text2); margin-bottom: 6px; }}
.nifty-price {{ font-size: 36px; font-weight: 700; letter-spacing: -1px; }}
.nifty-change {{ font-size: 15px; font-weight: 500; margin-top: 4px; }}
.ohlc-row {{ display: flex; gap: 0; margin-top: 12px; border-top: 0.5px solid var(--border); padding-top: 12px; }}
.ohlc-item {{ flex: 1; text-align: center; }}
.ohlc-label {{ font-size: 11px; color: var(--text3); margin-bottom: 3px; }}
.ohlc-val {{ font-size: 13px; font-weight: 600; }}
.period-tabs {{ display: flex; gap: 4px; margin-bottom: 10px; }}
.period-tab {{ flex: 1; text-align: center; font-size: 12px; font-weight: 500; padding: 7px 0; border-radius: 8px; border: 0.5px solid var(--border); background: var(--bg); color: var(--text2); cursor: pointer; }}
.period-tab.active {{ background: var(--text); color: var(--bg); border-color: var(--text); }}
.chart-wrap {{ height: 230px; margin-bottom: 8px; }}
.signal-row {{ display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 0.5px solid var(--border); }}
.signal-row:last-child {{ border-bottom: none; }}
.signal-name {{ font-size: 13px; color: var(--text2); }}
.badge {{ font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 8px; }}
.badge-r {{ background: var(--badge-r-bg); color: var(--badge-r); }}
.badge-g {{ background: var(--badge-g-bg); color: var(--badge-g); }}
.badge-y {{ background: var(--badge-y-bg); color: var(--badge-y); }}
.badge-b {{ background: var(--badge-b-bg); color: var(--badge-b); }}
.action {{ border-radius: 12px; padding: 13px 15px; margin-bottom: 10px; }}
.action-hold {{ background: var(--warn-bg); border-left: 3px solid var(--warn-text); }}
.action-buy {{ background: var(--buy-bg); border-left: 3px solid var(--buy-text); }}
.action-sell {{ background: var(--sell-bg); border-left: 3px solid var(--sell-text); }}
.action-title {{ font-size: 13px; font-weight: 600; margin-bottom: 5px; }}
.action-hold .action-title {{ color: var(--warn-text); }}
.action-buy .action-title {{ color: var(--buy-text); }}
.action-sell .action-title {{ color: var(--sell-text); }}
.action-desc {{ font-size: 12px; color: var(--text2); line-height: 1.6; }}
.divider {{ border: none; border-top: 0.5px solid var(--border); margin: 20px 0; }}
.input-row {{ display: flex; gap: 8px; margin-bottom: 10px; }}
.input-row input {{ flex: 1; font-size: 13px; padding: 10px 12px; border: 0.5px solid var(--border); border-radius: 10px; background: var(--bg); color: var(--text); outline: none; }}
.input-row input:focus {{ border-color: #0071e3; }}
.btn {{ font-size: 13px; padding: 10px 16px; border: 0.5px solid var(--border); border-radius: 10px; background: var(--card-bg); color: var(--text); cursor: pointer; white-space: nowrap; font-weight: 500; }}
.btn:hover {{ opacity: 0.8; }}
.quick-btns {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }}
.quick-btn {{ font-size: 11px; padding: 6px 11px; }}
.ai-response {{ font-size: 13px; color: var(--text); line-height: 1.8; padding: 14px; background: var(--bg); border-radius: 10px; min-height: 60px; white-space: pre-wrap; }}
.footer {{ font-size: 11px; color: var(--text3); text-align: center; margin-top: 20px; }}
</style>
</head>
<body>
<div class="container">

  <div style="text-align:right;margin-bottom:12px;">
    <button onclick="location.reload(true)" style="padding:7px 18px;border-radius:20px;border:0.5px solid var(--border);background:var(--card-bg);color:var(--text);font-size:13px;font-weight:500;cursor:pointer;">🔄 새로고침</button>
  </div>

  {scorecard_html}

  <div class="section-label">NIFTY 50</div>
  {nifty_section}

  <hr class="divider">

  <div class="section-label">SENSEX</div>
  {sensex_section}

  <hr class="divider">

  <div class="section-label">펀드 기준가 이력</div>
  {nav_table}

  <hr class="divider">

  <div class="section-label">포트폴리오 현황</div>
  <div class="metric-grid">
    <div class="metric">
      <div class="metric-label">현재 기준가</div>
      <div class="metric-value">{metrics["current_price"]:.2f}원</div>
      <div class="metric-sub">매수단가 {metrics["buy_price"]}원</div>
    </div>
    <div class="metric">
      <div class="metric-label">현재 손익</div>
      <div class="metric-value {pnl_class}">{pnl_sign}{metrics["pnl_pct"]}%</div>
      <div class="metric-sub {pnl_class}">{pnl_amt_sign}{metrics["pnl_amount"]}만원</div>
    </div>
    <div class="metric">
      <div class="metric-label">투자금</div>
      <div class="metric-value">{metrics["invest_man"]:,}만원</div>
      <div class="metric-sub">추가 의향 {metrics["add_invest_man"]:,}만원</div>
    </div>
    <div class="metric">
      <div class="metric-label">손절선까지</div>
      <div class="metric-value {sl_class}">{metrics["sl_gap"]}%</div>
      <div class="metric-sub">{metrics["sl_price"]}원 이탈 시 손절</div>
    </div>
  </div>

  <div class="loss-section">
    <div class="section-label">손실 여유 (최대 -10%까지 허용)</div>
    <div class="loss-bar-bg">
      <div class="loss-bar-fill" style="width: {metrics["loss_used_pct"]}%"></div>
    </div>
    <div class="loss-label">
      <span>현재 {metrics["pnl_pct"]}% 사용</span>
      <span>한도 -10%</span>
    </div>
  </div>

  <div class="card">
    <div class="card-title" style="margin-bottom:10px;">➕ 추가매수 시뮬레이션</div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="color:var(--text2);font-size:11px;border-bottom:1px solid var(--border);">
          <th style="text-align:left;padding:5px 0;font-weight:500;">시나리오</th>
          <th style="text-align:right;padding:5px 0;font-weight:500;">평균단가</th>
          <th style="text-align:right;padding:5px 0;font-weight:500;">현재 손익</th>
        </tr>
      </thead>
      <tbody style="line-height:2.2;">
        <tr>
          <td style="color:var(--text2);">현재 (매수 없음)</td>
          <td style="text-align:right;font-weight:600;">{metrics["buy_price"]}원</td>
          <td style="text-align:right;" class="{pnl_class}">{pnl_sign}{metrics["pnl_pct"]}%</td>
        </tr>
        <tr>
          <td style="color:var(--text2);">1차 +{metrics["add1_man"]:,}만원</td>
          <td style="text-align:right;font-weight:600;">{metrics["avg1"]}원</td>
          <td style="text-align:right;" class="{'up' if metrics['avg1_pnl']>=0 else 'down'}">{'+' if metrics['avg1_pnl']>=0 else ''}{metrics["avg1_pnl"]}%</td>
        </tr>
        <tr>
          <td style="color:var(--text2);">1+2차 +{metrics["add_invest_man"]:,}만원</td>
          <td style="text-align:right;font-weight:600;">{metrics["avg2"]}원</td>
          <td style="text-align:right;" class="{'up' if metrics['avg2_pnl']>=0 else 'down'}">{'+' if metrics['avg2_pnl']>=0 else ''}{metrics["avg2_pnl"]}%</td>
        </tr>
      </tbody>
    </table>
    <div style="margin-top:8px;font-size:11px;color:var(--text3);">* 추가매수는 현재 기준가({metrics["current_price"]:.2f}원) 기준으로 계산 / KB앱에서 확인 후 설정.json에 업데이트</div>
  </div>

  <div class="card">
    <div class="card-title" style="margin-bottom:10px;">🎯 목표수익률 계산기</div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="color:var(--text2);font-size:11px;border-bottom:1px solid var(--border);">
          <th style="text-align:left;padding:5px 0;font-weight:500;">목표 수익률</th>
          <th style="text-align:right;padding:5px 0;font-weight:500;">필요 기준가</th>
          <th style="text-align:right;padding:5px 0;font-weight:500;">필요 NIFTY</th>
          <th style="text-align:right;padding:5px 0;font-weight:500;">수익금</th>
        </tr>
      </thead>
      <tbody style="line-height:2.2;">
        {exit_rows}
      </tbody>
    </table>
    <div style="margin-top:8px;font-size:11px;color:var(--text3);">* 매수단가 {metrics["buy_price"]}원 기준 / NIFTY는 비례 추정치</div>
  </div>

  <hr class="divider">

  {events_html}

  <div class="section-label">매매 신호</div>
  <div class="card">
    <div class="card-title" style="margin-bottom:8px;">📡 기술적 지표 (자동)</div>
    {tech_signals_html}
  </div>
  {news_card_html}

  <hr class="divider">

  <div class="section-label">액션 가이드</div>
  {action_guide_html}

  <hr class="divider">

  <div class="section-label">AI 매매 판단 질문</div>
  <div class="card">
    <div class="card-title">지금 상황 물어보기</div>
    <div id="key-setup" style="margin-bottom:10px;display:none;">
      <div style="font-size:12px;color:var(--text3);margin-bottom:6px;">Anthropic API 키를 입력하면 저장됩니다 (이 기기에만)</div>
      <div class="input-row">
        <input type="password" id="api-key-input" placeholder="sk-ant-...">
        <button class="btn" onclick="saveKey()">저장</button>
      </div>
    </div>
    <div class="input-row">
      <input type="text" id="ai-q" placeholder="예: 지금 사도 될까요?">
      <button class="btn" onclick="askAI()">분석 ↗</button>
    </div>
    <div class="quick-btns">
      <button class="btn quick-btn" onclick="setQ('지금 1차 매수 타이밍인가요?')">1차 매수?</button>
      <button class="btn quick-btn" onclick="setQ('지금 보유가 맞나요 매도해야 하나요?')">보유 vs 매도</button>
      <button class="btn quick-btn" onclick="setQ('이번 주 인도 시장 핵심 이슈가 뭔가요?')">이번 주 이슈</button>
      <button class="btn quick-btn" onclick="toggleKeySetup()">🔑 키 변경</button>
    </div>
    <div class="ai-response" id="ai-resp">질문을 입력하거나 위 버튼을 눌러보세요.</div>
  </div>

  <div class="footer">
    마지막 업데이트: {updated_at}
    <br><br>
    <button onclick="location.reload(true)" style="margin-top:4px;padding:8px 24px;border-radius:20px;border:0.5px solid var(--border);background:var(--card-bg);color:var(--text);font-size:13px;font-weight:500;cursor:pointer;">🔄 새로고침</button>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const isDark = matchMedia('(prefers-color-scheme: dark)').matches;
const tC = isDark ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.4)';
const gC = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)';

function calcMA(prices, n) {{
  return prices.map((_, i) => {{
    if (i < n - 1) return null;
    const slice = prices.slice(i - n + 1, i + 1);
    return Math.round(slice.reduce((a, b) => a + b, 0) / n);
  }});
}}

// 기간별 이평 설정
const MA_CONFIG = {{
  d1:  [{{n:5, color:'#FF6B6B',label:'MA5'}}, {{n:20,color:'#FFA500',label:'MA20'}}, {{n:60,color:'#9B59B6',label:'MA60'}}],
  d5:  [{{n:3, color:'#FF6B6B',label:'MA3'}}, {{n:5, color:'#FFA500',label:'MA5'}},  {{n:10,color:'#9B59B6',label:'MA10'}}],
  d30: [{{n:5, color:'#FF6B6B',label:'MA5'}}, {{n:10,color:'#FFA500',label:'MA10'}}, {{n:20,color:'#9B59B6',label:'MA20'}}],
  mo3: [{{n:4, color:'#FF6B6B',label:'MA4주'}},{{n:8, color:'#FFA500',label:'MA8주'}},{{n:13,color:'#9B59B6',label:'MA13주'}}],
  mo6: [{{n:5, color:'#FF6B6B',label:'MA5주'}},{{n:13,color:'#FFA500',label:'MA13주'}},{{n:26,color:'#9B59B6',label:'MA26주'}}],
  yr1: [{{n:5, color:'#FF6B6B',label:'MA5주'}},{{n:13,color:'#FFA500',label:'MA13주'}},{{n:26,color:'#9B59B6',label:'MA26주'}},{{n:52,color:'#888',label:'MA52주'}}],
}};
let currentPeriodKey = 'd1';

function makeDatasets(prices, periodKey, name, sl) {{
  const n = prices.length;
  const maCfg = MA_CONFIG[periodKey] || MA_CONFIG.yr1;
  const periods = maCfg.filter(p => p.n < n);
  const maDatasets = periods.map(p => ({{
    label: p.label, data: calcMA(prices, p.n),
    borderColor: p.color, borderWidth: 1.2,
    pointRadius: 0, fill: false, tension: 0.3, spanGaps: false
  }}));
  const datasets = [
    {{ label: name || '지수', data: prices, borderColor: '#378ADD',
       backgroundColor: 'rgba(55,138,221,0.06)', borderWidth: 2,
       pointRadius: 0, pointHoverRadius: 4, fill: true, tension: 0.3 }},
    ...maDatasets
  ];
  if (sl != null) {{
    datasets.splice(1, 0, {{
      label: '손절선', data: Array(n).fill(sl), borderColor: '#E24B4A',
      borderWidth: 1.2, borderDash: [5,4], pointRadius: 0, fill: false
    }});
  }}
  return datasets;
}}

function initChart(canvasId, pdata, initKey) {{
  return new Chart(document.getElementById(canvasId), {{
    type: 'line',
    data: {{ labels: pdata[initKey].labels, datasets: makeDatasets(pdata[initKey].prices, initKey, pdata.name, pdata.sl) }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{
          display: true, position: 'top',
          labels: {{ color: tC, font: {{ size: 10 }}, boxWidth: 20, padding: 8,
                     filter: item => item.text !== '손절선' }}
        }},
        tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + (ctx.parsed.y ? ctx.parsed.y.toLocaleString() : '-') }} }}
      }},
      scales: {{
        x: {{ ticks: {{ color: tC, font: {{ size: 10 }}, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }}, grid: {{ color: gC }} }},
        y: {{ ticks: {{ color: tC, font: {{ size: 10 }}, callback: v => v.toLocaleString() }}, grid: {{ color: gC }} }}
      }}
    }}
  }});
}}

function switchChart(canvasId, prefix, key, el) {{
  document.querySelectorAll(`#${{prefix}}-tabs .period-tab`).forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  const c = window._charts[canvasId];
  c.inst.data.labels = c.data[key].labels;
  c.inst.data.datasets = makeDatasets(c.data[key].prices, key, c.data.name, c.data.sl);
  c.inst.update();
}}

function getKey() {{ return localStorage.getItem('anthropic_api_key') || ''; }}
function toggleKeySetup() {{
  const el = document.getElementById('key-setup');
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}}
function saveKey() {{
  const k = document.getElementById('api-key-input').value.trim();
  if (!k) return;
  localStorage.setItem('anthropic_api_key', k);
  document.getElementById('api-key-input').value = '';
  document.getElementById('key-setup').style.display = 'none';
  document.getElementById('ai-resp').textContent = 'API 키가 저장됐어요. 질문을 입력해보세요.';
}}
window.addEventListener('DOMContentLoaded', function() {{
  if (!getKey()) document.getElementById('key-setup').style.display = 'block';
}});

function setQ(q) {{ document.getElementById('ai-q').value = q; }}

async function askAI() {{
  const q = document.getElementById('ai-q').value.trim();
  if (!q) return;
  const API_KEY = getKey();
  if (!API_KEY) {{
    document.getElementById('key-setup').style.display = 'block';
    document.getElementById('ai-resp').textContent = 'API 키를 먼저 입력해주세요.';
    return;
  }}
  const box = document.getElementById('ai-resp');
  box.textContent = '분석 중...';

  const ctx = `당신은 10년차 인도 펀드 매니저입니다.
포트폴리오: KB스타 NIFTY50 인덱스 (H) S
매수 평균단가: {metrics["buy_price"]}원 / 현재 기준가: {metrics["current_price"]:.2f}원 / 손익: {pnl_sign}{metrics["pnl_pct"]}%
투자금: {metrics["invest_man"]:,}만원 / 추가 투자 예정: {metrics["add_invest_man"]:,}만원
손절 기준: 기준가 {metrics["sl_price"]}원 이탈

[실시간 시장 데이터 — {updated_at} 기준]
- NIFTY50: {nifty["current"]:,} ({'▲' if nifty["change_pct"]>=0 else '▼'}{abs(nifty["change_pct"])}%)
- USD/INR: ₹{macro.get("usdinr","?")} / India VIX: {macro.get("india_vix","?")} / US VIX: {macro.get("vix","?")}
- 브렌트유: ${macro.get("crude","?")} / NIFTY P/E: {macro.get("nifty_pe","?")}
- FII: {(news or {}).get("FII", {}).get("text","정보없음")} / DII: {(news or {}).get("DII", {}).get("text","정보없음")}
- RBI 금리: {(news or {}).get("RBI", {}).get("text","정보없음")} / 미국 연준: {(news or {}).get("fed", {}).get("text","정보없음")}
- 인도 CPI: {(news or {}).get("cpi", {}).get("text","정보없음")} / PMI: {(news or {}).get("pmi", {}).get("text","정보없음")}
- 미-인도 무역: {(news or {}).get("trade", {}).get("text","정보없음")} / 중동: {(news or {}).get("mideast", {}).get("text","정보없음")}

3~5문장, 한국어, 마지막에 "이 답변은 참고용입니다" 짧게 명시.`;

  try {{
    const r = await fetch('https://api.anthropic.com/v1/messages', {{
      method: 'POST',
      headers: {{
        'Content-Type': 'application/json',
        'x-api-key': API_KEY,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true'
      }},
      body: JSON.stringify({{
        model: 'claude-sonnet-4-6',
        max_tokens: 600,
        system: ctx,
        messages: [{{ role: 'user', content: q }}]
      }})
    }});
    const d = await r.json();
    if (d.content?.[0]?.text) {{
      box.textContent = d.content[0].text;
    }} else {{
      box.textContent = '오류: ' + JSON.stringify(d.error || d);
    }}
  }} catch(e) {{
    box.textContent = '네트워크 오류: ' + e.message;
  }}
}}

document.getElementById('ai-q').addEventListener('keydown', e => {{
  if (e.key === 'Enter') askAI();
}});

// 차트 초기화 (Chart.js 로딩 완료 후 실행)
window._charts = {{}};
const PDATA_chartNifty = {nifty_periods_js};
const PDATA_chartSensex = {sensex_periods_js};
window._charts['chartNifty'] = {{inst: initChart('chartNifty', PDATA_chartNifty, 'd1'), data: PDATA_chartNifty}};
window._charts['chartSensex'] = {{inst: initChart('chartSensex', PDATA_chartSensex, 'd1'), data: PDATA_chartSensex}};

// 기준가 차트 (이평선 포함)
const PDATA_chartNav = {nav_periods_js};
window._charts['chartNav'] = {{inst: initChart('chartNav', PDATA_chartNav, 'yr1'), data: PDATA_chartNav}};

function switchNavChart(key, el) {{
  document.querySelectorAll('#nav-tabs .period-tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  const c = window._charts['chartNav'];
  c.inst.data.labels = c.data[key].labels;
  c.inst.data.datasets = makeDatasets(c.data[key].prices, 'd30', c.data.name, c.data.sl);
  c.inst.update();
}}

// 페이지 열릴 때 신호 점수 재계산 + 실제 수치 기반 설명 생성
(function() {{
  const bmap = {{'badge-g': 1, 'badge-r': -1, 'badge-y': 0, 'badge-b': 0}};
  function sg(group) {{
    return [...document.querySelectorAll(`[data-sg="${{group}}"]`)].reduce((s, el) => {{
      for (const [c, v] of Object.entries(bmap)) if (el.classList.contains(c)) return s + v;
      return s;
    }}, 0);
  }}
  function cls(id) {{
    const el = document.getElementById(id); if (!el) return '';
    for (const c of ['badge-g','badge-r','badge-y','badge-b']) if (el.classList.contains(c)) return c;
    return '';
  }}
  function txt(id) {{ const el = document.getElementById(id); return el ? el.textContent : ''; }}

  const techBadges  = document.querySelectorAll('[data-sg="tech"]').length  || 7;
  const macroBadges = document.querySelectorAll('[data-sg="macro"]').length || 5;
  const newsBadges  = document.querySelectorAll('[data-sg="news"]').length  || 8;
  const ts = sg('tech')  * 1.5;
  const ms = sg('macro') * 1.0;
  const ns = sg('news')  * 0.8;
  const total = ts + ms + ns;
  const maxS = techBadges*1.5 + macroBadges*1.0 + newsBadges*0.8;
  const pct = Math.max(0, Math.min(100, Math.round((total + maxS) / (2*maxS) * 100)));

  let label, color, bg;
  if      (total >= maxS*0.5)  {{ label='강매수';    color='#2d6a0a'; bg='#e8fde8'; }}
  else if (total >= maxS*0.15) {{ label='매수';       color='#2d8a4e'; bg='#f0faf0'; }}
  else if (total >= -maxS*0.15){{ label='보유';       color='#BA7517'; bg='#fff8e1'; }}
  else if (total >= -maxS*0.5) {{ label='매도 검토';  color='#c0392b'; bg='#fff0f0'; }}
  else                          {{ label='강매도';    color='#9b2020'; bg='#fde8e8'; }}

  const emojiMap = {{'강매수':'🔥 강매수','매수':'🟢 매수','보유':'📌 보유','매도 검토':'⚠️매도 검토','강매도':'🔴 강매도'}};
  const scEmoji = document.getElementById('sc-emoji');
  const scPct   = document.getElementById('sc-pct');
  const scBar   = document.getElementById('sc-bar');
  const scTech  = document.getElementById('sc-tech');
  const scMacro = document.getElementById('sc-macro');
  const scNews  = document.getElementById('sc-news');
  const scDesc  = document.getElementById('sc-desc');
  if (scEmoji) {{ scEmoji.textContent = emojiMap[label] || label; scEmoji.style.color = color; }}
  if (scPct)   {{ scPct.textContent = pct+'점'; scPct.style.color = color; }}
  if (scBar)   {{ scBar.style.width = pct+'%'; scBar.style.background = color; }}
  const fmt = v => (v>=0?'+':'')+v.toFixed(1);
  if (scTech)  {{ scTech.textContent  = fmt(ts);  scTech.style.color  = color; }}
  if (scMacro) {{ scMacro.textContent = fmt(ms); scMacro.style.color = color; }}
  if (scNews)  {{ scNews.textContent  = fmt(ns);  scNews.style.color  = color; }}

  // 실제 수치 읽기
  const rsiTxt  = txt('ind-rsi');
  const maTxt   = txt('ind-ma');
  const momTxt  = txt('ind-mom');
  const slTxt   = txt('ind-sl');
  const inrTxt  = txt('ind-usdinr');
  const fiiTxt  = txt('ind-fii');
  const cpiTxt  = txt('ind-cpi');
  const pmiTxt  = txt('ind-pmi');
  const ivixTxt = txt('ind-ivix');

  const isBad  = id => cls(id) === 'badge-r';
  const isGood = id => cls(id) === 'badge-g';
  const isYel  = id => cls(id) === 'badge-y';

  // 긍정/부정 요인 수집
  const goodFactors = [];
  const badFactors  = [];
  if (isGood('ind-rsi'))    goodFactors.push(`RSI(${{rsiTxt}})`);
  else if (isBad('ind-rsi')) badFactors.push(`RSI(${{rsiTxt}})`);
  if (isGood('ind-ma'))     goodFactors.push(`이평선 ${{maTxt}}`);
  else if (isBad('ind-ma')) badFactors.push(`이평선 ${{maTxt}}`);
  if (isGood('ind-mom'))    goodFactors.push(`모멘텀 ${{momTxt}}`);
  else if (isBad('ind-mom')) badFactors.push(`모멘텀 ${{momTxt}}`);
  if (isGood('ind-fii'))    goodFactors.push(`FII 외국인 순매수(${{fiiTxt}})`);
  else if (isBad('ind-fii')) badFactors.push(`FII 외국인 순매도(${{fiiTxt}})`);
  if (isGood('ind-usdinr')) goodFactors.push(`루피 안정(${{inrTxt}})`);
  else if (isBad('ind-usdinr')) badFactors.push(`루피 약세(${{inrTxt}})`);
  if (isGood('ind-cpi'))    goodFactors.push(`물가 안정(${{cpiTxt}})`);
  else if (isBad('ind-cpi')) badFactors.push(`물가 압박(${{cpiTxt}})`);
  if (isGood('ind-pmi'))    goodFactors.push(`PMI 호조(${{pmiTxt}})`);
  else if (isBad('ind-pmi')) badFactors.push(`PMI 약세(${{pmiTxt}})`);
  if (isGood('ind-ivix'))   goodFactors.push(`India VIX 안정(${{ivixTxt}})`);
  else if (isBad('ind-ivix')) badFactors.push(`India VIX 급등(${{ivixTxt}})`);

  let desc = '';
  if (label === '강매수') {{
    desc = `기술·매크로·뉴스 신호가 전반적으로 긍정적입니다. `
         + (goodFactors.length ? goodFactors.slice(0,4).join(', ') + ' 신호가 동시에 켜진 강한 매수 구간입니다. ' : '')
         + `분할 매수를 적극 고려하세요. 손절: ${{slTxt}}.`;
  }} else if (label === '매수') {{
    desc = `기술적 흐름이 개선 중입니다. `
         + (goodFactors.length ? '✅ ' + goodFactors.join(', ') + '. ' : '')
         + (badFactors.length ? '⚠️ ' + badFactors.join(', ') + ' 리스크 잔존. ' : '')
         + `소규모 선진입 후 신호 강화 시 추가 매수로 대응하세요. 손절: ${{slTxt}}.`;
  }} else if (label === '보유') {{
    desc = (goodFactors.length ? `✅ ${{goodFactors.join(', ')}} 긍정적이나, ` : `신호가 혼재합니다. `)
         + (badFactors.length ? `⚠️ ${{badFactors.join(', ')}} 부담이 남아 있어 추가 매수보다 현 포지션 유지가 유리합니다. ` : '')
         + `손절선 ${{slTxt}} 유지하며 관망하세요.`;
  }} else if (label === '매도 검토') {{
    desc = `부정 신호가 우세합니다. `
         + (badFactors.length ? '⚠️ ' + badFactors.join(', ') + ' 상태입니다. ' : '')
         + (goodFactors.length ? `(긍정 요인: ${{goodFactors.join(', ')}}) ` : '')
         + `${{slTxt}} — 손절 기준 재확인 후 비중 축소를 고려하세요.`;
  }} else {{
    desc = `복수의 위험 신호가 동시에 켜져 있습니다. `
         + (badFactors.length ? badFactors.join(', ') + ' 모두 부정적입니다. ' : '')
         + `비중 축소 또는 현금 보유를 우선 고려하고 ${{slTxt}} 이탈 시 즉시 대응하세요.`;
  }}
  if (scDesc) scDesc.textContent = desc;
}})();
</script>
</body>
</html>"""
    return html

# ── 카카오 알림 ──────────────────────────────────────────────────

def kakao_refresh_access_token(rest_api_key, refresh_token, client_secret=None):
    params = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        params["client_secret"] = client_secret
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        "https://kauth.kakao.com/oauth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        result = json.loads(r.read())
    if "access_token" not in result:
        raise RuntimeError(f"토큰 갱신 실패: {result}")
    return result["access_token"]


def kakao_send(access_token, text):
    template = json.dumps({
        "object_type": "text",
        "text": text,
        "link": {"web_url": "", "mobile_web_url": ""},
    }, ensure_ascii=False)
    data = urllib.parse.urlencode({"template_object": template}).encode()
    req = urllib.request.Request(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        data=data,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        result = json.loads(r.read())
    if result.get("result_code") != 0:
        raise RuntimeError(f"메시지 전송 실패: {result}")
    print("✅ 카카오 알림 전송 완료")


def generate_ai_commentary(nifty, metrics, indicators, macro, api_key):
    if not api_key:
        return ""
    from datetime import timezone, timedelta
    KST = timezone(timedelta(hours=9))
    now_str = datetime.now(KST).strftime("%H:%M")
    ind = indicators or {}
    mac = macro or {}
    nav = metrics.get("current_price", 0)
    pnl = metrics.get("pnl_pct", 0)
    prompt = f"""당신은 인도 펀드 투자 어시스턴트입니다.
아래 현재 데이터를 보고, 투자자가 알아야 할 특이사항이나 흐름 변화가 있으면 2~3문장으로 한국어로 코멘트해주세요.
특이사항이 전혀 없으면 "특이사항 없음"이라고만 답하세요.
마지막 줄에는 반드시 지금 해야 할 행동을 아래 형식으로 한 줄 추가하세요:
👉 [매수 / 매도 / 관망] — 이유 한 줄

[현재 데이터]
- NIFTY50: {nifty['current']:,} ({nifty['change_pct']:+}%)
- 기준가: {nav:.0f}원 / 손익: {pnl:+.1f}%
- RSI(14주): {ind.get('rsi', '?')}
- 이평 배열: {ind.get('ma_signal', '?')}
- 4주 모멘텀: {ind.get('momentum', 0):+.1f}%
- India VIX: {mac.get('vix', '?')}
- USD/INR: {mac.get('usdinr', '?')}
- 브렌트유: ${mac.get('crude', '?')}

반드시 짧게, 핵심만 말해주세요."""
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={"Content-Type": "application/json",
                     "x-api-key": api_key,
                     "anthropic-version": "2023-06-01"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
        comment = result["content"][0]["text"].strip()
        if "특이사항 없음" in comment:
            return ""
        msg = (f"📊 인도펀드 {now_str}\n"
               f"NIFTY {nifty['current']:,} ({nifty['change_pct']:+}%)\n"
               f"기준가 {nav:.0f}원 / 손익 {pnl:+.1f}%\n"
               f"💬 {comment}")
        return msg
    except Exception as e:
        print(f"AI 코멘트 생성 실패: {e}")
        return ""


def check_action_guide_achievement(nifty, metrics, indicators, macro, action_guide, api_key):
    if not api_key or not action_guide:
        return ""
    ind = indicators or {}
    mac = macro or {}
    nav = metrics.get("current_price", 0)
    pnl = metrics.get("pnl_pct", 0)
    ag = action_guide
    prompt = f"""당신은 인도 펀드 투자 어시스턴트입니다.
아래 [현재 데이터]와 [액션가이드]를 비교해서, 달성된 조건이 있으면 어떤 조건인지 한 문장으로 알려주세요.
달성된 조건이 없으면 "없음"이라고만 답하세요.

[현재 데이터]
- NIFTY50: {nifty['current']:,} ({nifty['change_pct']:+}%)
- 기준가: {nav:.0f}원 / 손익: {pnl:+.1f}%
- RSI(14주): {ind.get('rsi', '?')}
- 이평 배열: {ind.get('ma_signal', '?')}
- India VIX: {mac.get('vix', '?')}
- USD/INR: {mac.get('usdinr', '?')}

[액션가이드]
- 현재 상태: {ag.get('now', {}).get('desc', '')}
- 1차 매수 조건: {ag.get('buy1', {}).get('desc', '')}
- 2차 매수 조건: {ag.get('buy2', {}).get('desc', '')}
- 손절 조건: {ag.get('sell', {}).get('desc', '')}

달성된 조건만 간단히 알려주세요."""
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 200,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={"Content-Type": "application/json",
                     "x-api-key": api_key,
                     "anthropic-version": "2023-06-01"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
        answer = result["content"][0]["text"].strip()
        if "없음" in answer:
            return ""
        msg = f"🎯 [인도펀드] 액션가이드 조건 달성!\n{answer}\n대시보드에서 확인하세요."
        return msg
    except Exception as e:
        print(f"달성 체크 실패: {e}")
        return ""


# ── 메인 ────────────────────────────────────────────────────────
def main():
    cfg = load_config()

    try:
        nifty = fetch_nifty()
        print(f"NIFTY50 현재: {nifty['current']:,} ({'+' if nifty['change_pct']>=0 else ''}{nifty['change_pct']}%)")
    except Exception as e:
        print(f"데이터 가져오기 실패: {e}")
        print("인터넷 연결을 확인해주세요.")
        return

    metrics = calc_metrics(cfg, nifty["current"])
    # 환경변수 우선, 없으면 설정.json 사용 (GitHub Actions 호환)
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic_api_key", "")).strip()
    from datetime import timezone, timedelta
    KST = timezone(timedelta(hours=9))
    updated_at = datetime.now(KST).strftime("%Y.%m.%d %H:%M")

    sensex = fetch_sensex()
    print(f"SENSEX 현재: {sensex['current']:,} ({'+' if sensex['change_pct']>=0 else ''}{sensex['change_pct']}%)")

    print("매크로 지표 가져오는 중...")
    macro = fetch_macro_signals()

    newsapi_key = os.environ.get("NEWSAPI_KEY") or cfg.get("newsapi_key", "")
    print("뉴스 신호 수집 중...")
    news = fetch_news_signals(api_key, newsapi_key if newsapi_key else None)

    print("AI 차트 분석 생성 중...")
    nifty_analysis  = generate_chart_analysis(nifty, api_key)
    sensex_analysis = ""  # SENSEX는 참고용 차트만 제공, AI 분석 제외

    # 기준가 이력: 공공데이터 API 자동 → 없으면 설정.json 수동 데이터
    public_api_key = os.environ.get("PUBLIC_DATA_API_KEY") or cfg.get("공공데이터_api_key", "")
    if public_api_key:
        auto_history = fetch_fund_nav(public_api_key, days=400)
        if auto_history:
            nav_history = auto_history
            # 설정.json에도 저장 (오프라인 폴백용)
            cfg["기준가_이력"] = auto_history
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        else:
            nav_history = cfg.get("기준가_이력", [])
    else:
        nav_history = cfg.get("기준가_이력", [])

    nifty_ind = calc_indicators(nifty["yr1"]["prices"])
    events = cfg.get("주요이벤트", [])

    print("액션 가이드 생성 중...")
    action_guide = generate_action_guide(nifty, metrics, nifty_ind, macro, news, api_key, events=events)
    html = build_html(nifty, sensex, metrics, api_key, updated_at, nifty_analysis, sensex_analysis, nav_history=nav_history, indicators=nifty_ind, macro=macro, news=news, action_guide=action_guide, events=events)

    # TwelveData UI/JS 주입
    _td_ui = '''<div id="td-key-setup" style="background:#f8f9fa;border-radius:10px;padding:12px;margin-bottom:10px;">
      <div id="td-key-connected" style="display:none;font-size:12px;color:var(--text2);">✅ TwelveData 실시간 연동 중 &nbsp;<button onclick="document.getElementById('td-key-connected').style.display='none';document.getElementById('td-key-input-row').style.display='flex';" style="padding:4px 10px;background:#4f8cff;color:#fff;border:none;border-radius:6px;font-size:11px;cursor:pointer;">🔑 키 변경</button></div>
      <div id="td-key-input-row" style="display:none;flex-direction:column;gap:6px;">
        <div style="font-size:12px;color:var(--text2);">📡 실시간 시세 연동을 위해 <b>TwelveData API 키</b>가 필요해요 (<a href="https://twelvedata.com" target="_blank" style="color:var(--info-text)">twelvedata.com</a> 무료 가입)</div>
        <div style="display:flex;gap:8px;">
          <input type="password" id="td-key-input" placeholder="TwelveData API 키 입력" style="flex:1;padding:8px 10px;border:1px solid var(--border);border-radius:8px;font-size:13px;background:var(--card-bg);color:var(--text);">
          <button onclick="saveTDKey()" style="padding:8px 14px;background:#4f8cff;color:#fff;border:none;border-radius:8px;font-size:13px;cursor:pointer;">저장</button>
        </div>
      </div>
    </div>'''
    html = html.replace('<div id="key-setup"', _td_ui + '\n    <div id="key-setup"', 1)

    _td_js = r"""
function getTDKey() { return localStorage.getItem('twelvedata_api_key') || ''; }
function saveTDKey() {
  const k = document.getElementById('td-key-input')?.value.trim();
  if (!k) return;
  localStorage.setItem('twelvedata_api_key', k);
  document.getElementById('td-key-input').value = '';
  document.getElementById('td-key-connected').style.display = 'block';
  document.getElementById('td-key-input-row').style.display = 'none';
}
function initTDKeyUI() {
  const connected = document.getElementById('td-key-connected');
  const inputRow = document.getElementById('td-key-input-row');
  if (!connected || !inputRow) return;
  connected.style.display = 'block';
  inputRow.style.display = 'none';
}
async function fetchYahooProxy(ticker) {
  try {
    const target = encodeURIComponent(`https://query2.finance.yahoo.com/v8/finance/chart/${ticker}?interval=1d&range=1d`);
    const r = await fetch(`https://corsproxy.io/?${target}`);
    if (!r.ok) return null;
    const j = await r.json();
    const meta = j.chart.result[0].meta;
    const price = meta.regularMarketPrice;
    const prev = meta.chartPreviousClose || meta.previousClose || price;
    return { price, prev, pct: prev ? (price - prev) / prev * 100 : 0 };
  } catch(e) { return null; }
}
async function fetchLiveData() {
  const tickers = [
    { sym: 'NIFTY50', yf: '%5ENSEI' },
    { sym: 'USD/INR', yf: 'USDINR%3DX' },
    { sym: 'INDIA VIX', yf: '%5EINDIAVIX' },
    { sym: 'VIX', yf: '%5EVIX' },
    { sym: 'BCO/USD', yf: 'BZ%3DF' },
  ];
  const results = await Promise.all(tickers.map(t => fetchYahooProxy(t.yf)));
  const data = {};
  tickers.forEach((t, i) => { if (results[i]) data[t.sym] = results[i]; });

  const nifty = data['NIFTY50'];
  const usdinr = data['USD/INR'];
  const ivix = data['INDIA VIX'];
  const vix = data['VIX'];
  const brent = data['BCO/USD'];

  if (nifty) {
    const cur = Math.round(nifty.price).toLocaleString('ko-KR');
    const pct = nifty.pct;
    const el = document.getElementById('ind-niftysup');
    if (el) {
      if (nifty.price >= 24000) { el.className = 'badge badge-g'; el.textContent = `✓ ${cur} — 여유 있음`; }
      else if (nifty.price >= 23000) { el.className = 'badge badge-y'; el.textContent = `⚠ ${cur} — 지지선 근접`; }
      else { el.className = 'badge badge-r'; el.textContent = `✗ ${cur} — 23,000 이탈!`; }
    }
  }
  if (usdinr) {
    const el = document.getElementById('ind-usdinr');
    if (el) {
      const v = usdinr.price.toFixed(2);
      const p = usdinr.pct;
      if (p > 0.3) { el.className = 'badge badge-r'; el.textContent = `✗ ₹${v} — 루피 약세`; }
      else if (p < -0.3) { el.className = 'badge badge-g'; el.textContent = `✓ ₹${v} — 루피 강세`; }
      else { el.className = 'badge badge-y'; el.textContent = `→ ₹${v} — 보합`; }
    }
  }
  if (ivix) {
    const el = document.getElementById('ind-ivix');
    if (el) {
      const v = ivix.price.toFixed(1);
      if (ivix.price < 15) { el.className = 'badge badge-g'; el.textContent = `✓ VIX ${v} — 안정`; }
      else if (ivix.price < 20) { el.className = 'badge badge-y'; el.textContent = `→ VIX ${v} — 주의`; }
      else { el.className = 'badge badge-r'; el.textContent = `✗ VIX ${v} — 공포`; }
    }
  }
  if (vix) {
    const el = document.getElementById('ind-vix');
    if (el) {
      const v = vix.price.toFixed(1);
      if (vix.price < 20) { el.className = 'badge badge-g'; el.textContent = `✓ US VIX ${v}`; }
      else if (vix.price < 30) { el.className = 'badge badge-y'; el.textContent = `→ US VIX ${v}`; }
      else { el.className = 'badge badge-r'; el.textContent = `✗ US VIX ${v}`; }
    }
  }
  if (brent) {
    const el = document.getElementById('ind-crude');
    if (el) {
      const v = brent.price.toFixed(1);
      if (brent.price < 80) { el.className = 'badge badge-g'; el.textContent = `✓ 브렌트 $${v}`; }
      else if (brent.price < 90) { el.className = 'badge badge-y'; el.textContent = `→ 브렌트 $${v}`; }
      else { el.className = 'badge badge-r'; el.textContent = `✗ 브렌트 $${v} — 고유가`; }
    }
  }
  return data;
}
async function updateActionGuide() {
  const API_KEY = getKey();
  if (!API_KEY) return;
  const status = document.getElementById('ag-status');
  if (status) status.textContent = '⟳ AI 분석 중...';
  const td = await fetchTDData(['NIFTY50', 'USD/INR', 'INDIA VIX', 'VIX', 'BCO/USD']).catch(() => ({}));
  const fmt = (sym, d=0) => td[sym] ? td[sym].price.toLocaleString('ko-KR', {maximumFractionDigits:d}) : '-';
  const pct = sym => td[sym] ? `${td[sym].pct >= 0 ? '▲' : '▼'}${Math.abs(td[sym].pct).toFixed(2)}%` : '';
  const ctx = `당신은 10년차 인도 주식 펀드 매니저입니다.\n현재 상황: KB스타 NIFTY50 인덱스 펀드 보유 중\n매수단가: 797.6원 / 손절기준가: 718원\n\n[실시간 시장 데이터]\n- NIFTY50: ${fmt('NIFTY50')} (${pct('NIFTY50')})\n- USD/INR: ₹${fmt('USD/INR',2)} / India VIX: ${fmt('INDIA VIX',1)} / US VIX: ${fmt('VIX',1)}\n- 브렌트유: $${fmt('BCO/USD',1)}`;
  const prompt = `위 실시간 데이터를 바탕으로 지금 시점의 액션 가이드를 JSON으로 작성해주세요.\n반드시 아래 형식만 출력하세요 (다른 텍스트 없이):\n{"now_title":"...","now_desc":"...","buy1_title":"...","buy1_desc":"...","buy2_title":"...","buy2_desc":"...","sell_title":"...","sell_desc":"..."}`;
  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json', 'anthropic-dangerous-direct-browser-access': 'true' },
      body: JSON.stringify({ model: 'claude-haiku-4-5-20251001', max_tokens: 600, system: ctx, messages: [{ role: 'user', content: prompt }] })
    });
    const d = await res.json();
    const text = d.content?.[0]?.text || '';
    const match = text.match(/\{[\s\S]*\}/);
    if (match) {
      const g = JSON.parse(match[0]);
      if (g.now_title)  { document.getElementById('ag-now-title').textContent  = g.now_title;  document.getElementById('ag-now-desc').textContent  = g.now_desc; }
      if (g.buy1_title) { document.getElementById('ag-buy1-title').textContent = g.buy1_title; document.getElementById('ag-buy1-desc').textContent = g.buy1_desc; }
      if (g.buy2_title) { document.getElementById('ag-buy2-title').textContent = g.buy2_title; document.getElementById('ag-buy2-desc').textContent = g.buy2_desc; }
      if (g.sell_title) { document.getElementById('ag-sell-title').textContent = g.sell_title; document.getElementById('ag-sell-desc').textContent = g.sell_desc; }
      if (status) status.textContent = '✓ 방금 업데이트';
    } else { if (status) status.textContent = ''; }
  } catch(e) { if (status) status.textContent = ''; }
}
"""
    html = html.replace('function getKey()', _td_js + '\nfunction getKey()', 1)
    html = html.replace(
        "window.addEventListener('DOMContentLoaded', function() {\n  if (!getKey())",
        "window.addEventListener('DOMContentLoaded', function() {\n  initTDKeyUI();\n  fetchLiveData();\n  if (!getKey())",
        1
    )

    out_path = os.path.join(os.path.dirname(__file__), '인도펀드_대시보드.html')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    idx_path = os.path.join(os.path.dirname(__file__), 'index.html')
    with open(idx_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"\n대시보드 업데이트 완료!")
    print(f"파일 위치: {out_path}")
    print(f"손익: {'+' if metrics['pnl_pct']>=0 else ''}{metrics['pnl_pct']}% ({'+' if metrics['pnl_amount']>=0 else ''}{metrics['pnl_amount']}만원)")

    # ── 카카오 알림 발송 ──
    rest_api_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()

    if rest_api_key and refresh_token:
        try:
            access_token = kakao_refresh_access_token(rest_api_key, refresh_token, client_secret or None)
            print("✅ 카카오 토큰 갱신 완료")

            commentary = generate_ai_commentary(nifty, metrics, nifty_ind, macro, api_key)
            if commentary:
                kakao_send(access_token, commentary)
                print("✅ AI 코멘트 발송 완료")
            else:
                print("ℹ️ AI 코멘트: 특이사항 없음 — 발송 안 함")

            achievement = check_action_guide_achievement(nifty, metrics, nifty_ind, macro, action_guide, api_key)
            if achievement:
                kakao_send(access_token, achievement)
                print("✅ 액션가이드 달성 알림 발송 완료")
            else:
                print("ℹ️ 액션가이드: 달성 조건 없음 — 발송 안 함")

        except Exception as e:
            print(f"카카오 알림 오류: {e}")
    else:
        print("⚠️ KAKAO 환경변수 없음 — 알림 건너뜀")

    # 자동으로 브라우저에서 열기
    import webbrowser
    webbrowser.open(f'file://{out_path}')

if __name__ == '__main__':
    main()
