"""
기상청 API 기반 오늘의 옷차림 추천 웹앱 - 로컬 서버 (app.py)

초보자 및 중학교 과학 수업 실습을 위해 파이썬 표준 라이브러리(http.server, urllib, json, datetime)만으로
구현된 가볍고 안전한 웹 서버입니다.

주요 기능:
1. key.txt 파일에서 기상청 API 인증키 읽기 (보안 유지 및 프론트 노출 방지)
2. 기상청 API(초단기실황, 단기예보) 호출 및 브라우저 CORS 문제 해결을 위한 프록시(중계) 역할
3. 어제 이맘때 관측, 지금 관측, 내일 아침 9시 예보 데이터를 하나로 취합하여 /api/weather 엔드포인트로 제공
4. 인증키가 없거나 API 오류(403 등) 발생 시 실습이 중단되지 않도록 친절한 안내와 함께 예시(Mock) 데이터 제공
5. 2주 날씨 예측 및 천체관측 적합도 계산 기능 제공
6. index.html 등 프론트엔드 정적 파일 서빙
"""

import http.server
import socketserver
import urllib.request
import urllib.parse
import urllib.error
import json
import os
import sys
from datetime import datetime, timedelta

# 로컬 웹 서버 포트 설정
PORT = 8000

# 기상청 API허브 베이스 URL
KMA_API_BASE = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0"

# 강수형태(PTY) 코드 한글 매핑
PTY_MAP = {
    "0": "없음",
    "1": "비",
    "2": "비/눈",
    "3": "눈",
    "5": "빗방울",
    "6": "진눈깨비",
    "7": "눈날림"
}

# SKY 코드를 숫자로 변환 (하늘상태)
SKY_MAP = {
    "1": "맑음",
    "3": "구름많음",
    "4": "흐림"
}


def calculate_stargazing_score(temp, humidity, wind_speed, pty_code, sky_code=None):
    """
    천체관측 적합도를 0~100점으로 계산합니다.
    조건:
    - 맑은 하늘 (구름 적음)
    - 낮은 습도 (60% 이하)
    - 약한 바람 (3m/s 이하)
    - 강수 없음
    """
    score = 100
    
    # 강수형태: 강수가 있으면 점수 감소
    pty = str(int(float(pty_code))) if pty_code else "0"
    if pty != "0":
        score -= 50  # 강수가 있으면 크게 감점
    
    # 하늘 상태: 구름이 많으면 감점
    if sky_code:
        sky = str(int(float(sky_code)))
        if sky == "4":  # 흐림
            score -= 40
        elif sky == "3":  # 구름많음
            score -= 20
    
    # 습도: 높을수록 감점 (60% 이상)
    hum = float(humidity) if humidity else 50
    if hum > 80:
        score -= 30
    elif hum > 60:
        score -= 15
    
    # 풍속: 바람이 강하면 감점
    wind = float(wind_speed) if wind_speed else 0
    if wind > 5:
        score -= 20
    elif wind > 3:
        score -= 10
    
    # 온도: 극단적인 온도는 관측 편안성 감소
    temp_val = float(temp) if temp else 15
    if temp_val < 0 or temp_val > 35:
        score -= 5
    
    return max(0, score)  # 최소 0점


def get_stargazing_recommendation(score):
    """점수에 따른 천체관측 추천도"""
    if score >= 80:
        return "매우 좋음 ⭐⭐⭐"
    elif score >= 60:
        return "좋음 ⭐⭐"
    elif score >= 40:
        return "보통 ⭐"
    else:
        return "좋지 않음 ✗"


