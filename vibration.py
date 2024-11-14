if __name__ == "__main__":
    while True:
        try:
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
            insert_vibration_data(7, axis_acc["x_axis"], filtered_x_acc, upper_limit_x, lower_limit_x, outlier_status_x)
            insert_vibration_data(8, axis_acc["y_axis"], filtered_y_acc, upper_limit_y, lower_limit_y, outlier_status_y)
            insert_vibration_data(9, axis_acc["z_axis"], filtered_z_acc, upper_limit_z, lower_limit_z, outlier_status_z)
            
            insert_vibration_data(10, ang_vel["x_axis"], filtered_x_ang_vel, upper_limit_ang_x, lower_limit_ang_x, outlier_status_ang_x)
            insert_vibration_data(11, ang_vel["y_axis"], filtered_y_ang_vel, upper_limit_ang_y, lower_limit_ang_y, outlier_status_ang_y)
            insert_vibration_data(12, ang_vel["z_axis"], filtered_z_ang_vel, upper_limit_ang_z, lower_limit_ang_z, outlier_status_ang_z)

            insert_vibration_data(13, vib_sp["x_axis"], filtered_x_vib_sp, upper_limit_vib_x, lower_limit_vib_x, outlier_status_vib_x)
            insert_vibration_data(14, vib_sp["y_axis"], filtered_y_vib_sp, upper_limit_vib_y, lower_limit_vib_y, outlier_status_vib_y)
            insert_vibration_data(15, vib_sp["z_axis"], filtered_z_vib_sp, upper_limit_vib_z, lower_limit_vib_z, outlier_status_vib_z)

            # 리스트에 데이터 추가
            vibration_data_list = [
                create_vibration_data(7, datetime.now(), axis_acc["x_axis"], upper_limit_x, lower_limit_x, outlier_status_x, filtered_x_acc),
                create_vibration_data(8, datetime.now(), axis_acc["y_axis"], upper_limit_y, lower_limit_y, outlier_status_y, filtered_y_acc),
                create_vibration_data(9, datetime.now(), axis_acc["z_axis"], upper_limit_z, lower_limit_z, outlier_status_z, filtered_z_acc),
                
                create_vibration_data(10, datetime.now(), ang_vel["x_axis"], upper_limit_ang_x, lower_limit_ang_x, outlier_status_ang_x, filtered_x_ang_vel),
                create_vibration_data(11, datetime.now(), ang_vel["y_axis"], upper_limit_ang_y, lower_limit_ang_y, outlier_status_ang_y, filtered_y_ang_vel),
                create_vibration_data(12, datetime.now(), ang_vel["z_axis"], upper_limit_ang_z, lower_limit_ang_z, outlier_status_ang_z, filtered_z_ang_vel),
                
                create_vibration_data(13, datetime.now(), vib_sp["x_axis"], upper_limit_vib_x, lower_limit_vib_x, outlier_status_vib_x, filtered_x_vib_sp),
                create_vibration_data(14, datetime.now(), vib_sp["y_axis"], upper_limit_vib_y, lower_limit_vib_y, outlier_status_vib_y, filtered_y_vib_sp),
                create_vibration_data(15, datetime.now(), vib_sp["z_axis"], upper_limit_vib_z, lower_limit_vib_z, outlier_status_vib_z, filtered_z_vib_sp)
            ]

            # # 데이터 일괄 삽입
            # for data in vibration_data_list:
            #     save_to_redis(client, stream_name, data)

            batch_save_to_redis(client, stream_name, vibration_data_list)
                
            sleep(0.01)  # 0.01초 대기 (필요에 따라 조정 가능)

        except Exception as e:
            print(f"데이터 수집 중 오류 발생: {e}")

# # PostgreSQL 연결 종료
# finally:
#     cur.close()
#     conn.close()
