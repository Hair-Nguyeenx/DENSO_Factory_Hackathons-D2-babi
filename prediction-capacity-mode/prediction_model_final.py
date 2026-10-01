import numpy as np 
import pandas as pd 
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error, mean_absolute_percentage_error
import joblib

data_path = "denso_logistics_simulation_test.csv"

df = pd.read_csv(data_path)
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.set_index('timestamp', inplace=True)
df = df.asfreq('h')

train = df.loc['2026'].copy()

#Tạo các rolling lag features cho workload_inbound và workload_outbound 
def create_lag_feature(df, target_cols):
    feature = pd.DataFrame(index=df.index)
    y = df[target_cols]
    #Biến trễ theo giờ
    for lag, name in [(1, '1h'), (2, '2h'), (3, '3h'), (4, '4h'), 
                      (12, '12h'), (18, '18h'), (24, '24h'), (72, '3d'), (168, '7d')]:
        feature[f'lag_{name}'] = y.shift(lag)
    #Biến trễ trung bình trong vòng 6h 12h 24h gần nhất(không tính giờ để predict)
    for average, name in [(3, '3h'), (6, '6h'), (12, '12h'), (24, '24h')]:
        feature[f'rollmean_{name}'] = y.shift(1).rolling(average).mean()
    # Tỷ lệ biến thiên ngắn hạn (t-1 so với t-3)
    feature['spike_ratio_1h_3h'] = (y.shift(1) + 1) / (y.shift(3) + 1)
    
    # Gia tốc biến thiên (t-1 trừ t-2)
    feature['diff_1h_2h'] = y.shift(1) - y.shift(2)
    
    # Đỉnh trần cao nhất trong 24 giờ qua
    feature['rollmax_24h'] = y.shift(1).rolling(24).max()

    # Tỷ lệ so với mức nền 6 giờ gần nhất
    feature['ratio_to_rollmean_6h'] = (y.shift(1) + 1) / (feature['rollmean_6h'] + 1)

    #Đặt trưng nhịp thời gian của kho logistics
    feature['hour'] = df.index.hour
    feature['dayofweek'] = df.index.dayofweek
    feature['month'] = df.index.month
    feature['is_weekend'] = (df.index.dayofweek >= 5).astype(int)

    #Mã hóa định danh các ca làm việc để mô hình hiểu được là việc bước nhảy workload sáng sớm 
    #là một điều bình thường chứ không có nguy cơ gây ra nghẽn ( ở đây nghĩa là ca tối -> sáng)
    # 0: Ca đêm (20:00 - 05:00) - Khối lượng thấp
    # 1: Chuyển giao đầu ca sáng (06:00 - 07:00) - Tự nhiên tăng vọt
    # 2: Cao điểm sáng (08:00 - 10:00) - Khối lượng cực đại
    # 3: Nghỉ trưa (11:00 - 12:00) - Trùng xuống
    # 4: Cao điểm chiều (14:00 - 16:00) - Tăng cao
    # 5: Ca chiều bình thường (13:00, 17:00 - 19:00)
    hours = df.index.hour

    shift_code = np.zeros(len(df), dtype=int)
    shift_code[(hours >= 20) | (hours <= 5)] = 0
    shift_code[(hours == 6) | (hours == 7)] = 1
    shift_code[(hours >= 8) & (hours <= 10)] = 2
    shift_code[(hours >= 11) & (hours <= 12)] = 3
    shift_code[(hours >= 14) & (hours <= 16)] = 4
    shift_code[(hours == 13) | ((hours >= 17) & (hours <= 19))] = 5
    feature['shift_pattern'] = shift_code

    feature['target'] = y
    return feature

#bây giờ sẽ huấn luyện 2 mô hình riêng biệt cho workload_inbound và outbound 

trained_models = {}
feature_column_dict = {}
targets = ['workload_inbound', 'workload_outbound']
for target in targets:
    feature = create_lag_feature(df, target)
    feature_train = feature.loc['2026'].dropna()
    X_cols = [c for c in feature_train.columns if c != "target"]
    X_train = feature_train[X_cols]
    y_train = feature_train["target"]

    model = HistGradientBoostingRegressor(
        max_iter=400, 
        max_depth=6, 
        learning_rate=0.04, 
        l2_regularization=0.1, 
        random_state=42
    )

    model.fit(X_train, y_train)

    preds = model.predict(X_train)
    mae = mean_absolute_error(y_train, preds)
    rmse = np.sqrt(mean_squared_error(y_train, preds))
    print(f"Kết quả Train 2026 [{target}] -> MAE: {mae:.2f} | RMSE: {rmse:.2f}")

    trained_models[target] = model
    feature_column_dict[target] = X_cols

joblib.dump(trained_models['workload_inbound'], 'model_inbound.pkl')
joblib.dump(trained_models['workload_outbound'], 'model_outbound.pkl')
joblib.dump(feature_column_dict, 'model_features.pkl')

print("ĐÃ LƯU THÀNH CÔNG:")
print(" model_inbound.pkl   (Mô hình Inbound)")
print(" model_outbound.pkl  (Mô hình Outbound)")
print(" model_features.pkl (Cấu trúc đặc trưng huấn luyện)")

