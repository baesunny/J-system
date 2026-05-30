# J-system 🏭
> IoT 센서 기반 산업 설비 예지보전(Predictive Maintenance) 시스템

[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 🎯 프로젝트 개요

산업용 설비에 장착된 IoT 센서에서 실시간으로 수집한 진동, 주파수, 전류 데이터 등을 분석하여 설비의 이상 상태를 조기에 감지하고 예방하는 예지보전 시스템이다.

### 핵심 기능
- **실시간 센서 데이터 수집**: Modbus RTU 및 Snap7 프로토콜 지원
- **신호 처리**: FFT 필터, Kalman 필터를 통한 노이즈 제거
- **이상치 탐지**: 통계 기반(3-sigma), LSTM, AutoEncoder 기반 탐지
- **실시간 시스템**: PostgreSQL + Redis Stream 기반 고속 데이터 파이프라인
- **시계열 예측**: ARIMA 모델을 활용한 미래값 예측 및 편차 분석

---

## 📁 프로젝트 구조

```
J-system/
├── 📄 README.md                           # 프로젝트 소개
├── 📄 제이시스템_예지보전시스템.pdf         # 최종 보고서
├── 📊 modeling_visualization.ipynb        # 모델링 시각화
│
├── 🔧 frequency.py                        # PLC 기반 주파수/전류 데이터 수집
├── 🔧 vibration.py                        # Modbus 기반 센서 데이터 수집 (가속도, 각속도, 진동)
│
├── 📂 file/                               # 초기 데이터 분석 파일
│   ├── __acceleration_velocity_speed.ipynb
│   └── __frequency.ipynb
│
└── 📂 final/                              # 최종 프로젝트 결과
    │
    ├── 📂 anomaly_detection/
    │   │
    │   ├── 🤖 Modeling/                   # 머신러닝 기반 이상탐지
    │   │   ├── AutoEncoder_Modeling.ipynb       # 딥러닝(AutoEncoder) 기반 이상탐지
    │   │   ├── LSTM_Modeling.ipynb              # 시계열 예측(LSTM) 기반 이상탐지
    │   │   └── preprocessed_data0912(symbolic).csv
    │   │
    │   └── ⚡ real_time/                  # 실시간 이상탐지 알고리즘
    │       ├── 3sigma.py                       # 3-Sigma 기반 이상치 판정 (✓ 최신)
    │       ├── arima_predict.py                # ARIMA 시계열 예측
    │       └── arima_predict-v2.py             # ARIMA v2 개선 버전
    │
    ├── 📊 data_analysis/                  # 데이터 분석 및 필터 검증
    │   ├── FFTfilter_KALMANfilter.ipynb        # FFT vs Kalman 필터 비교 분석
    │   ├── modeling_visualization.ipynb
    │   ├── 1024_final.csv                      # 실제 센서 데이터
    │   ├── 1024_sensor7_3sigma.csv
    │   └── sample_data.csv
    │
    └── 📚 NAS/                             # 센서/장비 관련 조사 자료
        └── readme.md
```

---

## 🔌 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                  산업 설비 센서                              │
│  (진동, 주파수, 전류 센서 - 모니터링)                        │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                  데이터 수집 계층                            │
│  • Modbus RTU (vibration.py)                                │
│  • Snap7 PLC (frequency.py)                                 │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                  신호 처리 계층                              │
│  • FFT 필터 (고주파 노이즈 제거)                             │
│  • Kalman 필터 (동적 신호 추적)                             │
│  • 동적 상한/하한선 계산                                    │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                  이상탐지 계층                               │
│  • 3-Sigma (통계 기반, 실시간)                              │
│  • ARIMA (시계열 예측)                                      │
│  • LSTM / AutoEncoder (심층학습)                            │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                  저장 계층                                   │
│  • PostgreSQL (분석용 히스토리)                              │
│  • Redis Stream (실시간 모니터링)                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔑 핵심 모듈 설명

### 1️⃣ **데이터 수집**

#### `frequency.py` - PLC 센서 데이터 수집
- **목적**: 설비의 전류, 주파수(CV/SV) 실시간 수집
- **기술**: Snap7 라이브러리를 이용한 PLC 통신
- **주요 센서**:
  - Sensor ID 3: 전류 (Current) [A]
  - Sensor ID 4: 주파수 실제값 (Frequency CV) [Hz]
  - Sensor ID 5: 주파수 목표값 (Frequency SV) [Hz]

```python
# 사용 방법
python frequency.py  # PLC에서 0.5초 간격으로 데이터 수집
```

#### `vibration.py` - Modbus 센서 데이터 수집
- **목적**: 가속도, 각속도, 진동 속도 3축 데이터 수집
- **기술**: Modbus RTU 프로토콜
- **주요 센서**:
  - ID 7-9: 가속도 (X, Y, Z축) [m/s²]
  - ID 10-12: 각속도 (X, Y, Z축) [deg/s]
  - ID 13-15: 진동 속도 (X, Y, Z축) [mm/s]

```python
# 사용 방법
python vibration.py  # Modbus 센서에서 0.5초 간격으로 데이터 수집
```

---

### 2️⃣ **신호 처리**

#### FFT 필터 (주파수 영역 필터링)
```python
# 용도: 고주파 노이즈 제거
# 방식: Fast Fourier Transform으로 주파수 성분 분석 후 5번째 이후 제거
filtered_value = apply_fft_filter(data_queue)
```

#### 동적 상한/하한선 계산
```python
# 방식: 시계열 데이터의 평균과 표준편차 기반
# 상한 = 평균 + 4σ (조정 가능)
# 하한 = 평균 - 4σ
upper_limit, lower_limit = calculate_limits_and_outlier_status(data_queue)
```

---

### 3️⃣ **이상탐지 알고리즘**

#### ⚡ **3-Sigma (통계 기반)**
- **위치**: `final/anomaly_detection/real_time/3sigma.py`
- **특징**: 
  - 실시간 처리 가능
  - 연산량 최소
  - 새로운 데이터 추가 시 동적 업데이트
- **원리**: 정상 데이터가 평균±3σ 범위 내에 있다는 가정

```python
# 이상치 판정
outlier = not (lower_limit <= value <= upper_limit)
```

#### 📈 **ARIMA (시계열 예측)**
- **위치**: `final/anomaly_detection/real_time/arima_predict.py`
- **특징**:
  - 미래값 예측 및 오차 분석
  - 추세 변화 감지
- **원리**: AutoRegressive Integrated Moving Average로 다음 예측값 계산
- **이상 판정**: 실제값과 예측값의 오차가 임계값 초과 시

#### 🤖 **LSTM (딥러닝 시계열)**
- **위치**: `final/anomaly_detection/Modeling/LSTM_Modeling.ipynb`
- **특징**:
  - 장기 의존성(Long-term Dependency) 학습
  - 복잡한 시계열 패턴 포착
- **학습 데이터**: Simulation_data
- **참고**: GPU 환경 필요

#### 🧠 **AutoEncoder (비지도학습)**
- **위치**: `final/anomaly_detection/Modeling/AutoEncoder_Modeling.ipynb`
- **특징**:
  - 정상 패턴을 학습한 후 편차 탐지
  - Hugging Face 사전 학습 모델 사용
- **모델**: [keras-io/timeseries-anomaly-detection](https://huggingface.co/keras-io/timeseries-anomaly-detection)
- **참고**: `keras<3.x` 또는 `tf_keras` 필수

---

### 4️⃣ **데이터 분석**

#### `FFTfilter_KALMANfilter.ipynb`
- **목적**: FFT 필터 vs Kalman 필터 성능 비교
- **분석 데이터**: `1024_final.csv`
- **평가 지표**: RMSE (Root Mean Square Error)
- **결론**: 더 적합한 필터 선정 기준 제시

---

## 🚀 설치 및 실행

### 요구사항
```
Python 3.8+
pip install -r requirements.txt
```

### 필수 패키지
```
# 데이터 수집
minimalmodbus==0.4.6    # Modbus 통신
snap7==1.3.0.1          # PLC 통신 (Snap7)
psycopg2-binary==2.9.x  # PostgreSQL
redis==4.5.x            # Redis

# 신호 처리 및 분석
numpy==1.23.x
scipy==1.9.x

# 머신러닝
tensorflow==2.12.x  # LSTM, AutoEncoder
scikit-learn==1.3.x # ARIMA (statsmodels)

# 기타
jupyter==1.0.x
matplotlib==3.7.x
pandas==1.5.x
```

### 데이터베이스 설정
```sql
-- PostgreSQL 테이블 생성
CREATE TABLE vibration (
    id SERIAL PRIMARY KEY,
    sensor_id INT NOT NULL,
    "time" TIMESTAMP NOT NULL,
    value FLOAT NOT NULL,
    filtered_value FLOAT,
    upper_limit FLOAT,
    lower_limit FLOAT,
    outlier_status BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sensor_time ON vibration(sensor_id, "time");
```

### 환경 변수 설정 (.env)
```
# PLC 설정
PLC_IP=<your_plc_ip>
PLC_RACK=0
PLC_SLOT=1

# 데이터베이스
DB_HOST=localhost
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your_password
DB_PORT=5432

# Redis
REDIS_URL=redis://localhost
REDIS_STREAM_NAME=sensorDataStream

# Modbus
MODBUS_PORT=COM3
MODBUS_SLAVE_ID=80
```

---

## 📊 주요 성과

| 항목 | 내용 |
|------|------|
| **이상탐지 정확도** | 3-Sigma 90%+ (정상 데이터 기준) |
| **실시간 처리** | 0.5초 주기 센서 데이터 처리 |
| **데이터 처리량** | 초당 9개 센서 × 무한 스트림 저장 |
| **조기 경고** | ARIMA 기반 미래 편차 예측 |
| **이상 패턴 인식** | LSTM/AutoEncoder로 미지 이상 탐지 |

---

## 🔬 기술 스택

### 통신
- **Modbus RTU**: 센서 데이터 수집
- **Snap7**: PLC 데이터 수집

### 신호 처리
- **NumPy/SciPy**: FFT, Kalman 필터
- **Pandas**: 시계열 데이터 관리

### 이상탐지
- **Statistical**: 3-Sigma, Z-Score
- **Time Series**: ARIMA, Exponential Smoothing
- **Deep Learning**: LSTM, AutoEncoder (Keras/TensorFlow)

### 저장소
- **PostgreSQL**: 장기 데이터 저장
- **Redis**: 실시간 스트림 처리

### 개발 도구
- **Jupyter Notebook**: 데이터 분석 및 실험
- **Python 3.8+**: 주 개발 언어

---

## 📝 파일별 설명

| 파일명 | 용도 |
|--------|------|
| `frequency.py` | PLC 센서 수집 |
| `vibration.py` | Modbus 센서 수집 |
| `3sigma.py` | 실시간 이상탐지 |
| `arima_predict.py` | ARIMA 예측 |
| `arima_predict-v2.py` | ARIMA v2 |
| `LSTM_Modeling.ipynb` | 딥러닝 이상탐지 |
| `AutoEncoder_Modeling.ipynb` | AutoEncoder |
| `제이시스템_예지보전시스템.pdf` | IoT 예지보전 시스템 최종 보고서 |

---

## 보고서

| 파일 | 설명 |
| --- | --- |
| `제이시스템_예지보전시스템.pdf` | 제이시스템 IoT 예지보전 시스템 최종 보고서 (센서 수집, 신호 처리, 이상탐지, 실험 결과 정리) |