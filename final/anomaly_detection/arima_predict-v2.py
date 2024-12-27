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
client = redis.from_url('redis://localhost')
pipeline = client.pipeline()  
stream_name = 'sensorDataStream'

# 데이터베이스에 삽입
def bulk_insert_to_db(data_list):
    try:
        cursor.executemany("""
            INSERT INTO vibration (sensor_id, time, value, predicted_value, filtered_value, outlier_status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, data_list)
        conn.commit()
    except Exception as e:
        print(f"Database insertion error: {e}")
        conn.rollback()

# Redis Stream 저장을 위한 데이터 형식
def create_vibration_data(sensor_id, time, axis_data, predicted_value, filtered_value, outlier_status):
    return {
        "sensorId": sensor_id,
        "time": str(time),
        "value": axis_data,
        "predicted_value" : predicted_value,
        "filteredValue": filtered_value,
        "outlierStatus": str(outlier_status)
    }


# Pipeline으로 Redis에 한 번에 저장
def batch_save_to_redis(data_list, maxlen=2000):
    try:
        for data in data_list:
            # 데이터를 Redis Stream에 추가
            if data[5] is None:
                stream_data = {
                    "equipmentId": data[0],
                    "sensorId": data[1],
                    "time": str(data[2]),
                    "value": data[3],
                    "predicted_value" : data[4],
#                     "filtered_value" : data[5],
                    "outlierStatus": str(data[6])
                }
            else:
                stream_data = {
                    "equipmentId": data[0],
                    "sensorId": data[1],
                    "time": str(data[2]),
                    "value": data[3],
                    "predicted_value" : data[4],
                    "filtered_value" : data[5],
                    "outlierStatus": str(data[6])
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
  
###################################################################################################
