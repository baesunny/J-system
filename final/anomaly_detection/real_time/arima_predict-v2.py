from time import sleep
import numpy as np
from collections import deque
from datetime import datetime
import datetime
import time
from psycopg2.extras import execute_values
import nest_asyncio
import asyncpg
import redis.asyncio as redis
import asyncio
from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusException
import multiprocessing as mp
from statsmodels.tsa.arima.model import ARIMA

# Jupyter에서 비동기 실행
nest_asyncio.apply()

port = 'COM5'
slave_id = 80

# Global buffers for batch operations
db_batch_buffer = []
redis_batch_buffer = []

# Batch size threshold
BATCH_SIZE = 300


# PostgreSQL 연결
async def db_connect():
    try:
        db_conn = await asyncpg.connect(
            host='localhost',
            port='5432',
            user='postgres',
            password='1234',
            database='postgres'
        )
        print(f"데이터베이스 연결 성공")
        return db_conn
    except Exception as e:
        print(f"[Error] 데이터 베이스 연결 중 에러 발생 : {e}")
        return None

# Redis Stream
stream_name = 'sensorDataStream'

# Redis 연결
async def redis_connect():
    try:
        redis_conn = await redis.Redis()
        print(f"Redis 연결 성공")
        return redis_conn
    except Exception as e:
        print(f"[Error] Redis 연결 중 예상치 못한 에러 발생: {e}")
        return None

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


min_data_length = 100

# 데이터 추가 함수
def add_sensor_data(sensor_type, sensor_id, data_type, data):
    if sensor_id in data_queues.get(sensor_type, {}):
        data_queues[sensor_type][sensor_id][data_type].append(data)
    else:
        if sensor_type not in data_queues:
            data_queues[sensor_type] = {}
        data_queues[sensor_type][sensor_id] = {data_type: deque([data], maxlen=1000)}

# FFT 필터 함수 (동기 로직을 비동기로 호출)
async def apply_fft_filter(data):
    return await asyncio.to_thread(sync_apply_fft_filter, data)

def sync_apply_fft_filter(data):
    if len(data) < 2:
        return data[-1] if data else 0
    fft_result = np.fft.fft(data)
    fft_result[5:] = 0
    filtered = np.fft.ifft(fft_result).real
    return float(filtered[-1])

# ARIMA 예측 함수
async def arima_predict(values, order=(1, 1, 1)):
    return await asyncio.to_thread(sync_arima_predict, values, order)

def sync_arima_predict(values, order):
    if len(values) >= min_data_length:
        model = ARIMA(values, order=order)
        model_fit = model.fit()
        forecast = model_fit.forecast(steps=1)
        return forecast[0]
    else:
        return 0

# 이상치 감지 함수
async def detect_outlier(actual, predicted, values):
    return await asyncio.to_thread(sync_detect_outlier, actual, predicted, values)

def sync_detect_outlier(actual, predicted, values):
    if len(values) >= min_data_length:
        std_dev = np.std(values)
        lower_limit = predicted - std_dev
        upper_limit = predicted + std_dev
        return actual < lower_limit or actual > upper_limit
    else:
        return False

async def process_vibration_data(axis_data, data_queue, filtered_data_queue):
    data_queue.append(axis_data)
    data_list = list(data_queue)
    filtered_list = list(filtered_data_queue)
    filtered_data = await apply_fft_filter(data_list)
    filtered_data_queue.append(filtered_data)
    predicted_value = await arima_predict(filtered_list)
    outlier_status = await detect_outlier(filtered_data, predicted_value, filtered_list)
    return filtered_data, predicted_value, outlier_status


# Bulk Insert
async def bulk_insert_vibration_data(db_conn, db_batch_buffer):
    try:
        # NoneType 데이터 필터링
        db_batch_buffer = [
            (sensor_id, time, float(value or 0), float(predicted_value or 0), bool(outlier_status), float(filtered_value or 0))
            for sensor_id, time, value, predicted_value, outlier_status, filtered_value in db_batch_buffer
            if value is not None and predicted_value is not None and filtered_value is not None
        ]
        
        if not db_batch_buffer:  # 삽입할 데이터가 없는 경우 처리
            return
        
        query = """
            INSERT INTO public.sensor_data2 (sensor_id, time, value, predicted_value, outlier_status, filtered_value) 
            VALUES ($1, $2, $3, $4, $5, $6)
        """
        await db_conn.executemany(query, db_batch_buffer)
    except Exception as e:
        print(f"[Error] Bulk Insert 중 에러 발생: {e}")


        
# Redis Stream 저장을 위한 데이터 형식
def create_vibration_json_data(sensor_id, time, axis_data, predicted_value, outlier_status, filtered_value):
    outlier_status_str = str(outlier_status)  # 한 번만 문자열로 변환
    time_str = str(time)  # 한 번만 변환
    return {
        "sensorId": sensor_id,
        "time": time_str,
        "value": axis_data,
        "predicted_value" : predicted_value,
        "outlierStatus": outlier_status_str,
        "filteredValue": filtered_value
    }