def generate_14day_forecast(auth_key, nx, ny):
    """
    기상청 API에서 14일 단기예보 데이터를 가져와 천체관측 적합도를 계산합니다.
    """
    now_dt = datetime.now()
    vilage_base_date, vilage_base_time = get_vilage_fcst_base_time(now_dt)
    
    forecast_data = []
    
    try:
        fcst_resp = fetch_kma_api("getVilageFcst", {
            "pageNo": "1",
            "numOfRows": "1000",
            "dataType": "JSON",
            "base_date": vilage_base_date,
            "base_time": vilage_base_time,
            "nx": nx,
            "ny": ny,
            "authKey": auth_key
        })
        items = fcst_resp.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        
        # 날짜별로 데이터 그룹화 (21:00 기준 - 밤 관측 시간)
        date_data = {}
        for it in items:
            fcst_date = it.get("fcstDate")
            fcst_time = it.get("fcstTime")
            
            # 밤 9시(21:00) 데이터 수집
            if fcst_time == "2100" and fcst_date:
                if fcst_date not in date_data:
                    date_data[fcst_date] = {}
                
                cat = it.get("category")
                val = it.get("fcstValue")
                date_data[fcst_date][cat] = float(val) if val is not None else None
        
        # 최대 14일 데이터 생성
        for fcst_date in sorted(date_data.keys())[:14]:
            data = date_data[fcst_date]
            
            pty_code = str(int(data.get("PTY", 0)))
            sky_code = str(int(data.get("SKY", 1)))
            
            temp = data.get("TMP", 15.0)
            humidity = data.get("REH", 60.0)
            wind_speed = data.get("WSD", 1.0)
            
            score = calculate_stargazing_score(temp, humidity, wind_speed, pty_code, sky_code)
            
            forecast_data.append({
                "date": f"{fcst_date[:4]}-{fcst_date[4:6]}-{fcst_date[6:]}",
                "temp": temp,
                "humidity": humidity,
                "wind_speed": wind_speed,
                "pty": pty_code,
                "pty_text": PTY_MAP.get(pty_code, "정보없음"),
                "sky": sky_code,
                "sky_text": SKY_MAP.get(sky_code, "맑음"),
                "stargazing_score": score,
                "stargazing_recommendation": get_stargazing_recommendation(score)
            })
    
    except Exception as e:
        print(f"[경고] 14일 예보 조회 실패: {e}")
        # 실습용 Mock 14일 데이터
        for i in range(14):
            future_dt = now_dt + timedelta(days=i)
            date_str = future_dt.strftime("%Y-%m-%d")
            score = 70 - (i % 3) * 10  # 샘플 점수
            forecast_data.append({
                "date": date_str,
                "temp": 20.0 + (i % 5),
                "humidity": 60.0 + (i % 20),
                "wind_speed": 2.0 + (i % 3),
                "pty": "0",
                "pty_text": "없음",
                "sky": "1" if i % 3 != 2 else "3",
                "sky_text": "맑음" if i % 3 != 2 else "구름많음",
                "stargazing_score": score,
                "stargazing_recommendation": get_stargazing_recommendation(score)
            })
    
    return forecast_data


def get_api_key():
    """
    key.txt 파일에서 기상청 API 인증키를 읽어옵니다.
    주석(#)이나 빈 줄은 무시하며, 파일이 없거나 비어있으면 None을 반환합니다.
    """
    key_path = os.path.join(os.path.dirname(__file__), "key.txt")
    if not os.path.exists(key_path):
        return None
    try:
        with open(key_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines()]
            # 주석(#)이 아니고 비어있지 않은 실제 키 행 찾기
            valid_keys = [l for l in lines if l and not l.startswith("#")]
            if not valid_keys:
                return None
            key = valid_keys[0]
            # 예시 플레이스홀더 텍스트인 경우 무효 처리
            if key.startswith("YOUR_") or "<" in key:
                return None
            return key
    except Exception as e:
        print(f"[경고] key.txt 읽기 실패: {e}")
        return None


