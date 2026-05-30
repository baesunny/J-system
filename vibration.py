"""
Modbus 센서 데이터 수집 및 처리 모듈

이 모듈은 Modbus RTU 프로토콜을 사용하여 센서에서 
가속도(Acceleration), 각속도(Angular Velocity), 진동 속도(Vibration Speed) 데이터를 
실시간으로 수집하고, FFT 필터를 적용하여 전처리한 후
PostgreSQL 데이터베이스와 Redis에 저장합니다.

Features:
    - Modbus RTU 센서 통신
    - FFT 필터를 통한 노이즈 제거
    - 동적 상한/하한선 계산 (통계 기반)
    - 이상치 탐지 (3-sigma)
    - PostgreSQL 배치 저장
    - Redis Stream 실시간 데이터 저장

Requirements:
    - minimalmodbus
    - psycopg2
    - redis
    - numpy
"""

import minimalmodbus
import serial
from time import sleep
from datetime import datetime
import time
from collections import deque

import psycopg2
from psycopg2.extras import execute_values
import numpy as np
import redis
import os
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

# 데이터베이스 연결 설정
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "dbname": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "1234"),
    "port": int(os.getenv("DB_PORT", "5432"))
}

# Modbus 포트 설정
MODBUS_PORT = os.getenv("MODBUS_PORT", "COM3")
MODBUS_SLAVE_ID = int(os.getenv("MODBUS_SLAVE_ID", "80"))

# Redis 설정
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost")
REDIS_STREAM_NAME = os.getenv("REDIS_STREAM_NAME", "sensorDataStream")

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    print("✓ PostgreSQL 데이터베이스 연결 성공")
except Exception as e:
    print(f"✗ 데이터베이스 연결 실패: {e}")

try:
    client = redis.from_url(REDIS_URL)
    print("✓ Redis 연결 성공")
except Exception as e:
    print(f"✗ Redis 연결 실패: {e}")




# 센서 데이터 저장 큐 (시계열 필터링용)
DATA_QUEUES = {
    # 가속도 (m/s²)
    'x_acc': deque(maxlen=100),
    'y_acc': deque(maxlen=100),
    'z_acc': deque(maxlen=100),
    'filtered_x_acc': deque(maxlen=100),
    'filtered_y_acc': deque(maxlen=100),
    'filtered_z_acc': deque(maxlen=100),
    
    # 각속도 (deg/s)
    'x_ang_vel': deque(maxlen=100),
    'y_ang_vel': deque(maxlen=100),
    'z_ang_vel': deque(maxlen=100),
    'filtered_x_ang_vel': deque(maxlen=100),
    'filtered_y_ang_vel': deque(maxlen=100),
    'filtered_z_ang_vel': deque(maxlen=100),
    
    # 진동 속도 (mm/s)
    'x_vib_sp': deque(maxlen=100),
    'y_vib_sp': deque(maxlen=100),
    'z_vib_sp': deque(maxlen=100),
    'filtered_x_vib_sp': deque(maxlen=100),
    'filtered_y_vib_sp': deque(maxlen=100),
    'filtered_z_vib_sp': deque(maxlen=100),
}

# Sensor ID 매핑
SENSOR_IDS = {
    'x_acc': 7, 'y_acc': 8, 'z_acc': 9,
    'x_ang_vel': 10, 'y_ang_vel': 11, 'z_ang_vel': 12,
    'x_vib_sp': 13, 'y_vib_sp': 14, 'z_vib_sp': 15
}


# ============================================================================
# 센서 데이터 변환 함수
# ============================================================================

def get_acceleration(x_register, y_register, z_register):
    """
    Modbus 레지스터 값을 가속도로 변환 (m/s²)
    
    Args:
        x_register, y_register, z_register: Modbus 레지스터 값
    
    Returns:
        dict: {'x_axis': float, 'y_axis': float, 'z_axis': float}
    """
    scale_factor = 9.8 / 32768
    return {
        "x_axis": x_register * scale_factor,
        "y_axis": y_register * scale_factor,
        "z_axis": z_register * scale_factor
    }


def get_angular_velocity(x_register, y_register, z_register):
    """
    Modbus 레지스터 값을 각속도로 변환 (deg/s)
    
    Args:
        x_register, y_register, z_register: Modbus 레지스터 값
    
    Returns:
        dict: {'x_axis': float, 'y_axis': float, 'z_axis': float}
    """
    return {
        "x_axis": x_register / 32768 * 2000,
        "y_axis": y_register / 32768 * 2000,
        "z_axis": z_register / 32768 * 2000
    }


def split_word(number):
    """16-bit 데이터를 High/Low byte로 분리"""
    return {
        "high": (number >> 8) & 0xFF,
        "low": number & 0xFF
    }


def get_vibration_speed(x_register, y_register, z_register):
    """
    Modbus 레지스터 값을 진동 속도로 변환 (mm/s)
    
    Args:
        x_register, y_register, z_register: Modbus 레지스터 값
    
    Returns:
        dict: {'x_axis': int, 'y_axis': int, 'z_axis': int}
    """
    x_bytes = split_word(x_register)
    y_bytes = split_word(y_register)
    z_bytes = split_word(z_register)
    
    return {
        "x_axis": int((x_bytes["high"] << 8) | x_bytes["low"]),
        "y_axis": int((y_bytes["high"] << 8) | y_bytes["low"]),
        "z_axis": int((z_bytes["high"] << 8) | z_bytes["low"]),
    }