# Redis Pipeline으로 데이터 저장
async def batch_save_to_redis(redis_conn, stream_name, redis_batch_buffer, maxlen=1000):
    try:
        pipeline = redis_conn.pipeline()
        
        # NoneType 데이터 필터링
        redis_batch_buffer = [
            {key: str(value or 0) for key, value in data.items() if value is not None}
            for data in redis_batch_buffer
        ]
        
        for data in redis_batch_buffer:
            pipeline.xadd(stream_name, data, maxlen=maxlen)
        await pipeline.execute()
    except Exception as e:
        print(f"[Error] Redis Batch 저장 중 에러 발생: {e}")


async def connect_modbus():
    instrument = AsyncModbusSerialClient(port=port, baudrate=9600, parity='N', stopbits=1, bytesize=8)
    await instrument.connect()
    if instrument.connected:
        print(f"Device에 연결되었습니다: {port}")
        return instrument
    else:
        print(f"[Error] {port} 연결 실패")
        instrument.close()
        return None

# 부호 없는 16비트 값을 부호 있는 16비트 값으로 변환하는 함수
def convert_to_signed(register_value):
    if register_value > 32767:
        return register_value - 65536  # 2의 보수 변환
    return register_value
    

# 비동기적으로 여러 레지스터 값을 읽는 함수 (배치로 처리)
async def read_registers_batch(instrument, start_register, count):
    try:
        # 여러 레지스터를 한 번에 읽기
        result = await instrument.read_holding_registers(start_register, count, slave=slave_id)
        if result.isError():
            print(f"[Error] 값 읽는 중 오류 발생 {start_register} - {start_register + count - 1}")
            return None
        # 레지스터 값이 음수인 경우 변환하여 리스트로 반환
        signed_values = [convert_to_signed(value) for value in result.registers]
        return signed_values
    except ModbusException as e:
        print(f"[Error] Modbus 관련 오류 발생: {e}")
        return None
    except Exception as e:
        print(f"[Error] 알 수 없는 오류 발생: {e}")
        return None

# 가속도 데이터 읽기 (배치로 읽기)
async def read_acc_data(instrument):
    acc_data = await read_registers_batch(instrument, 52, 3)  # 52번부터 3개의 레지스터 읽기
    # print("acc_data:", acc_data)
    if acc_data is None:
        print(f"[Error] 가속도 데이터 읽기 실패")
        return None
    return get_acceleration(*acc_data)

# 각속도 데이터 읽기 (배치로 읽기)
async def read_ang_vel_data(instrument):
    ang_vel_data = await read_registers_batch(instrument, 55, 3)  # 55번부터 3개의 레지스터 읽기
    # print("ang_vel_data:", ang_vel_data)
    if ang_vel_data is None:
        print(f"[Error] 각속도 데이터 읽기 실패")
        return None
    return get_angular_velocity(*ang_vel_data)

# 진동 속도 데이터 읽기 (배치로 읽기)
async def read_vib_sp_data(instrument):
    vib_sp_data = await read_registers_batch(instrument, 58, 3)  # 58번부터 3개의 레지스터 읽기
    # print("vib_sp_data:", vib_sp_data)
    if vib_sp_data is None:
        print(f"[Error] 진동 속도 데이터 읽기 실패")
        return None
    return get_vibration_speed(*vib_sp_data)