def get_ultra_srt_ncst_base_time(target_dt):
    """
    초단기실황(관측) 기준 시각 계산:
    - 매시 30분 발표, 40분경 제공됩니다.
    - 현재 분이 40분 미만이면 1시간 전 데이터를 요청합니다. (자정 넘김 자동 처리)
    """
    if target_dt.minute < 40:
        target_dt = target_dt - timedelta(hours=1)
    base_date = target_dt.strftime("%Y%m%d")
    base_time = target_dt.strftime("%H00")
    return base_date, base_time


def get_vilage_fcst_base_time(target_dt):
    """
    단기예보(예보) 기준 시각 계산:
    - 발표시각은 02, 05, 08, 11, 14, 17, 20, 23시 (각 시각 10분경 이후 제공)
    - 현재 시각보다 이전인 가장 최근 발표시각을 사용합니다.
    - 02시 10분 이전이면 전날 23시 발표를 사용합니다.
    """
    base_times = [2, 5, 8, 11, 14, 17, 20, 23]
    cur_hour = target_dt.hour
    cur_min = target_dt.minute

    # 02시 10분 이전이면 전날 23시 발표 데이터 사용
    if cur_hour < 2 or (cur_hour == 2 and cur_min < 10):
        prev_dt = target_dt - timedelta(days=1)
        return prev_dt.strftime("%Y%m%d"), "2300"

    # 당일 발표시각 중 가장 최근 시각 선택
    selected_hour = 2
    for h in base_times:
        if (cur_hour > h) or (cur_hour == h and cur_min >= 10):
            selected_hour = h

    return target_dt.strftime("%Y%m%d"), f"{selected_hour:02d}00"


def fetch_kma_api(endpoint, params):
    """
    기상청 API를 호출하고 JSON 결과를 파싱하여 반환합니다.
    파이썬 기본 요청 차단을 방지하기 위해 브라우저 형태의 User-Agent 헤더를 추가합니다.
    """
    query_string = urllib.parse.urlencode(params)
    url = f"{KMA_API_BASE}/{endpoint}?{query_string}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=7) as response:
        content = response.read().decode("utf-8")
        data = json.loads(content)

        # 기상청 API 자체 응답 코드 확인
        header = data.get("response", {}).get("header", {})
        result_code = header.get("resultCode", "00")
        result_msg = header.get("resultMsg", "NORMAL_SERVICE")

        if result_code != "00":
            if result_code in ["03", "30", "31", "32"] or "AUTH" in result_msg.upper() or "ACCESS" in result_msg.upper():
                raise PermissionError("활용신청을 확인하세요 (기상청 API허브 승인 및 인증키 확인 필요)")
            else:
                raise ValueError(f"기상청 API 오류 ({result_code}: {result_msg})")

        return data


