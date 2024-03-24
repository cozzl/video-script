#!/bin/sh

os="mac"
echo "系统: $os"

ffmpeg_path="ffmpeg"
src_path="/Users/markov/Desktop/video_soure"
dst_path="/Users/markov/Desktop/score_output"
vmarf_path="/Users/markov/Documents/code/vmaf/model/vmaf_v0.6.1.json"
vmarf_log_name="vmarf_log.json"

in_name_souce=$1
echo "source video name: $in_name_souce"

in_name_flv="in.flv"
in_name_yuv="in.yuv"

out_name_flv="output.flv"
out_name_yuv="output.yuv"

out_fps=30
out_resolution="720x1280"
out_resolution_fix="1280x720"

echo "开始打分..."

echo "清空输出目录$dst_path"
rm -rf ${dst_path}/*

# 获取源流信息
in_info=`ffprobe -i ${src_path}/${in_name_souce} -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate:format=bit_rate`
in_width=`echo $in_info|grep width|sed 's/.*width=\([0-9]*\).*/\1/g'`
in_height=`echo $in_info|grep height|sed 's/.*height=\([0-9]*\).*/\1/g'`
in_frame=`echo $in_info|grep r_frame_rate|sed 's/.*r_frame_rate=\([0-9|\/]*\).*/\1/g'`
in_bit_rate=`echo $in_info|grep bit_rate|sed 's/.*bit_rate=\([0-9]*\).*/\1/g'`
echo "源流信息: width=$in_width, height=$in_height, frame=$in_frame, bitrate=$in_bit_rate"

if (($in_width > $in_height))
then
    out_resolution=$out_resolution_fix
    echo "change scale to $out_resolution"
fi
# 源流转封装
$ffmpeg_path -i ${src_path}/${in_name_souce} -c copy -f flv -y ${dst_path}/${in_name_flv} > /dev/null 2>&1
$ffmpeg_path -i ${dst_path}/${in_name_flv} -r $out_fps -f rawvideo -y ${dst_path}/${in_name_yuv} > /dev/null 2>&1

# 转码
trans_command="$ffmpeg_path -threads 6 -i ${dst_path}/${in_name_flv} \
-c:a copy -c:v libx264 \
-r $out_fps \
-crf 23 -b:v $in_bit_rate \
-copyts -threads 10 \
-filter_complex_threads 2 -filter_complex [0:v]scale=${out_resolution}:flags=bicubic \
-x264-params lookahead=4:qpmin=1:qpmax=51:bframes=1 \
-f flv -y ${dst_path}/${out_name_flv}"

echo "转码命令: $trans_command"
$trans_command > /dev/null 2>&1 &

pid=$!
echo "转码pid: $pid"

if [ "$os" = "linux" ];then 
    comput_cpu_command="top -b -n 1 -p $pid | awk 'NR>7 { sum += $9; } END { printf "%.2f", sum; }'"
    echo "use linux comput cpu command"
else
    comput_cpu_command="ps -p $pid -o %cpu|sed -n '2p'"
    echo "use mac comput cpu command"
fi
echo "comput cpu command: $comput_cpu_command"

# 初始化 CPU 总使用率和采样计数器
total_cpu_usage=0
sample_count=0

while ps -p $pid > /dev/null; do

    cpu_usage=$(eval $comput_cpu_command)
    echo "$sample_count cpu usage: $cpu_usage"

    total_cpu_usage=$(awk "BEGIN {print $total_cpu_usage + $cpu_usage}")
    sample_count=$((sample_count + 1))
    sleep 1
done
# 计算平均cpu利用率
cpu=$(awk "BEGIN {print $total_cpu_usage / $sample_count}")

#wait $pid
echo "转码执行结束"

# 获取转码流信息
out_info=`ffprobe -i ${dst_path}/${out_name_flv} -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate:format=bit_rate`
out_width=`echo $out_info|grep width|sed 's/.*width=\([0-9]*\).*/\1/g'`
out_height=`echo $out_info|grep height|sed 's/.*height=\([0-9]*\).*/\1/g'`
out_frame=`echo $out_info|grep r_frame_rate|sed 's/.*r_frame_rate=\([0-9]*\).*/\1/g'`
out_bit_rate=`echo $out_info|grep bit_rate|sed 's/.*bit_rate=\([0-9]*\).*/\1/g'`
echo "转码流信息: width=$out_width, height=$out_height, frame=$out_frame, bitrate=$out_bit_rate"

# 转码流上采样并转为yuv
$ffmpeg_path -threads 6 \
-i ${dst_path}/${out_name_flv} \
-filter_complex_threads 2 -filter_complex [0:v]scale=${in_width}x${in_height}:flags=bicubic \
-f rawvideo -y ${dst_path}/${out_name_yuv} > /dev/null 2>&1

# 打分
$ffmpeg_path \
-s ${in_width}x${in_height} -i ${dst_path}/${in_name_yuv} \
-s ${in_width}x${in_height} -i ${dst_path}/${out_name_yuv} \
-filter_complex libvmaf=feature=name=psnr:n_threads=32:model=path=${vmarf_path}:log_path=${dst_path}/${vmarf_log_name}:log_fmt=json \
-f null - > /dev/null 2>&1

# 从文件中获取psnr和vmarf
psnr_y=`grep -o '"mean": [0-9.]*' ${dst_path}/${vmarf_log_name}  | awk -F ":" '{print $2}' | sed -n "1p"`
psnr_cb=`grep -o '"mean": [0-9.]*' ${dst_path}/${vmarf_log_name} | awk -F ":" '{print $2}' | sed -n "2p"`
psnr_cr=`grep -o '"mean": [0-9.]*' ${dst_path}/${vmarf_log_name} | awk -F ":" '{print $2}' | sed -n "3p"`
vmafneg=`grep -o '"mean": [0-9.]*' ${dst_path}/${vmarf_log_name} | awk -F ":" '{print $2}' | sed -n "15p"`

echo "psnr_y: $psnr_y, psnr_cb: $psnr_cb, psnr_cr: $psnr_cr"
echo "vmafneg: $vmafneg"

echo "转码平均cpu利用率: $cpu"

echo "打分结束!"
exit 0