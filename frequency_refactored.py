"""
PLC 기반 주파수 및 전류 센서 데이터 수집 모듈

이 모듈은 Snap7 라이브러리를 사용하여 PLC에서 주파수(CV/SV)와 
전류 데이터를 실시간으로 수집하고 PostgreSQL 데이터베이스에 저장합니다.

Features:
    - Snap7 프로토콜로 PLC 통신
    - 실시간 센서 데이터 수집
    - 동적 상한/하한선 계산
    - 이상치 탐지

Requirements:
    - snap7
    - psycopg2
    - PostgreSQL database
    - python-dotenv
"""

import snap7
import snap7.util
import psycopg2
from time import sleep
from datetime import datetime
import os
from dotenv import load_dotenv

# ============================================================================
# 환경 설정
# ============================================================================

# 환경 변수에서 연결 정보 로드 (보안상 권장)
load_dotenv()

# PLC 연결 설정
PLC_IP = os.getenv("PLC_IP", "192.168.0.120")
PLC_RACK = int(os.getenv("PLC_RACK", 0))
PLC_SLOT = int(os.getenv("PLC_SLOT", 1))

# 데이터베이스 연결 설정
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "1234"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432")
}

# ============================================================================
# 연결 초기화
# ============================================================================

plc = snap7.client.Client()
try:
    plc.connect(PLC_IP, PLC_RACK, PLC_SLOT)
    print("✓ PLC 연결 성공")
except Exception as e:
    print(f"✗ PLC 연결 실패: {e}")

# 데이터베이스 연결 설정
conn = None
cursor = None
try:
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    print("✓ 데이터베이스 연결 성공")
except Exception as e:
    print(f"✗ 데이터베이스 연결 실패: {e}")

# 전역 상태
prev_current_cv = None


# ============================================================================
# 데이터 수집 및 저장 함수
# ============================================================================

def read_plc_data():
    """
    PLC에서 센서 데이터 읽기
    
    DB7: 센서 데이터 (offset 0: 전류, offset 2: 주파수_CV)
    DB4: 추가 센서 데이터 (offset 0: 주파수_SV)
    
    Returns:
        dict: {'current_cv': float, 'frequency_cv': float, 'frequency_sv': float}
    """
    try:
        buffer_db7 = plc.db_read(7, 0, 16)
        buffer_db4 = plc.db_read(4, 0, 2)

        current_cv = snap7.util.get_int(buffer_db7, 0) / 10
        frequency_cv = snap7.util.get_int(buffer_db7, 2) / 100
        frequency_sv = snap7.util.get_int(buffer_db4, 0) / 100

        return {
            "current_cv": current_cv,
            "frequency_cv": frequency_cv,
            "frequency_sv": frequency_sv
        }
    except Exception as e:
        print(f"✗ PLC 데이터 읽기 오류: {e}")
        return None


def store_sensor_data(sensor_id, current_time, value, upper_limit, lower_limit, outlier_status):
    """
    센서 데이터를 데이터베이스에 저장
    
    Sensor ID:
        3: 전류 (Current)
        4: 주파수_CV (Frequency Command Value)
        5: 주파수_SV (Frequency Set Value)
    
    Args:
        sensor_id (int): 센서 ID
        current_time (datetime): 데이터 타임스탐프
        value (float): 센서 측정값
        upper_limit (float): 상한선
        lower_limit (float): 하한선
        outlier_status (bool): 이상치 여부
    """
    try:
        cursor.execute("""
            INSERT INTO vibration (sensor_id, "time", value, upper_limit, lower_limit, outlier_status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (sensor_id, current_time, value, upper_limit, lower_limit, outlier_status))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"✗ 데이터 저장 오류: {e}")


def process_frequency_data():
    """
    주파수 및 전류 데이터 읽기, 처리, 저장
    
    상한/하한선 결정 방식:
    - 전류: 이전 측정값 기준으로 ±0.1A 범위
    - 주파수_CV: 주파수_SV 기준으로 ±1Hz 범위
    - 주파수_SV: 참조값이므로 상한/하한선 없음
    """
    global prev_current_cv

    plc_data = read_plc_data()
    if plc_data is None:
        return

    current_cv = plc_data["current_cv"]
    frequency_cv = plc_data["frequency_cv"]
    frequency_sv = plc_data["frequency_sv"]
    current_time = datetime.now()

    # 전류(Current) 상한/하한선 계산 (이전 값 기반)
    if prev_current_cv is not None:
        upper_limit_current = prev_current_cv + 0.1
        lower_limit_current = prev_current_cv - 0.1
    else:
        upper_limit_current = current_cv + 0.1
        lower_limit_current = current_cv - 0.1

    # 주파수_CV 상한/하한선 계산 (목표 주파수 기반)
    upper_limit_frequency_cv = frequency_sv + 1
    lower_limit_frequency_cv = frequency_sv - 1

    # 이상치 판정
    outlier_current = (current_cv < lower_limit_current or current_cv > upper_limit_current)
    outlier_frequency_cv = (frequency_cv < lower_limit_frequency_cv or frequency_cv > upper_limit_frequency_cv)

    # 데이터베이스에 저장
    store_sensor_data(3, current_time, current_cv, upper_limit_current, lower_limit_current, outlier_current)
    store_sensor_data(4, current_time, frequency_cv, upper_limit_frequency_cv, lower_limit_frequency_cv, outlier_frequency_cv)
    store_sensor_data(5, current_time, frequency_sv, None, None, None)

    # 현재 측정값을 이전 값으로 저장
    prev_current_cv = current_cv

    # 로그 출력
    print(f"[{current_time.strftime('%H:%M:%S')}] Current: {current_cv:6.1f}A | "
          f"Freq_CV: {frequency_cv:6.2f}Hz | Freq_SV: {frequency_sv:6.2f}Hz")


# ============================================================================
# 메인 루프
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("PLC 센서 데이터 수집 시스템 시작")
    print("="*60 + "\n")
    
    try:
        while True:
            process_frequency_data()
            sleep(0.5)
    except KeyboardInterrupt:
        print("\n\n프로그램 중단")
        if plc:
            plc.disconnect()
            print("✓ PLC 연결 종료")
        if conn:
            conn.close()
            print("✓ 데이터베이스 연결 종료")
    except Exception as e:
        print(f"✗ 예상치 못한 오류: {e}")
        if plc:
            plc.disconnect()
        if conn:
            conn.close()