# ============================================================================
# 신호 처리 함수
# ============================================================================

def apply_fft_filter(data):
    """
    FFT 기반 고주파 필터링 (노이즈 제거)
    
    Args:
        data: 시계열 데이터 (deque)
    
    Returns:
        float: 필터링된 현재 값
    """
    if len(data) < 2:
        return data[-1] if data else 0
    
    fft_result = np.fft.fft(data)
    fft_result[5:] = 0  # 5번째 이후 주파수 성분 제거
    filtered = np.fft.ifft(fft_result).real
    return filtered[-1]


def calculate_limits_and_outlier_status(values):
    """
    시계열 데이터의 평균/표준편차를 기반으로 상한/하한선 계산
    (동적 통계 기반 상한/하한선)
    
    Args:
        values: 시계열 데이터 (deque)
    
    Returns:
        tuple: (upper_limit, lower_limit)
    """
    if len(values) < 2:
        mean = values[-1] if values else 0
        std = 0
    else:
        n = len(values)
        prev_mean = np.mean(values[:-1])
        prev_std = np.std(values[:-1])

        mean = prev_mean + (values[-1] - prev_mean) / n
        std = np.sqrt(((n - 1) * (prev_std ** 2) + (values[-1] - prev_mean) * (values[-1] - mean)) / n)
    
    # 표준편차의 4배를 상한/하한선으로 설정 (조정 가능)
    upper_limit = mean + 4 * std
    lower_limit = mean - 4 * std
    return float(upper_limit), float(lower_limit)


# ============================================================================
# 데이터베이스 저장 함수
# ============================================================================

