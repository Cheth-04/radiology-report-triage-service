"""Real Docker-stack smoke test (synthetic reports only, stdlib HTTP).

Usage (after compose up, migration, and user creation):
  python3 scripts/e2e_smoke.py --url http://localhost:8000 \
    --radiologist radiologist@example.com --admin admin@example.com
Passwords are prompted (not placed in terminal history).
"""
import argparse
import getpass
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

SAMPLES = [
    ('CT head', 'Acute intraparenchymal hemorrhage in the left basal ganglia measuring 3.2 cm with 4 mm midline shift. Impression: Acute intracranial hemorrhage.', True, 'CT'),
    ('Chest X-ray pneumothorax', 'Large right-sided pneumothorax with partial lung collapse. Impression: Large right pneumothorax.', True, 'X-ray'),
    ('MRI knee', 'Partial-thickness tear of the anterior cruciate ligament. Mild joint effusion. Impression: Partial ACL tear.', False, 'MRI'),
    ('Normal chest X-ray', 'Lungs are clear. Heart size normal. No pleural effusion. Impression: No acute cardiopulmonary abnormality.', False, 'X-ray'),
    ('CT abdomen', 'Simple 1.5 cm cyst in the right kidney. Liver, spleen and pancreas are unremarkable. Impression: Benign renal cyst.', False, 'CT'),
]

def request(root, path, method='GET', payload=None, token=None, form=False):
    headers = {'Accept':'application/json'}
    if token: headers['Authorization'] = f'Bearer {token}'
    data = None
    if payload is not None:
        if form:
            data = urllib.parse.urlencode(payload).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            data = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(root + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())

def login(root, email, password):
    status, payload = request(root, '/auth/login', 'POST', {'username': email, 'password': password}, form=True)
    if status != 200: raise RuntimeError(f'Login for {email} failed: HTTP {status}')
    return payload['access_token']

def require(condition, message):
    if not condition: raise AssertionError(message)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://localhost:8000')
    parser.add_argument('--radiologist', required=True)
    parser.add_argument('--admin', required=True)
    parser.add_argument('--timeout', type=int, default=60)
    args = parser.parse_args()
    root=args.url.rstrip('/')
    doctor_password=getpass.getpass('Radiologist password: ')
    admin_password=getpass.getpass('Admin password: ')
    doctor=login(root,args.radiologist,doctor_password)
    admin=login(root,args.admin,admin_password)
    require(request(root, '/ready')[0] == 200, 'Not ready')
    require(request(root,'/reports','POST',{'report_text': SAMPLES[0][1]})[0]==401,'Unauthenticated upload must be 401')
    require(request(root,'/reports','POST',{'report_text': SAMPLES[0][1]},admin)[0]==403,'Admin upload must be 403')
    require(request(root,'/reports','POST',{'report_text': ' '},doctor)[0]==422,'Invalid report must be 422')
    for name,report_text,critical,modality in SAMPLES:
        status, body=request(root,'/reports','POST',{'report_text':report_text},doctor)
        require(status==202, f'{name}: POST status {status} {body}')
        job_id=body['job_id']
        uuid.UUID(job_id)
        require(body['status']=='queued',f'{name}: submission not queued')
        deadline=time.monotonic()+args.timeout
        while True:
            state, body=request(root,f'/jobs/{job_id}',token=doctor)
            require(state==200,f'{name}: status HTTP {state}: {body}')
            if body['status'] in ('done','failed'): break
            require(body['status'] in ('queued','processing'),f'{name}: unexpected status {body["status"]}')
            require(time.monotonic()<deadline,f'{name}: timed out (last state: {body["status"]})')
            time.sleep(.75)
        require(body['status']=='done', f'{name}: processing failed: {body["error"]}')
        result=body['result']
        require(result['is_critical'] is critical, f'{name}: incorrect critical status')
        require(result['modality']==modality,f'{name}: incorrect modality')
        require(bool(result['critical_reason']) is critical, f'{name}: critical reason mismatch')
        require(result['findings'] and result['impression'],f'{name}: extraction missing fields')
        require(request(root,f'/jobs/{job_id}',token=admin)[0]==200,f'{name}: admin cannot view')
        print(f'PASS {name}: {job_id} => done, critical={critical}')
    print('PASS: all five synthetic samples processed; auth and admin checks passed.')
    print('Next: verify second-radiologist isolation and critical alert logs manually.')

if __name__=='__main__':
    try: main()
    except (AssertionError, RuntimeError, urllib.error.URLError) as error:
        print(f'FAIL: {error}',file=sys.stderr)
        raise SystemExit(1)