def generate_mock_weather(nx, ny):
    """
    인증키가 없거나 API 통신 실패 시 제공할 모의(Mock) 날씨 데이터입니다.
    수업 실습 시 참가자들이 중단 없이 화면과 옷차림 추천 기능을 체험할 수 있게 합니다.
    """
    now_dt = datetime.now()
    yesterday_dt = now_dt - timedelta(days=1)
    tomorrow_dt = now_dt + timedelta(days=1)

    return {
        "mock": True,
        "message": "현재 key.txt에 유효한 기상청 API 인증키가 없어 '실습용 예시 데이터'로 동작 중입니다. key.txt 파일에 인증키를 입력하면 실시간 기상 데이터를 확인할 수 있습니다.",
        "nx": nx,
        "ny": ny,
        "yesterday": {
            "kind": "관측",
            "title": "어제 이맘때",
            "date": yesterday_dt.strftime("%Y-%m-%d"),
            "time": yesterday_dt.strftime("%H:00"),
            "baseDate": yesterday_dt.strftime("%Y%m%d"),
            "baseTime": yesterday_dt.strftime("%H00"),
            "T1H": 25.4,     # 기온 (℃)
            "REH": 68.0,     # 습도 (%)
            "WSD": 2.1,      # 풍속 (m/s)
            "RN1": 0.0,      # 1시간 강수량 (mm)
            "PTY": "0",      # 강수형태 코드
            "PTY_text": "없음",
            "VEC": 160.0     # 풍향 (deg)
        },
        "now": {
            "kind": "관측",
            "title": "지금",
            "date": now_dt.strftime("%Y-%m-%d"),
            "time": now_dt.strftime("%H:00"),
            "baseDate": now_dt.strftime("%Y%m%d"),
            "baseTime": now_dt.strftime("%H00"),
            "T1H": 27.2,     # 기온 (℃)
            "REH": 62.0,     # 습도 (%)
            "WSD": 2.8,      # 풍속 (m/s)
            "RN1": 0.0,      # 1시간 강수량 (mm)
            "PTY": "0",      # 강수형태 코드
            "PTY_text": "없음",
            "VEC": 190.0     # 풍향 (deg)
        },
        "tomorrow": {
            "kind": "예보",
            "title": "내일 아침 9시 (등교시간)",
            "date": tomorrow_dt.strftime("%Y-%m-%d"),
            "time": "09:00",
            "baseDate": now_dt.strftime("%Y%m%d"),
            "baseTime": "0800",
            "fcstDate": tomorrow_dt.strftime("%Y%m%d"),
            "fcstTime": "0900",
            "T1H": 23.5,     # 예보 기온 (TMP -> T1H로 통일, ℃)
            "REH": 75.0,     # 습도 (%)
            "WSD": 1.5,      # 풍속 (m/s)
            "POP": 30.0,     # 강수확률 (%)
            "PTY": "0",      # 강수형태 코드
            "PTY_text": "없음",
            "SKY": "3",      # 하늘상태 (3: 구름많음)
            "SKY_text": "구름많음"
        }
    }


