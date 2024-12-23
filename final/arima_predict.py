import snap7
from time import sleep
import snap7.util
import psycopg2
from datetime import datetime
from statsmodels.tsa.arima.model import ARIMA
import numpy as np

# PLC 연결
plc = snap7.client.Client()
plc.connect("192.168.0.120", 0, 1)

# PostgreSQL 연결
db = psycopg2.connect(host='localhost', dbname='postgres', user='postgres', password='1234', port=5432)
cursor = db.cursor()

# 센서 값 저장용 리스트 (초기에는 비어 있음)
temp_values = []
rh_values = []

# ARIMA 모델 학습을 위한 최소 데이터 길이
min_data_length = 10

def arima_predict(values, order=(1,1,1)):
    """ARIMA 모델을 사용하여 다음 값을 예측."""
    if len(values) >= min_data_length:
        model = ARIMA(values, order=order)
        model_fit = model.fit()
        forecast = model_fit.forecast(steps=1)  # 다음 1개의 값 예측
        return forecast[0]
    else:
        return 0  # 데이터가 부족하면 0 반환

def detect_outlier(actual, predicted, values):
    """실제 값이 예측 값에서 표준편차 범위를 벗어나면 이상치로 간주."""
    if len(values) >= min_data_length:
        std_dev = np.std(values)  # 표준편차 계산
        lower_limit = predicted - std_dev
        upper_limit = predicted + std_dev
        return actual < lower_limit or actual > upper_limit  # 이상치 판별
    else:
        return False  # 데이터가 부족하면 이상치 판정 없음

while True:
    # PLC로부터 데이터 읽기
    buffer_sensor_db = plc.db_read(7, 0, 16)
    
    # 센서 값 추출
    raw_temp_cv = round(snap7.util.get_real(buffer_sensor_db, 8), 2)
    raw_rh_cv = round(snap7.util.get_real(buffer_sensor_db, 12), 2)

    # 현재 시간
    current_time = datetime.now()
    
    # 1. 온도 데이터 처리
    temp_values.append(raw_temp_cv)
    if len(temp_values) > min_data_length:
        temp_values = temp_values[-100:]  # 메모리 관리를 위해 최근 100개의 데이터만 유지
    predicted_temp = round(arima_predict(temp_values), 2)
    outlier_temp = bool(detect_outlier(raw_temp_cv, predicted_temp, temp_values))
    
    cursor.execute("""
        INSERT INTO public.sensor_data2 (sensor_id, "time", value, arima_value, outlier_status)
        VALUES (%s, %s, %s, %s, %s)
    """, (1, current_time, raw_temp_cv, predicted_temp, outlier_temp))
    
    # 2. 습도 데이터 처리
    rh_values.append(raw_rh_cv)
    if len(rh_values) > min_data_length:
        rh_values = rh_values[-100:]  # 메모리 관리를 위해 최근 100개의 데이터만 유지
    predicted_rh = round(arima_predict(rh_values), 2)
    outlier_rh = bool(detect_outlier(raw_rh_cv, predicted_rh, rh_values))

    cursor.execute("""
        INSERT INTO public.sensor_data2 (sensor_id, "time", value, arima_value, outlier_status)
        VALUES (%s, %s, %s, %s, %s)
    """, (2, current_time, raw_rh_cv, predicted_rh, outlier_rh))
    
    # 데이터베이스에 변경사항 적용
    db.commit()
    
    # 출력 (옵션)
    print(f"Raw temp = {raw_temp_cv}°C, Predicted temp = {predicted_temp}°C, Outlier = {outlier_temp}")
    print(f"Raw rh = {raw_rh_cv}%, Predicted rh = {predicted_rh}%, Outlier = {outlier_rh}")
    
    # 대기 시간
    sleep(0.5)
