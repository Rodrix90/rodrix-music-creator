import subprocess, os, time

cmd_process = [
    'ffmpeg', '-y', '-i', 'tests/test_hymn/test_raw_3min.wav',
    '-af', 'highpass=f=75:w=0.7,afftdn=nr=10:nf=-45:tn=1,equalizer=f=420:t=q:w=1.8:g=-2.5,equalizer=f=3400:t=q:w=1.2:g=2.0,highshelf=f=11000:g=2.5,compand=attacks=0.03:decays=0.15:points=-70/-70|-35/-35|-18/-14|0/-6:gain=1,loudnorm=I=-14:TP=-1.0:LRA=7',
    '-c:a', 'pcm_s16le', 'tests/test_hymn/test_out.wav'
]

p = subprocess.Popen(cmd_process, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
max_mem_kb = 0
while p.poll() is None:
    try:
        out = subprocess.check_output(f'tasklist /FI "PID eq {p.pid}" /FO CSV /NH', shell=True, text=True)
        parts = out.strip().split('","')
        if len(parts) >= 5:
            mem_str = parts[4].replace('"', '').replace(' K', '').replace(',', '').replace('.', '').strip()
            if mem_str.isdigit():
                max_mem_kb = max(max_mem_kb, int(mem_str))
    except Exception:
        pass
    time.sleep(0.04)

print(f"Peak FFmpeg RAM consumption for 3.5 min track: {max_mem_kb / 1024:.2f} MB")
