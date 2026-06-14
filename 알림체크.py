#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
인도 펀드 알림 체크 — 매일 GitHub Actions에서 실행
조건 충족 시 카카오톡 나에게 보내기로 알림 발송
"""

import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

import yfinance as yf

KST = timezone(timedelta(hours=9))
STATE_FILE = os.path.join(os.path.dirname(__file__), "알림상태.json")


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def already_sent(state, today, alert_key):
    return alert_key in state.get(today, [])


def mark_sent(state, today, alert_key):
    state.setdefault(today, [])
    if alert_key not in state[today]:
        state[today].append(alert_key)


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


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "설정.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_india_data():
    ticker = yf.Ticker("^NSEI")
    hist = ticker.history(period="1y", interval="1wk")
    prices = [float(row["Close"]) for _, row in hist.iterrows() if not row.isnull()["Close"]]

    current = prices[-1]
    prev = prices[-2] if len(prices) >= 2 else current

    ma5  = sum(prices[-5:])  / min(5,  len(prices))
    ma13 = sum(prices[-13:]) / min(13, len(prices))
    ma26 = sum(prices[-26:]) / min(26, len(prices))

    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else 0
    avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else 1
    rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss else 100

    prev_deltas = deltas[:-1]
    prev_gains  = [d for d in prev_deltas if d > 0]
    prev_losses = [-d for d in prev_deltas if d < 0]
    prev_avg_gain = sum(prev_gains[-14:]) / 14 if len(prev_gains) >= 14 else 0
    prev_avg_loss = sum(prev_losses[-14:]) / 14 if len(prev_losses) >= 14 else 1
    prev_rsi = 100 - (100 / (1 + prev_avg_gain / prev_avg_loss)) if prev_avg_loss else 100

    if ma5 > ma13 > ma26:
        ma_signal = "정배열"
    elif ma5 < ma13 < ma26:
        ma_signal = "역배열"
    else:
        ma_signal = "혼조"

    consecutive_down = 0
    for i in range(len(prices) - 1, 0, -1):
        if prices[i] < prices[i-1]:
            consecutive_down += 1
        else:
            break

    india_vix, us_vix, crude, usdinr = None, None, None, None
    try:
        india_vix = round(yf.Ticker("^INDIAVIX").fast_info.last_price, 1)
    except Exception:
        pass
    try:
        us_vix = round(yf.Ticker("^VIX").fast_info.last_price, 1)
    except Exception:
        pass
    try:
        crude = round(yf.Ticker("BZ=F").fast_info.last_price, 1)
    except Exception:
        pass
    try:
        usdinr = round(yf.Ticker("USDINR=X").fast_info.last_price, 2)
    except Exception:
        pass

    return {
        "current": round(current),
        "prev": round(prev),
        "rsi": round(rsi, 1),
        "prev_rsi": round(prev_rsi, 1),
        "ma5": round(ma5), "ma13": round(ma13), "ma26": round(ma26),
        "ma_signal": ma_signal,
        "india_vix": india_vix,
        "us_vix": us_vix,
        "crude": crude,
        "usdinr": usdinr,
        "consecutive_down": consecutive_down,
    }


def check_india_conditions(cfg, data):
    alerts = []
    nav = cfg.get("현재기준가", 0)
    buy_price = cfg.get("매수단가", 0)
    sl_price = cfg.get("손절기준가", 718)
    nifty = data["current"]
    rsi = data["rsi"]
    prev_rsi = data["prev_rsi"]
    india_vix = data["india_vix"]
    us_vix = data["us_vix"]
    crude = data["crude"]
    usdinr = data["usdinr"]
    ma_signal = data["ma_signal"]

    # ── 핵심 매수 조건 (1개라도 → 즉시 매수 알림) ──
    if nav > 0 and nav <= 765:
        alerts.append({"type": "매수핵심",
            "msg": f"🟢 [인도펀드] 매수 신호!\n기준가 {nav}원 → 765원 이하 진입\n지금 매수 검토하세요"})

    if prev_rsi > rsi and rsi <= 40 and prev_rsi >= 40:
        alerts.append({"type": "매수핵심",
            "msg": f"🟢 [인도펀드] 매수 신호!\nRSI {prev_rsi} → {rsi} 하락, 과매도 진입\n지금 매수 검토하세요"})

    if ma_signal == "정배열" and data.get("prev_ma_signal", "") != "정배열":
        alerts.append({"type": "매수핵심",
            "msg": f"🟢 [인도펀드] 매수 신호!\n이평선 정배열 전환 (NIFTY {nifty:,})\n지금 매수 검토하세요"})

    # ── 보조 매수 조건 (참고 알림) ──
    if rsi <= 40:
        alerts.append({"type": "매수참고", "msg": f"📊 [인도펀드] 참고: RSI {rsi} (과매도 구간)"})
    if nifty <= 24200:
        alerts.append({"type": "매수참고", "msg": f"📊 [인도펀드] 참고: NIFTY {nifty:,} (매수 기준가 이하)"})
    if india_vix and india_vix <= 20:
        alerts.append({"type": "매수참고", "msg": f"📊 [인도펀드] 참고: India VIX {india_vix} (시장 안정)"})
    if crude and crude <= 80:
        alerts.append({"type": "매수참고", "msg": f"📊 [인도펀드] 참고: 브렌트유 ${crude} (저유가 호재)"})
    if usdinr and usdinr <= 86:
        alerts.append({"type": "매수참고", "msg": f"📊 [인도펀드] 참고: USD/INR {usdinr} (루피 안정)"})

    # ── 매도 조건 ──
    if buy_price > 0 and nav > 0:
        gain_pct = (nav - buy_price) / buy_price * 100
        if gain_pct >= 25:
            alerts.append({"type": "매도",
                "msg": f"🟡 [인도펀드] 매도 신호!\n수익률 +{gain_pct:.1f}% (기준가 {nav}원)\n지금 매도하세요"})
        elif gain_pct >= 15:
            alerts.append({"type": "매도",
                "msg": f"🟡 [인도펀드] 매도 신호!\n수익률 +{gain_pct:.1f}% (기준가 {nav}원)\n1차 수익실현 검토"})
    if rsi >= 70:
        alerts.append({"type": "매도", "msg": f"🟡 [인도펀드] 매도 신호!\nRSI {rsi} 과매수\n매도 검토하세요"})

    # ── 손절 조건 ──
    if nav > 0 and nav <= sl_price:
        alerts.append({"type": "손절",
            "msg": f"🔴 [인도펀드] 손절 경고!\n기준가 {nav}원 → 손절선 {sl_price}원 이탈\n즉시 손절하세요"})
    if nifty <= 23000:
        alerts.append({"type": "손절",
            "msg": f"🔴 [인도펀드] 손절 경고!\nNIFTY {nifty:,} → 23,000 붕괴\n즉시 손절하세요"})
    if india_vix and india_vix >= 28:
        alerts.append({"type": "손절",
            "msg": f"🔴 [인도펀드] 경고!\nIndia VIX {india_vix} → 공포 구간\n포지션 점검 필요"})
    if us_vix and us_vix >= 30:
        alerts.append({"type": "손절",
            "msg": f"🔴 [인도펀드] 경고!\n미국 VIX {us_vix} → 글로벌 공포\n포지션 점검 필요"})
    if data["consecutive_down"] >= 3:
        alerts.append({"type": "손절",
            "msg": f"🔴 [인도펀드] 경고!\nNIFTY {data['consecutive_down']}주 연속 하락\n추세 점검 필요"})

    # ── 이벤트 알림 ──
    today = datetime.now().date()
    for ev in cfg.get("주요이벤트", []):
        try:
            ev_date = datetime.strptime(ev["날짜"], "%Y-%m-%d").date()
            diff = (ev_date - today).days
            if diff == 3:
                alerts.append({"type": "이벤트예고",
                    "msg": f"📅 [인도펀드] D-3 이벤트\n{ev['내용']} ({ev['날짜']})\n포지션 점검하세요"})
            elif diff == 0:
                alerts.append({"type": "이벤트당일",
                    "msg": f"📅 [인도펀드] 오늘 이벤트\n{ev['내용']}\n대시보드에서 결과 확인하세요"})
        except Exception:
            pass

    return alerts


def main():
    rest_api_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()

    if not rest_api_key or not refresh_token:
        print("⚠️  KAKAO 환경변수 없음 — 알림 건너뜀")
        return

    today = datetime.now(KST).strftime("%Y-%m-%d")
    state = load_state()

    print("카카오 토큰 갱신 중...")
    access_token = kakao_refresh_access_token(rest_api_key, refresh_token, client_secret or None)

    print("인도 펀드 데이터 수집 중...")
    cfg = load_config()
    data = fetch_india_data()
    print(f"NIFTY: {data['current']:,} | RSI: {data['rsi']} | 기준가: {cfg.get('현재기준가', '?')}원")

    alerts = check_india_conditions(cfg, data)
    if not alerts:
        print("✅ 알림 조건 없음")
        return

    priority = {"손절": 0, "매수핵심": 1, "매도": 2, "이벤트당일": 3, "이벤트예고": 4, "매수참고": 5}
    alerts.sort(key=lambda a: priority.get(a["type"], 99))

    sent_any = False
    for alert in alerts:
        key = alert["type"]
        if already_sent(state, today, key):
            print(f"  ⏭ 오늘 이미 보낸 알림 스킵: {key}")
            continue
        kakao_send(access_token, alert["msg"])
        mark_sent(state, today, key)
        sent_any = True
        print(f"  → {alert['type']}: {alert['msg'][:40]}...")

    if sent_any:
        save_state(state)


if __name__ == "__main__":
    main()
