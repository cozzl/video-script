import subprocess
import psutil
import os
import csv
import logging
import json

# 路径设置
input_videos_dir = "./videos/input"  # 输入视频的文件夹
output_videos_dir = "./videos/output"  # 输出视频的文件夹
vmaf_log_dir = "./vmaf_log"  # 存储vmaf日志的文件夹
csv_output = "./results.csv"  # 输出的CSV文件

# 模型路径和ffmpeg命令
vmaf_model_path = "/Users/markov/Documents/vmaf_json/vmaf_v0.6.1.json"

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 调用FFmpeg转码并打印日志
def transcode_video(input_path, output_path):
    command = f"ffmpeg -i {input_path} -c:v libx264 -b:v 1000k -y {output_path}"
    logging.info(f"执行转码命令: {command}")
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return process

# 调用FFmpeg计算VMAF和PSNR
def calculate_vmaf_psnr(distorted_video, reference_video, log_file):
    command = (
        f"ffmpeg -i {distorted_video} -i {reference_video} "
        f"-lavfi \"scale2ref=flags=bicubic[main][ref];[main][ref]libvmaf=feature=name=psnr:shortest=1:log_fmt=json:log_path={log_file}:model=path={vmaf_model_path}\" "
        f"-f null -"
    )
    logging.info(f"计算VMAF和PSNR命令: {command}")
    subprocess.run(command, shell=True)

# 监控CPU利用率
def monitor_cpu_usage(process):
    cpu_usages = []
    while process.poll() is None:
        cpu_usages.append(psutil.cpu_percent(interval=1))
    avg_cpu_usage = sum(cpu_usages) / len(cpu_usages) if cpu_usages else 0
    logging.info(f"转码CPU平均利用率: {avg_cpu_usage:.2f}%")
    return avg_cpu_usage

# 从VMAF日志中提取VMAF和PSNR
def extract_vmaf_psnr(log_file):

    with open(log_file, 'r') as f:
        log_data = f.read()
        data = json.loads(log_data)
        psnr_y = data['pooled_metrics']['psnr_y']['mean']
        psnr_cb = data['pooled_metrics']['psnr_cb']['mean']
        psnr_cr = data['pooled_metrics']['psnr_cr']['mean']
        vmaf = data['pooled_metrics']['vmaf']['mean']
        
    logging.info(f"提取结果: VMAF={vmaf}, PSNR_Y={psnr_y}, PSNR_CB={psnr_cb}, PSNR_CR={psnr_cr}")
    return vmaf, psnr_y, psnr_cb, psnr_cr

# 处理视频文件并记录VMAF、PSNR、CPU使用率
def process_videos(input_dir, output_dir, vmaf_dir, csv_file):
    video_files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
    
    # 创建CSV文件
    with open(csv_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["Video Name", "VMAF", "PSNR_Y", "PSNR_CB", "PSNR_CR", "CPU Usage"])
        
        # 遍历每个视频文件
        for video in video_files:
            input_path = os.path.join(input_dir, video)
            output_path = os.path.join(output_dir, video)
            log_file = os.path.join(vmaf_dir, f"{video}_vmaf.json")
            
            # Step 1: 转码
            transcode_process = transcode_video(input_path, output_path)
            
            # Step 2: 监控CPU利用率
            cpu_usage = monitor_cpu_usage(transcode_process)
            
            # Step 3: 等待转码完成后，计算VMAF和PSNR
            transcode_process.wait()
            calculate_vmaf_psnr(output_path, input_path, log_file)
            
            # Step 4: 从日志文件中提取VMAF和PSNR
            vmaf, psnr_y, psnr_cb, psnr_cr = extract_vmaf_psnr(log_file)
            
            # Step 5: 记录结果到CSV文件
            writer.writerow([video, vmaf, psnr_y, psnr_cb, psnr_cr, cpu_usage])
            logging.info(f"处理完成: {video}, VMAF={vmaf}, PSNR_Y={psnr_y}, PSNR_CB={psnr_cb}, PSNR_CR={psnr_cr}, CPU Usage={cpu_usage:.2f}%")

# 执行整个流程
process_videos(input_videos_dir, output_videos_dir, vmaf_log_dir, csv_output)