def get_real_weather(auth_key, nx, ny):
    """
    기상청 API를 호출하여 [어제 실황, 지금 실황, 내일 아침 9시 예보]를 취합합니다.
    """
    now_dt = datetime.now()
    yesterday_dt = now_dt - timedelta(days=1)
    tomorrow_dt = now_dt + timedelta(days=1)
    tomorrow_fcst_date = tomorrow_dt.strftime("%Y%m%d")

    # 1. '지금' 초단기실황 기준시각 계산
    now_base_date, now_base_time = get_ultra_srt_ncst_base_time(now_dt)

    # 2. '어제 이맘때' 초단기실황 기준시각 계산 (현재 기준시각의 하루 전)
    yest_base_date = (datetime.strptime(now_base_date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    yest_base_time = now_base_time

    # 3. '단기예보' 기준시각 계산
    vilage_base_date, vilage_base_time = get_vilage_fcst_base_time(now_dt)

    result_data = {
        "mock": False,
        "message": "기상청 API로부터 실시간 기상 데이터를 성공적으로 수신했습니다.",
        "nx": nx,
        "ny": ny,
        "yesterday": None,
        "now": None,
        "tomorrow": None
    }

    # --- (1) 지금 초단기실황 조회 ---
    try:
        now_resp = fetch_kma_api("getUltraSrtNcst", {
            "pageNo": "1",
            "numOfRows": "100",
            "dataType": "JSON",
            "base_date": now_base_date,
            "base_time": now_base_time,
            "nx": nx,
            "ny": ny,
            "authKey": auth_key
        })
        items = now_resp.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]

        now_dict = {}
        for it in items:
            cat = it.get("category")
            val = it.get("obsrValue")
            now_dict[cat] = float(val) if val is not None else None

        pty_code = str(int(now_dict.get("PTY", 0)))
        result_data["now"] = {
            "kind": "관측",
            "title": "지금",
            "date": f"{now_base_date[:4]}-{now_base_date[4:6]}-{now_base_date[6:]}",
            "time": f"{now_base_time[:2]}:{now_base_time[2:]}",
            "baseDate": now_base_date,
            "baseTime": now_base_time,
            "T1H": now_dict.get("T1H", 20.0),
            "REH": now_dict.get("REH", 50.0),
            "WSD": now_dict.get("WSD", 1.0),
            "RN1": now_dict.get("RN1", 0.0),
            "PTY": pty_code,
            "PTY_text": PTY_MAP.get(pty_code, "정보없음"),
            "VEC": now_dict.get("VEC", 0.0)
        }
    except Exception as e:
        print(f"[오류] 지금 초단기실황 조회 실패: {e}")
        raise e

    # --- (2) 어제 초단기실황 조회 ---
    try:
        yest_resp = fetch_kma_api("getUltraSrtNcst", {
            "pageNo": "1",
            "numOfRows": "100",
            "dataType": "JSON",
            "base_date": yest_base_date,
            "base_time": yest_base_time,
            "nx": nx,
            "ny": ny,
            "authKey": auth_key
        })
        items = yest_resp.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]

        yest_dict = {}
        for it in items:
            cat = it.get("category")
            val = it.get("obsrValue")
            yest_dict[cat] = float(val) if val is not None else None

        pty_code = str(int(yest_dict.get("PTY", 0)))
        result_data["yesterday"] = {
            "kind": "관측",
            "title": "어제 이맘때",
            "date": f"{yest_base_date[:4]}-{yest_base_date[4:6]}-{yest_base_date[6:]}",
            "time": f"{yest_base_time[:2]}:{yest_base_time[2:]}",
            "baseDate": yest_base_date,
            "baseTime": yest_base_time,
            "T1H": yest_dict.get("T1H", 20.0),
            "REH": yest_dict.get("REH", 50.0),
            "WSD": yest_dict.get("WSD", 1.0),
            "RN1": yest_dict.get("RN1", 0.0),
            "PTY": pty_code,
            "PTY_text": PTY_MAP.get(pty_code, "정보없음"),
            "VEC": yest_dict.get("VEC", 0.0)
        }
    except Exception as e:
        print(f"[오류] 어제 초단기실황 조회 실패: {e}")
        result_data["yesterday"] = generate_mock_weather(nx, ny)["yesterday"]

    # --- (3) 내일 09시 단기예보 조회 ---
    try:
        fcst_resp = fetch_kma_api("getVilageFcst", {
            "pageNo": "1",
            "numOfRows": "1000",
            "dataType": "JSON",
            "base_date": vilage_base_date,
            "base_time": vilage_base_time,
            "nx": nx,
            "ny": ny,
            "authKey": auth_key
        })
        items = fcst_resp.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]

        # 내일 09시(등교시간) 데이터 필터링
        tmr_dict = {}
        for it in items:
            if it.get("fcstDate") == tomorrow_fcst_date and it.get("fcstTime") == "0900":
                cat = it.get("category")
                val = it.get("fcstValue")
                tmr_dict[cat] = float(val) if val is not None else None

        pty_code = str(int(tmr_dict.get("PTY", 0)))
        sky_code = str(int(tmr_dict.get("SKY", 1)))

        result_data["tomorrow"] = {
            "kind": "예보",
            "title": "내일 아침 9시 (등교시간)",
            "date": f"{tomorrow_fcst_date[:4]}-{tomorrow_fcst_date[4:6]}-{tomorrow_fcst_date[6:]}",
            "time": "09:00",
            "baseDate": vilage_base_date,
            "baseTime": vilage_base_time,
            "fcstDate": tomorrow_fcst_date,
            "fcstTime": "0900",
            # TMP(예보 기온)를 T1H로 이름을 통일하여 프론트엔드가 동일하게 처리하게 함
            "T1H": tmr_dict.get("TMP", 20.0),
            "REH": tmr_dict.get("REH", 60.0),
            "WSD": tmr_dict.get("WSD", 1.5),
            "POP": tmr_dict.get("POP", 0.0),
            "PTY": pty_code,
            "PTY_text": PTY_MAP.get(pty_code, "없음"),
            "SKY": sky_code,
            "SKY_text": SKY_MAP.get(sky_code, "맑음")
        }
    except Exception as e:
        print(f"[오류] 단기예보 조회 실패: {e}")
        result_data["tomorrow"] = generate_mock_weather(nx, ny)["tomorrow"]

    return result_data


