import sys
import json
import os
import subprocess
import time
import shlex
import numpy as np
import pandas as pd
import re
import logging
from subprocess import PIPE, Popen
from signal import alarm, signal, SIGALRM, SIGKILL

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

if sys.version_info >= (3,):
    import urllib.request as urllib2
else:
    import urllib2
logger = logging.getLogger('main')

def run_command(cmd):
    p = subprocess.Popen(shlex.split(cmd), stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    output, _ = p.communicate()
    code = p.returncode
    if code != 0:
        raise Exception('run_command error: %s' % cmd)
    return output, code

def run_cmd(args,
            cwd=None,
            shell=True,
            kill_tree=True,
            timeout=-1,
            env=None):
    '''
    Run a command with a timeout after which it will be forcibly
    killed.
    '''
    logger.debug("run_cmd: %s", args)
    class Alarm(Exception):
        pass
    def alarm_handler(signum, frame):
        raise Alarm
    p = Popen(args, shell=shell, cwd=cwd, stdout=PIPE, stderr=PIPE, env=env)
    if timeout != -1:
        signal(SIGALRM, alarm_handler)
        alarm(timeout)
    try:
        stdout, stderr = p.communicate()
        if timeout != -1:
            alarm(0)
    except Alarm:
        pids = [p.pid]
        if kill_tree:
            pids.extend(_get_process_children(p.pid))
        for pid in pids:
            # process might have died before getting to this line
            # so wrap to avoid OSError: no such process
            try:
                os.kill(pid, SIGKILL)
            except OSError:
                pass
        return -9, '', ''
    return p.returncode, stdout, stderr

def ff_probe_common(input_url, ffprobe_tool, extra_options = ""):
    show_options = " -select_streams v " + extra_options
    ff_cmd = "%s -hide_banner -loglevel quiet -print_format json %s %s" % (ffprobe_tool, show_options, input_url)
    print(ff_cmd)
    return_code, raw_output, stderr = run_cmd(ff_cmd)
    dict_info = json.loads(raw_output)
    return dict_info

def analysis_instant_bitrate(input_file):
    result_info = {}
    ffprobe = FFPROBE
    dict_info = ff_probe_common(input_file, ffprobe, "-show_packets -show_format")
    if 'packets' not in dict_info or len(dict_info['packets']) <= 0:
        return False, result_info
    
    bitrates = [] 
    next_pts_time = float(-1)
    delta_pts_time = float(0)
    start_pts_time = float(-1)
    delta_size = float(0)
    bitrate = float(0)
    for packet in dict_info['packets']:
        if next_pts_time == -1:
            next_pts_time = float(packet['dts_time'])
            delta_size = 0
            start_pts_time = next_pts_time
        
        delta_pts_time = float(packet['dts_time']) - next_pts_time 
        if delta_pts_time > 1:
            bitrate = (delta_size * 8.0) / delta_pts_time
            bitrate = bitrate / 1000.0
            
            bitrates.append(bitrate)
            
            next_pts_time = float(packet['dts_time'])
            delta_size = float(packet['size'])
        else:
            delta_size += float(packet['size'])
    datas=np.array(bitrates)
    result_info['Bitrate-pct0'] = np.quantile(datas, 0)
    result_info['Bitrate-pct10'] = np.quantile(datas, 0.1)
    result_info['Bitrate-pct50'] = np.quantile(datas, 0.5)
    result_info['Bitrate-pct90'] = np.quantile(datas, 0.9)
    result_info['Bitrate-std'] = np.std(datas)
    result_info['Bitrate'] = np.mean(datas)
    result_info['Size'] = int(dict_info['format']['size'])
    
    return True, result_info
    
def analysis_instant_vmaf(main_file, ref_file, log_path, model_path):
    ffmpeg = FFMPEG
    ff_cmd = "%s -i %s -i %s -lavfi 'scale2ref[main][ref];[main][ref]libvmaf=log_fmt=json:log_path=%s:model=path=%s:shortest=1' -f null -" % (ffmpeg, main_file, ref_file, log_path, model_path)
    print(ff_cmd)
    
    if os.path.isfile(log_path):
        os.remove(log_path)
        
    run_cmd(ff_cmd)
    
    result_info = {}
    if not os.path.isfile(log_path):
        print("analysis_instant_vmaf File does not exist" )
        return False, result_info
    
    vmafs = [] 
    with open(log_path, "r") as fp:
        vmaf_info = json.load(fp)
        frames = pd.DataFrame.from_dict(vmaf_info['frames'])
        for idx,row in frames.iterrows():
            metrics = row['metrics']
            vmafs.append(float(metrics['vmaf']))
        
        datas=np.array(vmafs)
        result_info['Vmaf-pct0'] = np.quantile(datas, 0)
        result_info['Vmaf-pct10'] = np.quantile(datas, 0.1)
        result_info['Vmaf-pct50'] = np.quantile(datas, 0.5)
        result_info['Vmaf-pct90'] = np.quantile(datas, 0.9)
        result_info['Vmaf-std'] = np.std(datas)
        result_info['Vmaf'] = np.mean(datas)
    
    if os.path.exists(log_path):
        os.remove(log_path)
    return True, result_info

def analysis_instant_psnr(main_file, ref_file, log_path):
    ffmpeg = FFMPEG
    ff_cmd = "%s -i %s -i %s -lavfi 'scale2ref[main][ref];[main][ref]psnr=stats_file=%s:shortest=1' -f null -" % (ffmpeg, main_file, ref_file, log_path)
    print(ff_cmd)
    
    if os.path.exists(log_path):
        os.remove(log_path)
        
    run_cmd(ff_cmd)
    
    result_info = {}
    if not os.path.isfile(log_path):
        print("analysis_instant_vmaf File does not exist" )
        return False, result_info
    
    psnrs = [] 
    with open(log_path, "r") as fp:
        for line in fp:
            allpsnr = re.findall(r"n:(.*?) mse_avg:(.*?) mse_y:(.*?) mse_u:(.*?) mse_v:(.*?) psnr_avg:(.*?) psnr_y:(.*?) psnr_u:(.*?) psnr_v:(.*?)", line)
            if 'nan' in allpsnr[0][5] or 'inf' in allpsnr[0][5]:
                continue
            psnrs.append(float(allpsnr[0][5]))

        datas=np.array(psnrs)
        result_info['Gpsnr-pct0'] = np.quantile(datas, 0)
        result_info['Gpsnr-pct10'] = np.quantile(datas, 0.1)
        result_info['Gpsnr-pct50'] = np.quantile(datas, 0.5)
        result_info['Gpsnr-pct90'] = np.quantile(datas, 0.9)
        result_info['Gpsnr-std'] = np.std(datas)
        result_info['Gpsnr'] = np.mean(datas)     
    
    if os.path.exists(log_path):
        os.remove(log_path)
    return True, result_info