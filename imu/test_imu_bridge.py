#!/usr/bin/env python3
"""Tests for imu-bridge.py that need no IMU and no Pi: run  python3 imu/test_imu_bridge.py
A pseudo-terminal stands in for the USB IMU. Uses local TCP ports 14001-14021."""
import os, pty, socket, subprocess, sys, time, threading, importlib.util, tty
B=os.path.join(os.path.dirname(os.path.abspath(__file__)),'imu-bridge.py')
spec=importlib.util.spec_from_file_location('ib',B); ib=importlib.util.module_from_spec(spec); spec.loader.exec_module(ib)

def dataconv(tokens):  # exact port of IMUData.dataConv
    dec=[int(t) for t in tokens]; out=[]
    for i in range(9):
        v=float(dec[2*i]*256+dec[2*i+1])
        if v>32768: v-=65536
        out.append(v)
    return [out[0]/2048,out[1]/2048,out[2]/2048,out[3]/16.4,out[4]/16.4,out[5]/16.4]+out[6:]

# 1. encoder round trip incl. edges
for v in [0,1,-1,32767,-32767,-32768,40000,12345,-12345]:
    tok=ib.encode([v]*9).decode().split(',')
    got=dataconv(tok)[6]
    exp=max(-32767,min(32767,v))
    assert got==exp,(v,got); assert ib.valid_line(ib.encode([v]*9))
print('encode round trip ok')
assert ib.frame_line(b'12 418959432132') == (12, 418959432132)
assert ib.frame_line(b'12') is None and ib.frame_line(b'x 1') is None and ib.frame_line(b'1 2 3') is None
print('frame line ok')
assert not ib.valid_line(b'1,2,3'); assert not ib.valid_line(b','.join([b'256']*18)); assert not ib.valid_line(b'')

# 2. fake USB IMU on a pty
m,s=pty.openpty(); tty.setraw(s); path=os.ttyname(s)
stop=False
def feed():
    n=0
    while not stop:
        if n%50==7: os.write(m,b'garbage line\r\n')
        os.write(m, ib.encode([0,0,2048,0,int(100*16.4),0,1,2,3])+b'\r\n'); n+=1
        time.sleep(1/145)
threading.Thread(target=feed,daemon=True).start()
env=dict(os.environ,IMU_DEV=path,IMU_PORT='14001')
p=subprocess.Popen([sys.executable,'-I',B],env=env,stderr=subprocess.PIPE,text=True)
time.sleep(1.0)
c=socket.create_connection(('127.0.0.1',14001)); buf=b''; t0=time.time()
while time.time()-t0<3: buf+=c.recv(65536)
lines=buf.split(b'\n'); lines=[l for l in lines[1:-1]]  # drop partial ends
for l in lines:
    assert l.endswith(b'\r'); tok=l.rstrip(b'\r').split(b',')
    assert len(tok)==18, l
    d=dataconv(tok); assert abs(d[2]-1)<1e-9 and abs(d[4]-100)<0.1 and d[6:]==[1,2,3], d
print(f'pty relay ok: {len(lines)} lines in 3 s = {len(lines)/3:.0f}/s, garbage filtered')
stop=True; c.close(); p.terminate(); print(p.communicate()[1])

# 2b. the line ending the real IMU sends: CR LF CR, so every line after the first opens with a CR
m2,s2=pty.openpty(); tty.setraw(s2); run2=[True]
def feed_cr(fd=m2, run=run2):
    while run[0]:
        os.write(fd, ib.encode([0,0,2048,0,int(100*16.4),0,1,2,3])+b'\r\n\r')
        time.sleep(1/30)
threading.Thread(target=feed_cr,daemon=True).start()
p=subprocess.Popen([sys.executable,'-I',B],env=dict(os.environ,IMU_DEV=os.ttyname(s2),IMU_PORT='14021',IMU_SYNC_PORT='0'),stderr=subprocess.PIPE,text=True)
time.sleep(1.0)
c=socket.create_connection(('127.0.0.1',14021)); c.settimeout(0.2); buf=b''; t0=time.time()
while time.time()-t0<3:
    try: buf+=c.recv(65536)
    except socket.timeout: pass
lines=buf.split(b'\n')[1:-1]
assert len(lines)>60, f'only {len(lines)} lines relayed in 3 s from an IMU that ends lines with CR LF CR'
for l in lines:
    assert l.endswith(b'\r') and not l.startswith(b'\r'), l
    assert ib.valid_line(l[:-1]), l
print(f'CR LF CR line ending ok: {len(lines)} lines in 3 s = {len(lines)/3:.0f}/s')
run2[0]=False; c.close(); p.terminate(); print(p.communicate()[1])

