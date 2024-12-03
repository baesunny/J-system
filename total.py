import snap7
import snap7.util
import psycopg2
import redis
from collections import deque
import numpy as np
from time import sleep
import time
from datetime import datetime
import cProfile

# PLC 연결 설정
plc = snap7.client.Client()
plc.connect("192.168.0.120", 0, 1)

# 데이터베이스 연결 설정
conn = psycopg2.connect(
    dbname="postgres",
    user="postgres",
    password="1234",
    host="localhost",
    port="5432"
)
cursor = conn.cursor()

# Redis에 연결
# client = redis.from_url('redis://localhost')
# 연결 풀 설정
pool = redis.ConnectionPool(
    host='localhost',  # Redis 서버 주소
    port=6379,         # Redis 서버 포트
    # db=0,              # 사용할 DB 번호 (기본값은 0)
    max_connections=3 # 최대 연결 수
)
# 연결 풀을 사용하여 Redis 클라이언트 생성
client = redis.Redis(connection_pool=pool)
pipeline = client.pipeline()  # pipeline 생성
stream_name = 'sensorDataStream'

# 데이터베이스에 삽입
def bulk_insert_to_db(data_list):
    try:
        cursor.executemany("""
            INSERT INTO vibration (sensor_id, time, value, upper_limit, lower_limit, outlier_status, filtered_value)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, data_list)
        conn.commit()
    except Exception as e:
        print(f"Database insertion error: {e}")
        conn.rollback()

# Redis Stream 저장을 위한 데이터 형식
def create_vibration_data(sensor_id, time, axis_data, upper_limit, lower_limit, outlier_status, filtered_value):
    return {
        "sensorId": sensor_id,
        "time": str(time),
        "value": axis_data,
        "upperLimit": upper_limit,
        "lowerLimit": lower_limit,
        "outlierStatus": str(outlier_status),
        "filteredValue": filtered_value
    }

# Pipeline으로 Redis에 한 번에 저장
def batch_save_to_redis(data_list, maxlen=1000):
    try:
        for data in data_list:
            # 데이터를 Redis Stream에 추가
            stream_data = {
                "sensor_id": data[0],
                "time": str(data[1]),  # 시간 ISO 8601 형식으로 저장
                "value": data[2],
                "upper_limit": data[3] if data[3] else "",
                "lower_limit": data[4] if data[4] else "",
                "outlier_status": str(data[5]) if str(data[5]) else "",
                "filtered_value": data[6] if data[6] else ""
            }
            # XADD 명령어로 Stream에 데이터 추가
            pipeline.xadd(stream_name, stream_data, maxlen=maxlen)
        # 모든 명령을 한 번에 실행
        pipeline.execute()
    except Exception as e:
        print(f"[Error] Redis Batch 저장 중 에러 발생: {e}")

# 데이터 저장을 위한 큐 관리 (각 센서 타입별로 관리)
data_queues = {
    'temperature': {},
    'rh': {},
    'inverter': {},
    'vibration': {}
}

# 사용하는 센서들 (각 센서 타입별로 개수 다름)
temperature_sensor_ids = range(1, 2)  # 온도 센서 1개
rh_sensor_ids = range(2, 3)  # 습도 센서 1개
inverter_sensor_ids = range(3, 4)  # 인버터 1개
vibration_sensor_ids = range(4, 6)  # 진동 센서 2개

# 각 센서 타입별로 큐 생성
for sensor_id in inverter_sensor_ids:
    data_queues['inverter'][sensor_id] = {
        'current_cv': deque(maxlen=100),  # 전류
        'frequency_cv': deque(maxlen=100),  # 주파수
        'voltage': deque(maxlen=100),  # 전압
    }

for sensor_id in temperature_sensor_ids:
    data_queues['temperature'][sensor_id] = {
        'temp': deque(maxlen=100),  # 온도
    }
    
for sensor_id in rh_sensor_ids:
    data_queues['rh'][sensor_id] = {
        'rh': deque(maxlen=100),  # 습도
    }

for sensor_id in vibration_sensor_ids:
    data_queues['vibration'][sensor_id] = {
        'x_acc': deque(maxlen=100),  # 가속도 x축
        'y_acc': deque(maxlen=100),  # 가속도 y축
        'z_acc': deque(maxlen=100),  # 가속도 z축
        'filtered_x_acc': deque(maxlen=100),  # 가속도 x축
        'filtered_y_acc': deque(maxlen=100),  # 가속도 y축
        'filtered_z_acc': deque(maxlen=100),  # 가속도 z축
        
        'x_ang_vel': deque(maxlen=100),  # 각속도 x축
        'y_ang_vel': deque(maxlen=100),  # 각속도 y축
        'z_ang_vel': deque(maxlen=100),  # 각속도 z축
        'filtered_x_ang_vel': deque(maxlen=100),  # 각속도 x축
        'filtered_y_ang_vel': deque(maxlen=100),  # 각속도 y축
        'filtered_z_ang_vel': deque(maxlen=100),  # 각속도 z축
        
        'x_vib_sp': deque(maxlen=100),  # 진동 속도 x축
        'y_vib_sp': deque(maxlen=100),  # 진동 속도 y축
        'z_vib_sp': deque(maxlen=100),   # 진동 속도 z축
        'filtered_x_vib_sp': deque(maxlen=100),  # 진동 속도 x축
        'filtered_y_vib_sp': deque(maxlen=100),  # 진동 속도 y축
        'filtered_z_vib_sp': deque(maxlen=100),   # 진동 속도 z축
    }

# 센서 데이터 추가하는 예시
def add_sensor_data(sensor_type, sensor_id, data_type, data):
    if sensor_id in data_queues[sensor_type]:
        data_queues[sensor_type][sensor_id][data_type].append(data)
    else:
        print(f"Sensor ID {sensor_id} not found for type {sensor_type}")

# FFT 필터 적용
def apply_fft_filter(data):
    if len(data) < 2:  # 최소한 2개의 데이터가 필요
        return data[-1] if data else 0
    fft_result = np.fft.fft(data)
    fft_result[5:] = 0  # 고주파수 제거 (임의로 설정, 조정 가능)
    filtered = np.fft.ifft(fft_result).real
    return float(filtered[-1])  # 가장 최근 필터링된 값 반환

# 상한선, 하한선 계산
def calculate_limits(values):
    mean = np.mean(values)
    std = np.std(values)
    upper_limit = mean + 3 * std
    lower_limit = mean - 3 * std
    return float(upper_limit), float(lower_limit)

# 이상치 상태 계산
def calculate_outlier_status(value, upper_limit, lower_limit):
    return not (lower_limit <= value <= upper_limit)

# 센서 데이터 상한선 및 하한선, 이상치 상태 계산
def process_sensor_data(data, data_queue):
    data_queue.append(data)  # 데이터 추가
    upper_limit, lower_limit = calculate_limits(data_queue)  # 이상치 상태 계산
    outlier_status = calculate_outlier_status(data, upper_limit, lower_limit)  # 이상치 여부 계산
    return upper_limit, lower_limit, outlier_status

# 진동 데이터 FFT 필터링 및 상한선 및 하한선, 이상치 상태 계산
def process_vibration_data(axis_data, data_queue, filtered_data_queue):
    """
    :param axis_data: 입력 데이터 (각 축의 센서 값)
    :param data_queue: 해당 센서의 데이터 큐 (원본 데이터 저장)
    :param filtered_data_queue: 필터링된 데이터 큐 (필터링 후 저장)
    :return: 필터링된 값, 상한선 값, 하한선 값, 이상치 상태
    """
    data_queue.append(axis_data)  # 데이터 추가
    filtered_data = apply_fft_filter(data_queue)  # FFT 필터링 적용
    filtered_data_queue.append(filtered_data)  # 필터링된 데이터 저장
    upper_limit, lower_limit = calculate_limits(filtered_data_queue)  # 이상치 상태 계산
    outlier_status = calculate_outlier_status(filtered_data, upper_limit, lower_limit)  # 이상치 여부 계산
    return filtered_data, upper_limit, lower_limit, outlier_status

# if __name__ == "__main__":
def main():
    while True:
        # 함수 실행 시작 시간
        start = time.time();
        
        # PLC 데이터 모두 읽기
        das_db = plc.db_read(7, 0, 168)
        sensor_db2 = plc.db_read(4, 0, 2)
    
        # PLC 데이터 블록에서 값 읽기
        # 인버터 데이터 
        current_cv = snap7.util.get_int(das_db, 0) / 10
        frequency_cv = snap7.util.get_int(das_db, 2) / 100
        frequency_sv = snap7.util.get_int(sensor_db2, 0) / 100
        voltage = snap7.util.get_int(das_db, 4)
        power = snap7.util.get_int(das_db, 6) 

        # 온도, 습도 데이터 
        temp = snap7.util.get_real(das_db, 8)
        rh = snap7.util.get_real(das_db, 12)

        # 진동센서 1
        # 가속도 데이터 
        axis_acc = {
            "x_axis": snap7.util.get_real(das_db, 16),
            "y_axis": snap7.util.get_real(das_db, 20),
            "z_axis": snap7.util.get_real(das_db, 24)
        }

        # 각속도 데이터 
        ang_vel = {
            "x_axis": snap7.util.get_real(das_db, 28),
            "y_axis": snap7.util.get_real(das_db, 32),
            "z_axis": snap7.util.get_real(das_db, 36)
        }

        # 진동 속도 데이터 읽기
        vib_sp = {
            "x_axis": snap7.util.get_real(das_db, 40),
            "y_axis": snap7.util.get_real(das_db, 44),
            "z_axis": snap7.util.get_real(das_db, 48)
        }

        # 진동센서 2
        # 가속도 데이터 
        axis_acc2 = {
            "x_axis": snap7.util.get_real(das_db, 96),
            "y_axis": snap7.util.get_real(das_db, 100),
            "z_axis": snap7.util.get_real(das_db, 104)
        }

        # 각속도 데이터 
        ang_vel2 = {
            "x_axis": snap7.util.get_real(das_db, 108),
            "y_axis": snap7.util.get_real(das_db, 112),
            "z_axis": snap7.util.get_real(das_db, 116)
        }

        # 진동 속도 데이터 읽기
        vib_sp2 = {
            "x_axis": snap7.util.get_real(das_db, 120),
            "y_axis": snap7.util.get_real(das_db, 124),
            "z_axis": snap7.util.get_real(das_db, 128)
        }

        # 인버터, 온도, 습도 데이터 상한선/하한선, 이상치 상태
        upper_limit_temp, lower_limit_temp, outlier_status_temp = process_sensor_data(temp, data_queues['temperature'][1]['temp'])
        upper_limit_rh, lower_limit_rh, outlier_status_rh = process_sensor_data(rh, data_queues['rh'][2]['rh'])
        upper_limit_current_cv, lower_limit_current_cv, outlier_status_current_cv = process_sensor_data(current_cv, data_queues['inverter'][3]['current_cv'])
        upper_limit_frequency_cv, lower_limit_frequency_cv, outlier_status_frequency_cv = process_sensor_data(frequency_cv, data_queues['inverter'][3]['frequency_cv'])
        upper_limit_voltage, lower_limit_voltage, outlier_status_voltage = process_sensor_data(voltage, data_queues['inverter'][3]['voltage'])

        # 진동 데이터 FFT 필터 적용 값, 상한선/하한선, 이상치 상태
        filtered_x_acc, upper_limit_x, lower_limit_x, outlier_status_x = process_vibration_data(axis_acc['x_axis'], data_queues['vibration'][4]['x_acc'], data_queues['vibration'][4]['filtered_x_acc'])
        filtered_y_acc, upper_limit_y, lower_limit_y, outlier_status_y = process_vibration_data(axis_acc['y_axis'], data_queues['vibration'][4]['y_acc'], data_queues['vibration'][4]['filtered_y_acc'])
        filtered_z_acc, upper_limit_z, lower_limit_z, outlier_status_z = process_vibration_data(axis_acc['z_axis'], data_queues['vibration'][4]['z_acc'], data_queues['vibration'][4]['filtered_z_acc'])
        
        filtered_x_ang_vel, upper_limit_ang_x, lower_limit_ang_x, outlier_status_ang_x = process_vibration_data(ang_vel["x_axis"], data_queues['vibration'][4]['x_ang_vel'], data_queues['vibration'][4]['filtered_x_ang_vel'])
        filtered_y_ang_vel, upper_limit_ang_y, lower_limit_ang_y, outlier_status_ang_y = process_vibration_data(ang_vel["y_axis"], data_queues['vibration'][4]['y_ang_vel'], data_queues['vibration'][4]['filtered_y_ang_vel'])
        filtered_z_ang_vel, upper_limit_ang_z, lower_limit_ang_z, outlier_status_ang_z = process_vibration_data(ang_vel["z_axis"], data_queues['vibration'][4]['z_ang_vel'], data_queues['vibration'][4]['filtered_z_ang_vel'])

        filtered_x_vib_sp, upper_limit_vib_x, lower_limit_vib_x, outlier_status_vib_x = process_vibration_data(vib_sp["x_axis"], data_queues['vibration'][4]['x_vib_sp'], data_queues['vibration'][4]['filtered_x_vib_sp'])
        filtered_y_vib_sp, upper_limit_vib_y, lower_limit_vib_y, outlier_status_vib_y = process_vibration_data(vib_sp["y_axis"], data_queues['vibration'][4]['y_vib_sp'], data_queues['vibration'][4]['filtered_y_vib_sp'])
        filtered_z_vib_sp, upper_limit_vib_z, lower_limit_vib_z, outlier_status_vib_z = process_vibration_data(vib_sp["z_axis"], data_queues['vibration'][4]['z_vib_sp'], data_queues['vibration'][4]['filtered_z_vib_sp'])

        # 진동 데이터 2 FFT 필터 적용 값, 상한선/하한선, 이상치 상태
        filtered_x_acc2, upper_limit_x2, lower_limit_x2, outlier_status_x2 = process_vibration_data(axis_acc2['x_axis'], data_queues['vibration'][5]['x_acc'], data_queues['vibration'][5]['filtered_x_acc'])
        filtered_y_acc2, upper_limit_y2, lower_limit_y2, outlier_status_y2 = process_vibration_data(axis_acc2['y_axis'], data_queues['vibration'][5]['y_acc'], data_queues['vibration'][5]['filtered_y_acc'])
        filtered_z_acc2, upper_limit_z2, lower_limit_z2, outlier_status_z2 = process_vibration_data(axis_acc2['z_axis'], data_queues['vibration'][5]['z_acc'], data_queues['vibration'][5]['filtered_z_acc'])
        
        filtered_x_ang_vel2, upper_limit_ang_x2, lower_limit_ang_x2, outlier_status_ang_x2 = process_vibration_data(ang_vel2["x_axis"], data_queues['vibration'][5]['x_ang_vel'], data_queues['vibration'][5]['filtered_x_ang_vel'])
        filtered_y_ang_vel2, upper_limit_ang_y2, lower_limit_ang_y2, outlier_status_ang_y2 = process_vibration_data(ang_vel2["y_axis"], data_queues['vibration'][5]['y_ang_vel'], data_queues['vibration'][5]['filtered_y_ang_vel'])
        filtered_z_ang_vel2, upper_limit_ang_z2, lower_limit_ang_z2, outlier_status_ang_z2 = process_vibration_data(ang_vel2["z_axis"], data_queues['vibration'][5]['z_ang_vel'], data_queues['vibration'][5]['filtered_z_ang_vel'])

        filtered_x_vib_sp2, upper_limit_vib_x2, lower_limit_vib_x2, outlier_status_vib_x2 = process_vibration_data(vib_sp2["x_axis"], data_queues['vibration'][5]['x_vib_sp'], data_queues['vibration'][5]['filtered_x_vib_sp'])
        filtered_y_vib_sp2, upper_limit_vib_y2, lower_limit_vib_y2, outlier_status_vib_y2 = process_vibration_data(vib_sp2["y_axis"], data_queues['vibration'][5]['y_vib_sp'], data_queues['vibration'][5]['filtered_y_vib_sp'])
        filtered_z_vib_sp2, upper_limit_vib_z2, lower_limit_vib_z2, outlier_status_vib_z2 = process_vibration_data(vib_sp2["z_axis"], data_queues['vibration'][5]['z_vib_sp'], data_queues['vibration'][5]['filtered_z_vib_sp'])

        # 현재 시간
        current_time = datetime.now()
    
        # 각 센서 데이터 삽입 준비
        sensor_data_list = [
            (1, current_time, temp, upper_limit_temp, lower_limit_temp, outlier_status_temp, None),
            (2, current_time, rh, upper_limit_rh, lower_limit_rh, outlier_status_rh, None),
            
            (3, current_time, current_cv, upper_limit_current_cv, lower_limit_current_cv, outlier_status_current_cv, None),
            (4, current_time, frequency_cv, upper_limit_frequency_cv, lower_limit_frequency_cv, outlier_status_frequency_cv, None),
            (5, current_time, frequency_sv, None, None, None, None),  # frequency_sv의 상한선, 하한선, 이상탐지값은 결측치로 설정
            (6, current_time, voltage, upper_limit_voltage, lower_limit_voltage, outlier_status_voltage, None),
            
            (7, current_time, axis_acc["x_axis"], upper_limit_x, lower_limit_x, outlier_status_x, filtered_x_acc),
            (8, current_time, axis_acc["y_axis"], upper_limit_y, lower_limit_y, outlier_status_y, filtered_y_acc),
            (9, current_time, axis_acc["z_axis"], upper_limit_z, lower_limit_z, outlier_status_z, filtered_z_acc),
            
            (10, current_time, ang_vel["x_axis"], upper_limit_ang_x, lower_limit_ang_x, outlier_status_ang_x, filtered_x_ang_vel),
            (11, current_time, ang_vel["y_axis"], upper_limit_ang_y, lower_limit_ang_y, outlier_status_ang_y, filtered_y_ang_vel),
            (12, current_time, ang_vel["z_axis"], upper_limit_ang_z, lower_limit_ang_z, outlier_status_ang_z, filtered_z_ang_vel),
            
            (13, current_time, vib_sp["x_axis"], upper_limit_vib_x, lower_limit_vib_x, outlier_status_vib_x, filtered_x_vib_sp),
            (14, current_time, vib_sp["y_axis"], upper_limit_vib_y, lower_limit_vib_y, outlier_status_vib_y, filtered_y_vib_sp),
            (15, current_time, vib_sp["z_axis"], upper_limit_vib_z, lower_limit_vib_z, outlier_status_vib_z, filtered_z_vib_sp),

            (16, current_time, axis_acc2["x_axis"], upper_limit_x2, lower_limit_x2, outlier_status_x2, filtered_x_acc2),
            (17, current_time, axis_acc2["y_axis"], upper_limit_y2, lower_limit_y2, outlier_status_y2, filtered_y_acc2),
            (18, current_time, axis_acc2["z_axis"], upper_limit_z2, lower_limit_z2, outlier_status_z2, filtered_z_acc2),
            
            (19, current_time, ang_vel2["x_axis"], upper_limit_ang_x2, lower_limit_ang_x2, outlier_status_ang_x2, filtered_x_ang_vel2),
            (20, current_time, ang_vel2["y_axis"], upper_limit_ang_y2, lower_limit_ang_y2, outlier_status_ang_y2, filtered_y_ang_vel2),
            (21, current_time, ang_vel2["z_axis"], upper_limit_ang_z2, lower_limit_ang_z2, outlier_status_ang_z2, filtered_z_ang_vel2),
            
            (22, current_time, vib_sp2["x_axis"], upper_limit_vib_x2, lower_limit_vib_x2, outlier_status_vib_x2, filtered_x_vib_sp2),
            (23, current_time, vib_sp2["y_axis"], upper_limit_vib_y2, lower_limit_vib_y2, outlier_status_vib_y2, filtered_y_vib_sp2),
            (24, current_time, vib_sp2["z_axis"], upper_limit_vib_z2, lower_limit_vib_z2, outlier_status_vib_z2, filtered_z_vib_sp2)
        ]

        # print('*** sensor_data_list:', sensor_data_list)
        
        # 데이터베이스에 삽입
        bulk_insert_to_db(sensor_data_list)
        batch_save_to_redis(sensor_data_list)
        
        # 함수 실행 시간 계산
        end = time.time()
        print(f'실행 시간={end-start}')
    
        # 주기 설정
        sleep(0.01)
    
    # 데이터베이스 연결 종료
    conn.close()

# cProfile을 사용하여 main 함수 실행
if __name__ == "__main__":
    cProfile.run('main()')
