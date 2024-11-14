import minimalmodbus
import serial
from time import sleep
import psycopg2
import numpy as np
from collections import deque
import redis
from datetime import datetime
import datetime
import time  # 이 줄을 코드 상단에 추가하세요.
from psycopg2.extras import execute_values


# PostgreSQL 연결 설정
conn = psycopg2.connect(
    host='localhost',
    dbname='postgres',
    user='postgres',
    password='1234',
    port=5432
)
cur = conn.cursor()

port = 'COM3'
slave_id = 80

# Redis에 연결
client = redis.from_url('redis://localhost')
stream_name = 'sensorDataStream'
count = 0


# 데이터 저장을 위한 큐
data_queues = {
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

def get_acceleration(x_axis_acc_register, y_axis_acc_register, z_axis_acc_register):
    scale_factor = 9.8 / 32768
    return {
        "x_axis": x_axis_acc_register * scale_factor,
        "y_axis": y_axis_acc_register * scale_factor,
        "z_axis": z_axis_acc_register * scale_factor
    }

def get_angular_velocity(x_ang_vel_register, y_ang_vel_register, z_ang_vel_register):
    return {
        "x_axis": x_ang_vel_register / 32768 * 2000,
        "y_axis": y_ang_vel_register / 32768 * 2000,
        "z_axis": z_ang_vel_register / 32768 * 2000
    }

def split_word(number):
    return {
        "high": (number >> 8) & 0xFF,
        "low": number & 0xFF
    }

def get_vibration_speed(x_vib_sp_register, y_vib_sp_register, z_vib_sp_register):
    x_byte_dict = split_word(x_vib_sp_register)
    y_byte_dict = split_word(y_vib_sp_register)
    z_byte_dict = split_word(z_vib_sp_register)
    
    return {
        "x_axis": int((x_byte_dict["high"] << 8) | x_byte_dict["low"]),
        "y_axis": int((y_byte_dict["high"] << 8) | y_byte_dict["low"]),
        "z_axis": int((z_byte_dict["high"] << 8) | z_byte_dict["low"]),
    }

def apply_fft_filter(data):
    if len(data) < 2:  # 최소한 2개의 데이터가 필요
        return data[-1] if data else 0
    
    fft_result = np.fft.fft(data)
    fft_result[5:] = 0  # 고주파수 제거 (임의로 설정, 조정 가능)
    filtered = np.fft.ifft(fft_result).real
    return filtered[-1]  # 가장 최근 필터링된 값 반환

def calculate_limits_and_outlier_status(values):
    mean = np.mean(values)
    std = np.std(values)
    upper_limit = mean + 3 * std
    lower_limit = mean - 3 * std
    return upper_limit, lower_limit


def insert_vibration_data(sensor_id, current_time, value, filtered_value, upper_limit, lower_limit, outlier_status):
    cur.execute("""
        INSERT INTO public.vibration (sensor_id, "time", value, filtered_value, upper_limit, lower_limit, outlier_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (sensor_id, current_time, value, filtered_value, upper_limit, lower_limit, outlier_status))
    conn.commit()

def bulk_insert_vibration_data(data_list):
    query = "INSERT INTO public.vibration(sensor_id, time, value, filtered_value, upper_limit, lower_limit, outlier_status) VALUES %s"

    try:
        with conn.cursor() as cur:
            # execute_values를 사용하여 성능을 높이고 다중 레코드를 한 번에 삽입
            execute_values(cur, query, data_list)
            conn.commit()
            print("Bulk insert completed successfully.")
    except Exception as e:
        conn.rollback()
        print(f"An error occurred: {e}")
    finally:
        conn.close()

def create_vibration_data_raw(sensor_id, time, axis_data, upper_limit, lower_limit, outlier_status, filtered_value):
    return {
        "sensorId": sensor_id,
        "time": time,
        "value": axis_data,
        "upperLimit": upper_limit,
        "lowerLimit": lower_limit,
        "outlierStatus": outlier_status,
        "filteredValue": filtered_value
}

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

def save_to_redis(client, stream_name, data):
    client.xadd(stream_name, data, maxlen="~1000")
    print(f"Saved data to Redis stream {stream_name}: {data}")

def batch_save_to_redis(client, stream_name, data_list):
    pipeline = client.pipeline()
    
    for data in data_list:
        pipeline.xadd(stream_name, data)
    
    pipeline.execute()

try:
    instrument = minimalmodbus.Instrument(port=port, slaveaddress=slave_id)
    print("Device에 연결되었습니다.")
    instrument.serial.baudrate = 9600
    instrument.serial.bytesize = 8
    instrument.serial.parity = serial.PARITY_NONE
    instrument.serial.stopbits = 1
except Exception as e:
    print(f"{port}를 통한 연결 실패: {e}")


if __name__ == "__main__":
    while True:
        try:
            # 현재 시간 한 번만 호출
            current_time = datetime.datetime.now()

            # 가속도 데이터 읽기
            acc_data = [
                instrument.read_register(52, 0, 3, True),
                instrument.read_register(53, 0, 3, True),
                instrument.read_register(54, 0, 3, True)
            ]
            axis_acc = get_acceleration(*acc_data)

            # 각속도 데이터 읽기
            ang_vel_data = [
                instrument.read_register(55, 0, 3, True),
                instrument.read_register(56, 0, 3, True),
                instrument.read_register(57, 0, 3, True)
            ]
            ang_vel = get_angular_velocity(*ang_vel_data)

            # 진동 속도 데이터 읽기
            vib_sp_data = [
                instrument.read_register(58, 0, 3, True),
                instrument.read_register(59, 0, 3, True),
                instrument.read_register(60, 0, 3, True)
            ]
            vib_sp = get_vibration_speed(*vib_sp_data)

            # 필터 적용 및 이상치 상태 계산
            data_queues['x_acc'].append(axis_acc["x_axis"])
            filtered_x_acc = apply_fft_filter(data_queues['x_acc'])
            data_queues['filtered_x_acc'].append(filtered_x_acc)  # 필터링된 값 저장
            upper_limit_x, lower_limit_x = calculate_limits_and_outlier_status(data_queues['filtered_x_acc'])
            outlier_status_x = not (lower_limit_x <= filtered_x_acc <= upper_limit_x)
            
            data_queues['y_acc'].append(axis_acc["y_axis"])
            filtered_y_acc = apply_fft_filter(data_queues['y_acc'])
            data_queues['filtered_y_acc'].append(filtered_y_acc)  # 필터링된 값 저장
            upper_limit_y, lower_limit_y = calculate_limits_and_outlier_status(data_queues['filtered_y_acc'])
            outlier_status_y = not (lower_limit_y <= filtered_y_acc <= upper_limit_y)
            
            data_queues['z_acc'].append(axis_acc["z_axis"])
            filtered_z_acc = apply_fft_filter(data_queues['z_acc'])
            data_queues['filtered_z_acc'].append(filtered_z_acc)  # 필터링된 값 저장
            upper_limit_z, lower_limit_z = calculate_limits_and_outlier_status(data_queues['filtered_z_acc'])
            outlier_status_z = not (lower_limit_z <= filtered_z_acc <= upper_limit_z)

            # 각속도 필터링 및 이상치 상태 계산
            data_queues['x_ang_vel'].append(ang_vel["x_axis"])
            filtered_x_ang_vel = apply_fft_filter(data_queues['x_ang_vel'])
            data_queues['filtered_x_ang_vel'].append(filtered_x_ang_vel)  # 필터링된 데이터 저장
            upper_limit_ang_x, lower_limit_ang_x = calculate_limits_and_outlier_status(data_queues['filtered_x_ang_vel'])
            outlier_status_ang_x = not (lower_limit_ang_x <= filtered_x_ang_vel <= upper_limit_ang_x)
            
            data_queues['y_ang_vel'].append(ang_vel["y_axis"])
            filtered_y_ang_vel = apply_fft_filter(data_queues['y_ang_vel'])
            data_queues['filtered_y_ang_vel'].append(filtered_y_ang_vel)  # 필터링된 데이터 저장
            upper_limit_ang_y, lower_limit_ang_y = calculate_limits_and_outlier_status(data_queues['filtered_y_ang_vel'])
            outlier_status_ang_y = not (lower_limit_ang_y <= filtered_y_ang_vel <= upper_limit_ang_y)
            
            data_queues['z_ang_vel'].append(ang_vel["z_axis"])
            filtered_z_ang_vel = apply_fft_filter(data_queues['z_ang_vel'])
            data_queues['filtered_z_ang_vel'].append(filtered_z_ang_vel)  # 필터링된 데이터 저장
            upper_limit_ang_z, lower_limit_ang_z = calculate_limits_and_outlier_status(data_queues['filtered_z_ang_vel'])
            outlier_status_ang_z = not (lower_limit_ang_z <= filtered_z_ang_vel <= upper_limit_ang_z)
            
            # 진동 속도 필터링 및 이상치 상태 계산
            data_queues['x_vib_sp'].append(vib_sp["x_axis"])
            filtered_x_vib_sp = apply_fft_filter(data_queues['x_vib_sp'])
            data_queues['filtered_x_vib_sp'].append(filtered_x_vib_sp)  # 필터링된 데이터 저장
            upper_limit_vib_x, lower_limit_vib_x = calculate_limits_and_outlier_status(data_queues['filtered_x_vib_sp'])
            outlier_status_vib_x = not (lower_limit_vib_x <= filtered_x_vib_sp <= upper_limit_vib_x)
            
            data_queues['y_vib_sp'].append(vib_sp["y_axis"])
            filtered_y_vib_sp = apply_fft_filter(data_queues['y_vib_sp'])
            data_queues['filtered_y_vib_sp'].append(filtered_y_vib_sp)  # 필터링된 데이터 저장
            upper_limit_vib_y, lower_limit_vib_y = calculate_limits_and_outlier_status(data_queues['filtered_y_vib_sp'])
            outlier_status_vib_y = not (lower_limit_vib_y <= filtered_y_vib_sp <= upper_limit_vib_y)
            
            data_queues['z_vib_sp'].append(vib_sp["z_axis"])
            filtered_z_vib_sp = apply_fft_filter(data_queues['z_vib_sp'])
            data_queues['filtered_z_vib_sp'].append(filtered_z_vib_sp)  # 필터링된 데이터 저장
            upper_limit_vib_z, lower_limit_vib_z = calculate_limits_and_outlier_status(data_queues['filtered_z_vib_sp'])
            outlier_status_vib_z = not (lower_limit_vib_z <= filtered_z_vib_sp <= upper_limit_vib_z)

            # 데이터베이스에 진동 데이터 저장
            # insert_vibration_data(7, current_time, axis_acc["x_axis"], filtered_x_acc, upper_limit_x, lower_limit_x, outlier_status_x)
            # insert_vibration_data(8, current_time, axis_acc["y_axis"], filtered_y_acc, upper_limit_y, lower_limit_y, outlier_status_y)
            # insert_vibration_data(9, current_time, axis_acc["z_axis"], filtered_z_acc, upper_limit_z, lower_limit_z, outlier_status_z)
            
            # insert_vibration_data(10, current_time, ang_vel["x_axis"], filtered_x_ang_vel, upper_limit_ang_x, lower_limit_ang_x, outlier_status_ang_x)
            # insert_vibration_data(11, current_time, ang_vel["y_axis"], filtered_y_ang_vel, upper_limit_ang_y, lower_limit_ang_y, outlier_status_ang_y)
            # insert_vibration_data(12, current_time, ang_vel["z_axis"], filtered_z_ang_vel, upper_limit_ang_z, lower_limit_ang_z, outlier_status_ang_z)

            # insert_vibration_data(13, current_time, vib_sp["x_axis"], filtered_x_vib_sp, upper_limit_vib_x, lower_limit_vib_x, outlier_status_vib_x)
            # insert_vibration_data(14, current_time, vib_sp["y_axis"], filtered_y_vib_sp, upper_limit_vib_y, lower_limit_vib_y, outlier_status_vib_y)
            # insert_vibration_data(15, current_time, vib_sp["z_axis"], filtered_z_vib_sp, upper_limit_vib_z, lower_limit_vib_z, outlier_status_vib_z)

            
            # 리스트에 데이터 추가
            raw_vibration_data_list = [
                create_vibration_data_raw(7, current_time, axis_acc["x_axis"], upper_limit_x, lower_limit_x, outlier_status_x, filtered_x_acc),
                create_vibration_data_raw(8, current_time, axis_acc["y_axis"], upper_limit_y, lower_limit_y, outlier_status_y, filtered_y_acc),
                create_vibration_data_raw(9, current_time, axis_acc["z_axis"], upper_limit_z, lower_limit_z, outlier_status_z, filtered_z_acc),
                
                create_vibration_data_raw(10, current_time, ang_vel["x_axis"], upper_limit_ang_x, lower_limit_ang_x, outlier_status_ang_x, filtered_x_ang_vel),
                create_vibration_data_raw(11, current_time, ang_vel["y_axis"], upper_limit_ang_y, lower_limit_ang_y, outlier_status_ang_y, filtered_y_ang_vel),
                create_vibration_data_raw(12, current_time, ang_vel["z_axis"], upper_limit_ang_z, lower_limit_ang_z, outlier_status_ang_z, filtered_z_ang_vel),
                
                create_vibration_data_raw(13, current_time, vib_sp["x_axis"], upper_limit_vib_x, lower_limit_vib_x, outlier_status_vib_x, filtered_x_vib_sp),
                create_vibration_data_raw(14, current_time, vib_sp["y_axis"], upper_limit_vib_y, lower_limit_vib_y, outlier_status_vib_y, filtered_y_vib_sp),
                create_vibration_data_raw(15, current_time, vib_sp["z_axis"], upper_limit_vib_z, lower_limit_vib_z, outlier_status_vib_z, filtered_z_vib_sp)
            ]

            # 데이터베이스에 진동 데이터 저장
            bulk_insert_vibration_data(raw_vibration_data_list)
            
            # 리스트에 데이터 추가
            vibration_data_list = [
                create_vibration_data(7, current_time, axis_acc["x_axis"], upper_limit_x, lower_limit_x, outlier_status_x, filtered_x_acc),
                create_vibration_data(8, current_time, axis_acc["y_axis"], upper_limit_y, lower_limit_y, outlier_status_y, filtered_y_acc),
                create_vibration_data(9, current_time, axis_acc["z_axis"], upper_limit_z, lower_limit_z, outlier_status_z, filtered_z_acc),
                
                create_vibration_data(10, current_time, ang_vel["x_axis"], upper_limit_ang_x, lower_limit_ang_x, outlier_status_ang_x, filtered_x_ang_vel),
                create_vibration_data(11, current_time, ang_vel["y_axis"], upper_limit_ang_y, lower_limit_ang_y, outlier_status_ang_y, filtered_y_ang_vel),
                create_vibration_data(12, current_time, ang_vel["z_axis"], upper_limit_ang_z, lower_limit_ang_z, outlier_status_ang_z, filtered_z_ang_vel),
                
                create_vibration_data(13, current_time, vib_sp["x_axis"], upper_limit_vib_x, lower_limit_vib_x, outlier_status_vib_x, filtered_x_vib_sp),
                create_vibration_data(14, current_time, vib_sp["y_axis"], upper_limit_vib_y, lower_limit_vib_y, outlier_status_vib_y, filtered_y_vib_sp),
                create_vibration_data(15, current_time, vib_sp["z_axis"], upper_limit_vib_z, lower_limit_vib_z, outlier_status_vib_z, filtered_z_vib_sp)
            ]
            
            # Redis에 진동 데이터 저장
            batch_save_to_redis(client, stream_name, vibration_data_list)

            time.sleep(0.5)
        except Exception as e:
            print(f"Error: {e}")