def insert_vibration_data(sensor_id, timestamp, value, filtered_value, upper_limit, lower_limit, outlier_status):
    """개별 센서 데이터를 데이터베이스에 저장"""
    try:
        cur.execute("""
            INSERT INTO public.vibration 
            (sensor_id, time, value, filtered_value, upper_limit, lower_limit, outlier_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (sensor_id, timestamp, value, filtered_value, upper_limit, lower_limit, outlier_status))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"데이터 저장 오류: {e}")


def bulk_insert_vibration_data(data_list):
    """배치 삽입으로 여러 센서 데이터를 한 번에 저장 (성능 최적화)"""
    query = """
        INSERT INTO public.vibration
        (sensor_id, time, value, filtered_value, upper_limit, lower_limit, outlier_status) 
        VALUES %s
    """

    try:
        with conn.cursor() as cursor:
            execute_values(cursor, query, data_list)
            conn.commit()
            print(f"✓ {len(data_list)}개 레코드 저장 완료")
    except Exception as e:
        conn.rollback()
        print(f"✗ 배치 저장 오류: {e}")


# ============================================================================
# Redis 저장 함수
# ============================================================================

def save_to_redis(data_dict):
    """Redis Stream에 단일 데이터 저장"""
    try:
        client.xadd(REDIS_STREAM_NAME, data_dict, maxlen="~1000")
    except Exception as e:
        print(f"Redis 저장 오류: {e}")


def batch_save_to_redis(data_list):
    """Redis Stream에 배치 데이터 저장"""
    try:
        pipeline = client.pipeline()
        for data in data_list:
            pipeline.xadd(REDIS_STREAM_NAME, data)
        pipeline.execute()
    except Exception as e:
        print(f"Redis 배치 저장 오류: {e}")


# ============================================================================
# 데이터 변환 함수
# ============================================================================

def create_vibration_data(sensor_id, timestamp, value, upper_limit, lower_limit, outlier_status, filtered_value):
    """
    센서 데이터를 저장용 딕셔너리로 변환
    
    Args:
        sensor_id: 센서 ID
        timestamp: 데이터 타임스탐프
        value: 측정값
        upper_limit: 상한선
        lower_limit: 하한선
        outlier_status: 이상치 여부 (bool)
        filtered_value: 필터링된 값
    
    Returns:
        dict: 저장용 데이터 딕셔너리
    """
    return {
        "sensor_id": str(sensor_id),
        "time": str(timestamp),
        "value": str(value),
        "upper_limit": str(upper_limit),
        "lower_limit": str(lower_limit),
        "outlier_status": str(outlier_status),
        "filtered_value": str(filtered_value)
    }



# ============================================================================
# Modbus 센서 초기화
# ============================================================================

instrument = None
try:
    instrument = minimalmodbus.Instrument(port=MODBUS_PORT, slaveaddress=MODBUS_SLAVE_ID)
    instrument.serial.baudrate = 9600
    instrument.serial.bytesize = 8
    instrument.serial.parity = serial.PARITY_NONE
    instrument.serial.stopbits = 1
    print(f"✓ Modbus 센서 연결 성공 ({MODBUS_PORT}, Slave ID: {MODBUS_SLAVE_ID})")
except Exception as e:
    print(f"✗ Modbus 센서 연결 실패: {e}")


# ============================================================================
# 메인 데이터 수집 루프
# ============================================================================

def process_sensor_data():
    """센서에서 데이터를 읽고 처리하여 저장"""
    if instrument is None:
        print("센서가 연결되지 않았습니다.")
        return
    
    try:
        current_time = datetime.now()
        data_to_insert = []
        redis_data_list = []

        # 1. 가속도 데이터 읽기 및 처리
        acc_data = [
            instrument.read_register(52, 0, 3, True),
            instrument.read_register(53, 0, 3, True),
            instrument.read_register(54, 0, 3, True)
        ]
        axis_acc = get_acceleration(*acc_data)
        
        for axis, axis_name in [("x_axis", "x_acc"), ("y_axis", "y_acc"), ("z_axis", "z_acc")]:
            DATA_QUEUES[axis_name].append(axis_acc[axis])
            filtered_value = apply_fft_filter(DATA_QUEUES[axis_name])
            DATA_QUEUES[f"filtered_{axis_name}"].append(filtered_value)
            
            upper_limit, lower_limit = calculate_limits_and_outlier_status(DATA_QUEUES[f"filtered_{axis_name}"])
            outlier_status = not (lower_limit <= filtered_value <= upper_limit)
            
            sensor_id = SENSOR_IDS[axis_name]
            data_to_insert.append((sensor_id, current_time, axis_acc[axis], filtered_value, upper_limit, lower_limit, outlier_status))
            redis_data_list.append(create_vibration_data(sensor_id, current_time, axis_acc[axis], upper_limit, lower_limit, outlier_status, filtered_value))

        # 2. 각속도 데이터 읽기 및 처리
        ang_vel_data = [
            instrument.read_register(55, 0, 3, True),
            instrument.read_register(56, 0, 3, True),
            instrument.read_register(57, 0, 3, True)
        ]
        ang_vel = get_angular_velocity(*ang_vel_data)
        
        for axis, axis_name in [("x_axis", "x_ang_vel"), ("y_axis", "y_ang_vel"), ("z_axis", "z_ang_vel")]:
            DATA_QUEUES[axis_name].append(ang_vel[axis])
            filtered_value = apply_fft_filter(DATA_QUEUES[axis_name])
            DATA_QUEUES[f"filtered_{axis_name}"].append(filtered_value)
            
            upper_limit, lower_limit = calculate_limits_and_outlier_status(DATA_QUEUES[f"filtered_{axis_name}"])
            outlier_status = not (lower_limit <= filtered_value <= upper_limit)
            
            sensor_id = SENSOR_IDS[axis_name]
            data_to_insert.append((sensor_id, current_time, ang_vel[axis], filtered_value, upper_limit, lower_limit, outlier_status))
            redis_data_list.append(create_vibration_data(sensor_id, current_time, ang_vel[axis], upper_limit, lower_limit, outlier_status, filtered_value))

        # 3. 진동 속도 데이터 읽기 및 처리
        vib_sp_data = [
            instrument.read_register(58, 0, 3, True),
            instrument.read_register(59, 0, 3, True),
            instrument.read_register(60, 0, 3, True)
        ]
        vib_sp = get_vibration_speed(*vib_sp_data)
        
        for axis, axis_name in [("x_axis", "x_vib_sp"), ("y_axis", "y_vib_sp"), ("z_axis", "z_vib_sp")]:
            DATA_QUEUES[axis_name].append(vib_sp[axis])
            filtered_value = apply_fft_filter(DATA_QUEUES[axis_name])
            DATA_QUEUES[f"filtered_{axis_name}"].append(filtered_value)
            
            upper_limit, lower_limit = calculate_limits_and_outlier_status(DATA_QUEUES[f"filtered_{axis_name}"])
            outlier_status = not (lower_limit <= filtered_value <= upper_limit)
            
            sensor_id = SENSOR_IDS[axis_name]
            data_to_insert.append((sensor_id, current_time, vib_sp[axis], filtered_value, upper_limit, lower_limit, outlier_status))
            redis_data_list.append(create_vibration_data(sensor_id, current_time, vib_sp[axis], upper_limit, lower_limit, outlier_status, filtered_value))

        # 데이터베이스 저장 (배치)
        bulk_insert_vibration_data(data_to_insert)
        
        # Redis 저장 (스트림)
        batch_save_to_redis(redis_data_list)
        
        print(f"[{current_time.strftime('%H:%M:%S')}] ✓ 센서 데이터 처리 완료")

    except Exception as e:
        print(f"센서 데이터 처리 오류: {e}")


if __name__ == "__main__":
    print("\n" + "="*50)
    print("센서 데이터 수집 시스템 시작")
    print("="*50 + "\n")
    
    try:
        while True:
            process_sensor_data()
            time.sleep(0.5)  # 0.5초 간격으로 데이터 수집
    except KeyboardInterrupt:
        print("\n\n프로그램 중단")
        if conn:
            conn.close()
        print("✓ 데이터베이스 연결 종료")
