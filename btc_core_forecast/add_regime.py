"""As-of 7/30/90 day regime context, historical diagnostic only."""
import argparse,pathlib,os,zipfile
import numpy as np
import forecast as f

def regime(a,i):
    if i<90*288:raise ValueError('90d history required')
    row=[]
    for n in (7*288,30*288,90*288):
        close=a[i-n:i+1,4];w=np.diff(np.log(close));vol=a[i-n+1:i+1,5].sum()
        row.extend([float(np.log(close[-1]/close[0])),float(np.sqrt(np.mean(w*w))),
            float(2*a[i-n+1:i+1,8].sum()/max(vol,1e-9)-1)])
    return row

def run(raw,arrays,out):
    t,a=f.read(raw);d=dict(np.load(arrays));keep=[];extra=[]
    for j,i in enumerate(d['idx']):
        if i<90*288:continue
        if t[i]!=d['anchors'][j]:raise ValueError('raw anchor correspondence mismatch')
        keep.append(j);extra.append(regime(a,i))
    for k in d:d[k]=d[k][keep]
    d['x']=np.column_stack([d['x'],np.asarray(extra)])
    destination=pathlib.Path(out);temporary=destination.with_name(destination.stem+'_writing.npz')
    np.savez_compressed(temporary,**d)
    with zipfile.ZipFile(temporary) as z:
        if z.testzip() is not None:raise ValueError('array archive corrupted')
    os.replace(temporary,destination)
    print('REGIME_ARRAYS',len(keep),'features',d['x'].shape[1],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--arrays',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.raw,a.arrays,a.output)