async def main():
    instrument = await connect_modbus()
    db_conn = await db_connect()
    redis_conn = await redis_connect()
    
    if instrument is None:
        print(f"기존 연결을 종료했습니다.")
        return;

    global db_batch_buffer, redis_batch_buffer
    
    while True:        
        # 함수 실행 시작 시간
        start = time.time();
        
        try:
            # 현재 시간 한 번만 호출
            current_time = datetime.datetime.now()       

            # 각 함수 비동기적으로 실행
            acc_data_task = read_acc_data(instrument)
            ang_vel_data_task = read_ang_vel_data(instrument)
            vib_sp_data_task = read_vib_sp_data(instrument)
        
            # 모든 비동기 작업이 완료되기를 기다리기
            axis_acc, ang_vel, vib_sp = await asyncio.gather(
                acc_data_task, ang_vel_data_task, vib_sp_data_task
            )    
        
            # 각 센서 데이터 처리 비동기화 (task 생성)
            tasks = [
                process_vibration_data(axis_acc['x_axis'], data_queues['x_acc'], data_queues['filtered_x_acc']),
                process_vibration_data(axis_acc['y_axis'], data_queues['y_acc'], data_queues['filtered_y_acc']),
                process_vibration_data(axis_acc['z_axis'], data_queues['z_acc'], data_queues['filtered_z_acc']),
                
                process_vibration_data(ang_vel["x_axis"], data_queues['x_ang_vel'], data_queues['filtered_x_ang_vel']),
                process_vibration_data(ang_vel["y_axis"], data_queues['y_ang_vel'], data_queues['filtered_y_ang_vel']),
                process_vibration_data(ang_vel["z_axis"], data_queues['z_ang_vel'], data_queues['filtered_z_ang_vel']),
                
                process_vibration_data(vib_sp["x_axis"], data_queues['x_vib_sp'], data_queues['filtered_x_vib_sp']),
                process_vibration_data(vib_sp["y_axis"], data_queues['y_vib_sp'], data_queues['filtered_y_vib_sp']),
                process_vibration_data(vib_sp["z_axis"], data_queues['z_vib_sp'], data_queues['filtered_z_vib_sp'])
            ]
    
            # asyncio.gather를 사용하여 비동기 함수들을 동시에 실행
            results = await asyncio.gather(*tasks)
    
            # FFT 필터 적용 값, 상한선/하한선, 이상치 여부 상태
            filtered_x_acc, predicted_x, outlier_status_x = results[0]
            filtered_y_acc, predicted_y, outlier_status_y = results[1]
            filtered_z_acc, predicted_z, outlier_status_z = results[2]
            
            filtered_x_ang_vel, predicted_ang_x, outlier_status_ang_x = results[3]
            filtered_y_ang_vel, predicted_ang_y, outlier_status_ang_y = results[4]
            filtered_z_ang_vel, predicted_ang_z, outlier_status_ang_z = results[5]
    
            filtered_x_vib_sp, predicted_vib_x, outlier_status_vib_x = results[6]
            filtered_y_vib_sp, predicted_vib_y, outlier_status_vib_y = results[7]
            filtered_z_vib_sp, predicted_vib_z, outlier_status_vib_z = results[8]
    
            # 데이터베이스에 진동 데이터 저장
    
            #리스트에 데이터 추가
            raw_vibration_data_list = [
                (7, current_time, axis_acc["x_axis"], predicted_x, outlier_status_x, filtered_x_acc),
                (8, current_time, axis_acc["y_axis"], predicted_y, outlier_status_y, filtered_y_acc),
                (9, current_time, axis_acc["z_axis"], predicted_z, outlier_status_z, filtered_z_acc),
                
                (10, current_time, ang_vel["x_axis"], predicted_ang_x, outlier_status_ang_x, filtered_x_ang_vel),
                (11, current_time, ang_vel["y_axis"], predicted_ang_y, outlier_status_ang_y, filtered_y_ang_vel),
                (12, current_time, ang_vel["z_axis"], predicted_ang_z, outlier_status_ang_z, filtered_z_ang_vel),
                
                (13, current_time, vib_sp["x_axis"], predicted_vib_x, outlier_status_vib_x, filtered_x_vib_sp),
                (14, current_time, vib_sp["y_axis"], pdicted_vib_y, outlier_status_vib_y, filtered_y_vib_sp),
                (15, current_time, vib_sp["z_axis"], predicted_vib_z, outlier_status_vib_z, filtered_z_vib_sp)
            ]
        
            # 리스트에 key-value 쌍 데이터 추가
            vibration_data_list = [
                create_vibration_json_data(7, current_time, axis_acc["x_axis"], predicted_x, outlier_status_x, filtered_x_acc),
                create_vibration_json_data(8, current_time, axis_acc["y_axis"], predicted_y, outlier_status_y, filtered_y_acc),
                create_vibration_json_data(9, current_time, axis_acc["z_axis"], predicted_z, outlier_status_z, filtered_z_acc),
                
                create_vibration_json_data(10, current_time, ang_vel["x_axis"], predicted_ang_x, outlier_status_ang_x, filtered_x_ang_vel),
                create_vibration_json_data(11, current_time, ang_vel["y_axis"], predicted_ang_y, outlier_status_ang_y, filtered_y_ang_vel),
                create_vibration_json_data(12, current_time, ang_vel["z_axis"], predicted_ang_z, outlier_status_ang_z, filtered_z_ang_vel),
                
                create_vibration_json_data(13, current_time, vib_sp["x_axis"], predicted_vib_x, outlier_status_vib_x, filtered_x_vib_sp),
                create_vibration_json_data(14, current_time, vib_sp["y_axis"], predicted_vib_y, outlier_status_vib_y, filtered_y_vib_sp),
                create_vibration_json_data(15, current_time, vib_sp["z_axis"], predicted_vib_z, outlier_status_vib_z, filtered_z_vib_sp)
            ]
        
            # Redis에 진동 데이터 저장
            await asyncio.gather(
                # 데이터베이스에 진동 데이터 저장
                bulk_insert_vibration_data(db_conn, raw_vibration_data_list),
                batch_save_to_redis(redis_conn, stream_name, vibration_data_list)
            )

            # 함수 실행 시간 계산
            end = time.time()
            # print(f'실행 시간={end-start}')
    
            await asyncio.sleep(0.05)  # 0.1초 단위로 실행
        except Exception as e:
            print(f"Error: {e}")
            
    instrument.close()
    await db_conn.close()

if __name__ == "__main__":
    asyncio.run(main())
