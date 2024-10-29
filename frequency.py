import snap7
import psycopg2
from time import sleep
import snap7.util
from datetime import datetime

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

# 초기 상한 및 하한값 설정
upper_limit_frequency_cv, lower_limit_frequency_cv = 0, 0

# current_cv 이전 값 저장용 초기값 설정
prev_current_cv = None


from datetime import datetime
from time import sleep

# 이전 값 초기화
prev_current_cv = None

while True:
    # PLC 데이터 읽기
    buffer_sensor_db = plc.db_read(7, 0, 16)
    buffer_sensor_db_2 = plc.db_read(4, 0, 2)

    # 값 변환
    current_cv = snap7.util.get_int(buffer_sensor_db, 0) / 10
    frequency_cv = snap7.util.get_int(buffer_sensor_db, 2) / 100
    frequency_sv = snap7.util.get_int(buffer_sensor_db_2, 0) / 100

    # 상한 및 하한 설정
    if prev_current_cv is not None:
        upper_limit_current = prev_current_cv + 0.1
        lower_limit_current = prev_current_cv - 0.1
    else:
        upper_limit_current = current_cv + 0.1
        lower_limit_current = current_cv - 0.1

    upper_limit_frequency_cv = frequency_sv + 1
    lower_limit_frequency_cv = frequency_sv - 1

    # 현재 시간
    current_time = datetime.now()

    # 각 센서 데이터 삽입 준비
    data_to_insert = [
        (3, current_time, current_cv, upper_limit_current, lower_limit_current, current_cv < lower_limit_current or current_cv > upper_limit_current),
        (4, current_time, frequency_cv, upper_limit_frequency_cv, lower_limit_frequency_cv, frequency_cv < lower_limit_frequency_cv or frequency_cv > upper_limit_frequency_cv),
        (5, current_time, frequency_sv, None, None, None)  # frequency_sv의 상한선, 하한선, 이상탐지값은 결측치로 설정
    ]

    # 데이터베이스에 삽입
    try:
        cursor.executemany("""
            INSERT INTO vibration (sensor_id, "time", value, upper_limit, lower_limit, outlier_status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, data_to_insert)
        conn.commit()
    except Exception as e:
        print(f"Database insertion error: {e}")
        conn.rollback()

    # 현재 측정값을 이전 값으로 저장
    prev_current_cv = current_cv

    # 주기 설정
    sleep(0.5)

# 데이터베이스 연결 종료
conn.close()