# 3. sim mode rate
p=subprocess.Popen([sys.executable,'-I',B],env=dict(os.environ,IMU_DEV='sim',IMU_PORT='14002'),stderr=subprocess.PIPE,text=True)
time.sleep(0.5); c=socket.create_connection(('127.0.0.1',14002)); buf=b''; t0=time.time()
while time.time()-t0<4: buf+=c.recv(65536)
n=buf.count(b'\n'); assert all(len(l.rstrip(b'\r').split(b','))==18 for l in buf.split(b'\n')[1:-1])
print(f'sim ok: {n/4:.1f} lines/s'); p.terminate(); print(p.communicate()[1])

# ---- synchronized output ----
def dataconv(tok):
    v=[float(int(tok[2*i])*256+int(tok[2*i+1])) for i in range(9)]
    v=[x-65536 if x>32768 else x for x in v]; return v
def grab(port, secs):
    c=socket.create_connection(('127.0.0.1',port)); c.settimeout(0.2); buf=b''; t0=time.time()
    while time.time()-t0<secs:
        try: buf+=c.recv(65536)
        except socket.timeout: pass
    c.close(); return buf

m,s=pty.openpty(); tty.setraw(s); path=os.ttyname(s); run=[True]
good=ib.encode([0,0,2048,0,int(100*16.4),0,1,2,3])
def feed():
    n=0
    while run[0]:
        # every 10th write: three lines in one write; every 25th line: garbage
        k=3 if n%10==0 else 1
        data=b''
        for _ in range(k):
            data+= (b'garbage\r\n' if n%25==24 else good+b'\r\n'); n+=1
        os.write(m,data); time.sleep(k/145)
threading.Thread(target=feed,daemon=True).start()
p=subprocess.Popen([sys.executable,'-I',B],env=dict(os.environ,IMU_DEV=path,IMU_PORT='14011',IMU_SYNC_PORT='14012'),stderr=subprocess.PIPE,text=True)
time.sleep(1.0)
res={}
th=[threading.Thread(target=lambda k=k: res.__setitem__(k,grab(k,3))) for k in (14011,14012)]
[t.start() for t in th]; [t.join() for t in th]
run[0]=False

# raw port: byte-identical format, 18 tokens only
raw=res[14011].split(b'\n')[1:-1]
assert raw and all(l==good+b'\r' for l in raw), raw[:3]
print(f'4001-style raw ok: {len(raw)} lines, all exactly the IMU line + CR LF')

# sync port
sl=res[14012].split(b'\r\n')
assert sl[0]==ib.SYNC_HEADER.rstrip(b'\r\n'), sl[0]
print('header:', sl[0].decode())
rows=[l.split(b',') for l in sl[1:] if l]
assert all(len(r)==21 for r in rows)
seq=[int(r[0]) for r in rows]; mono=[int(r[1]) for r in rows]; wall=[int(r[2]) for r in rows]
assert all(b>a for a,b in zip(seq,seq[1:]))
gaps=[b-a for a,b in zip(seq,seq[1:]) if b-a!=1]
assert gaps and all(g==2 for g in gaps), gaps          # each skipped garbage line shows as a gap of 2
assert all(b>=a for a,b in zip(mono,mono[1:]))
assert all(dataconv(r[3:])==[0,0,2048,0,int(100*16.4),0,1,2,3] for r in rows)
shared=sum(1 for a,b in zip(mono,mono[1:]) if a==b)
assert shared>0
# seq consecutive within a shared-stamp group
for i in range(1,len(rows)):
    if mono[i]==mono[i-1]: assert seq[i]-seq[i-1] in (1,2)
assert abs(wall[-1]/1e6-time.time())<5
print(f'sync ok: {len(rows)} rows, {len(gaps)} seq gaps (skipped lines), {shared} rows share a stamp (3-line writes), wall clock current')
p.terminate(); print(p.communicate()[1])

# sync port off
p=subprocess.Popen([sys.executable,'-I',B],env=dict(os.environ,IMU_DEV='sim',IMU_PORT='14013',IMU_SYNC_PORT='0'),stderr=subprocess.PIPE,text=True)
time.sleep(0.5)
try: socket.create_connection(('127.0.0.1',14014),timeout=0.5); print('?')
except OSError: pass
r=grab(14013,1); assert r.count(b'\n')>100
p.terminate(); err=p.communicate()[1]; assert 'sync' not in err.split('serving')[1].split('\n')[0] if 'serving' in err else True
print('IMU_SYNC_PORT=0: only the raw output runs')
