import hashlib,json,pathlib,tempfile,unittest
import numpy as np
import forecast as f
import prospective_audit as a

class AcceptTestSignature:
    def verify(self,*args):return {'verified':True}

class AuditTests(unittest.TestCase):
    def fixture(self,root):
        anchor=f.stamp('2026-10-13T11:30:00+00:00');end=anchor+3600000
        p={'kind':'FORECAST','source_sha':a.SOURCE_SHA,'anchor_utc':f.iso(anchor),'computed_at_utc':f.iso(anchor+15000),
           'reference_spot':100.,'samples_log_returns':{'candidate':{'1':[0.,.01,-.01]},'baseline':{'1':[0.,0.,0.]}}}
        pp=root/'prediction.json';pp.write_text(json.dumps(p)+'\n')
        bundle={'verificationMaterial':{'tlogEntries':[{'integratedTime':str((anchor+16000)//1000)}]}}
        pathlib.Path(str(pp)+'.sigstore.json').write_text(json.dumps(bundle))
        rows=[[anchor+i*300000,'100','103','99','102','1',anchor+(i+1)*300000-1] for i in range(12)]
        scores={}
        for key,v in p['samples_log_returns'].items():
            r=np.array(v['1']);prices=100*np.exp(r);lo,mid,hi=np.quantile(prices,[.1,.5,.9]);probs=np.array([(r>=np.log1p(.007)).mean(),(r<=np.log1p(-.007)).mean(),((r>np.log1p(-.007))&(r<np.log1p(.007))).mean()])
            scores[key]={'crps':f.crps(prices,102),'mae':float(abs(mid-102)),'coverage_80pct':bool(lo<=102<=hi),'brier':float(np.sum((probs-np.array([1,0,0]))**2))}
        o={'forecast_sha256':hashlib.sha256(pp.read_bytes()).hexdigest(),'anchor_utc':p['anchor_utc'],'horizon_hours':1,'received_at_utc':f.iso(end+1000),'outcome_rows':rows,'scores':scores}
        op=root/'outcome.json';op.write_text(json.dumps(o));return pp,op,o

    def test_real_arithmetic_stays_unready(self):
        with tempfile.TemporaryDirectory() as tmp:
            pp,op,_=self.fixture(pathlib.Path(tmp));r=a.verify_pair(pp,op,AcceptTestSignature())
            self.assertEqual(r['actual_endpoint'],102);self.assertFalse(r['trading_authority']);self.assertTrue(r['forecast_signed_before_outcome'])
    def test_changed_score_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pp,op,o=self.fixture(pathlib.Path(tmp));o['scores']['candidate']['crps']+=1;op.write_text(json.dumps(o))
            with self.assertRaisesRegex(ValueError,'score mismatch'):a.verify_pair(pp,op,AcceptTestSignature())
    def test_reordered_outcome_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pp,op,o=self.fixture(pathlib.Path(tmp));o['outcome_rows'][0],o['outcome_rows'][1]=o['outcome_rows'][1],o['outcome_rows'][0];op.write_text(json.dumps(o))
            with self.assertRaisesRegex(ValueError,'grid gap'):a.verify_pair(pp,op,AcceptTestSignature())
    def test_late_signed_forecast_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pp,op,o=self.fixture(pathlib.Path(tmp));bundle={'verificationMaterial':{'tlogEntries':[{'integratedTime':str(f.stamp(o['received_at_utc'])//1000)}]}}
            pathlib.Path(str(pp)+'.sigstore.json').write_text(json.dumps(bundle))
            with self.assertRaisesRegex(ValueError,'signed'):a.verify_pair(pp,op,AcceptTestSignature())
    def test_different_forecast_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pp,op,o=self.fixture(pathlib.Path(tmp));o['forecast_sha256']='0'*64;op.write_text(json.dumps(o))
            with self.assertRaisesRegex(ValueError,'another forecast'):a.verify_pair(pp,op,AcceptTestSignature())

if __name__=='__main__':unittest.main()