class WeatherRequestHandler(http.server.SimpleHTTPRequestHandler):
    """
    HTTP 요청 처리 핸들러:
    - /api/weather 경로: 기상청 API 데이터 취합 및 JSON 응답 반환
    - /api/stargazing 경로: 14일 천체관측 적합도 예측 반환
    - 기타 경로: HTML, JS, CSS 등 정적 파일 서빙
    """
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)

        # 날씨 API 엔드포인트 처리
        if parsed_url.path == "/api/weather":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            # 부산 기본값 (nx: 98, ny: 76)
            nx = query_params.get("nx", ["98"])[0]
            ny = query_params.get("ny", ["76"])[0]

            auth_key = get_api_key()

            if not auth_key:
                # 인증키가 없는 경우 실습용 Mock 데이터 제공
                weather_data = generate_mock_weather(nx, ny)
            else:
                try:
                    weather_data = get_real_weather(auth_key, nx, ny)
                except PermissionError as pe:
                    weather_data = generate_mock_weather(nx, ny)
                    weather_data["message"] = f"활용신청을 확인하세요. ({str(pe)})"
                except urllib.error.HTTPError as e:
                    weather_data = generate_mock_weather(nx, ny)
                    if e.code == 403:
                        weather_data["message"] = "활용신청을 확인하세요. (403 인증 오류: API허브에서 '단기예보' 오픈API 활용신청 승인 상태와 인증키를 확인해주세요.)"
                    else:
                        weather_data["message"] = f"기상청 API HTTP 오류 ({e.code}): {e.reason}"
                except Exception as e:
                    weather_data = generate_mock_weather(nx, ny)
                    weather_data["message"] = f"기상청 API 호출 중 문제가 발생하여 예시 데이터로 대체합니다: {str(e)}"

            response_body = json.dumps(weather_data, ensure_ascii=False, indent=2).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
            return

        # 천체관측 14일 예보 엔드포인트 처리
        if parsed_url.path == "/api/stargazing":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            nx = query_params.get("nx", ["98"])[0]
            ny = query_params.get("ny", ["76"])[0]

            auth_key = get_api_key()

            try:
                if auth_key:
                    stargazing_data = generate_14day_forecast(auth_key, nx, ny)
                else:
                    stargazing_data = generate_14day_forecast(None, nx, ny)
            except Exception as e:
                print(f"[오류] 천체관측 예보 생성 실패: {e}")
                stargazing_data = generate_14day_forecast(None, nx, ny)

            response_body = json.dumps({
                "success": True,
                "data": stargazing_data,
                "message": "14일 천체관측 적합도 예보"
            }, ensure_ascii=False, indent=2).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
            return

        # 기본 웹 서빙 (index.html 등)
        return super().do_GET()


def run_server():
    # 스크립트가 위치한 디렉터리를 작업 디렉터리로 설정
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # 포트 재사용 허용 설정 (서버 재시작 시 Address already in use 방지)
    socketserver.TCPServer.allow_reuse_address = True

    with socketserver.TCPServer(("", PORT), WeatherRequestHandler) as httpd:
        print("=" * 60)
        print(f"🌦️  기상청 날씨 옷차림 추천 웹앱 서버가 실행되었습니다!")
        print(f"👉 브라우저 주소: http://localhost:{PORT}")
        print("=" * 60)
        print("💡 [알림] 종료하려면 키보드에서 Ctrl + C 를 누르세요.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n서버를 안전하게 종료합니다.")
            httpd.server_close()
            sys.exit(0)


if __name__ == "__main__":
    run_server()
