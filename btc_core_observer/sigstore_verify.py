"""Prime authenticated TUF once; parallel verification uses fixed read-only root.

Signature, Rekor inclusion, issuer, workflow identity and source SHA stay required.
This helper is prepared for a NEW frozen epoch, not installed into running R5/R6.
"""
import base64,hashlib,json,pathlib,re,subprocess,tempfile,threading,shutil

def run(args,env=None):
    p=subprocess.run(args,capture_output=True,text=True,env=env,timeout=60)
    if p.returncode:raise RuntimeError(p.stderr[-900:])
    return p

def certificate_sha(bundle):
    obj=json.loads(pathlib.Path(bundle).read_text())
    data=base64.b64decode(obj['verificationMaterial']['certificate']['rawBytes'],validate=True)
    p=subprocess.run(['openssl','x509','-inform','DER','-text','-noout'],input=data,capture_output=True,timeout=10)
    if p.returncode:raise ValueError('certificate cannot be decoded')
    m=re.search(r'1\.3\.6\.1\.4\.1\.57264\.1\.3:\s*\n\s*([0-9a-f]{40})',p.stdout.decode())
    if not m:raise ValueError('certificate source SHA missing')
    return m.group(1)

class Verifier:
    def __init__(self,cosign,workdir):
        binary=shutil.which(cosign) or str(pathlib.Path(cosign).resolve())
        if not pathlib.Path(binary).is_file():raise ValueError('cosign executable missing')
        self.cosign=binary;self.workdir=pathlib.Path(workdir)
        self.lock=threading.Lock();self.root=None;self.hash=None

    def initialize(self):
        import os
        with self.lock:
            if self.root is not None:return
            self.workdir.mkdir(parents=True,exist_ok=True)
            cache=pathlib.Path(tempfile.mkdtemp(prefix='tuf-',dir=self.workdir))
            env=dict(os.environ,TUF_ROOT=str(cache.resolve()))
            # Built-in trust anchors verify TUF metadata; never trust a root from input bundle.
            run([self.cosign,'initialize'],env)
            candidates=list(cache.glob('*/targets/trusted_root.json'))
            if len(candidates)!=1:raise RuntimeError('authenticated trusted_root target absent or ambiguous')
            raw=candidates[0].read_bytes();root=json.loads(raw)
            if not root.get('certificateAuthorities') or not root.get('tlogs') or not root.get('ctlogs'):
                raise RuntimeError('incomplete trusted verification material')
            target=cache/'pinned_trusted_root.json';target.write_bytes(raw);target.chmod(0o400)
            self.root=target;self.hash=hashlib.sha256(raw).hexdigest()

    def verify(self,path,identity,issuer,source_sha):
        self.initialize();path=pathlib.Path(path)
        if hashlib.sha256(self.root.read_bytes()).hexdigest()!=self.hash:raise RuntimeError('trusted root changed after initialization')
        bundle=str(path)+'.sigstore.json'
        if certificate_sha(bundle)!=source_sha:raise RuntimeError('source commit does not match frozen SHA')
        args=[self.cosign,'verify-blob',str(path),'--bundle',bundle,
              '--trusted-root',str(self.root),'--new-bundle-format=true',
              '--certificate-identity',identity,'--certificate-oidc-issuer',issuer]
        run(args)
        return {'verified':True,'source_sha':source_sha,'trusted_root_sha256':self.hash,
                'signature_and_rekor_checks_required':True,'issuer_and_identity_required':True}
