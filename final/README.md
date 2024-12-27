## 코드파일 정리 내역 💻

#### 1. 3sigma.py
- basic code
- 실시간으로 수집되는 데이터의 통계적 정보(평균/표준편차)를 기반으로 상한선과 하한선 설정
- 해당 기준 내에 들어오면 정상 데이터, 기준범위를 벗어나면 이상치 데이터로 판별
- 현재까지 최신 version

#### 2. Modeling.ipynb
- Hugging Face에 사전 배포된 AutoEncoder 딥러닝 모델을 사용한 이상탐지 basic code
- https://huggingface.co/keras-io/timeseries-anomaly-detection << 모델 배포
- (환경설정) Note: 'keras<3.x' or 'tf_keras' must be installed
- gpu 환경 완비 후에 적용시도?

#### 3. arima_predict.py
- arima 통계기반 모델로 filtered value 다음값 예측
- 예측한 값과 실제값 사이의 오차 계산
- 계산된 오차가 일정 수준 이상으로 발생할 시, 이상치 데이터로 판별
- 최신 버전과의 병합 필요

#### 4. 
