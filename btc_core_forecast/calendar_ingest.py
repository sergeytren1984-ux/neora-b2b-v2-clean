"""Parse real calendar bytes with receipt vintage and explicit DST handling.

An observed schedule is not an observed release value or a consensus estimate.
Current calendar bytes are never substituted for a past available vintage.
"""
import datetime as dt,hashlib,json,pathlib
from zoneinfo import ZoneInfo

UTC=dt.timezone.utc

def parse(raw,receipt):
    if hashlib.sha256(raw).hexdigest()!=receipt['sha256']:raise ValueError('calendar digest mismatch')
    received=dt.datetime.fromisoformat(receipt['received_at_utc'])
    if received.tzinfo is None:raise ValueError('calendar receipt timezone required')
    text=raw.decode('utf-8').replace('\r\n','\n').replace('\n ','').replace('\n\t','')
    events=[]
    for block in text.split('BEGIN:VEVENT\n')[1:]:
        fields={}
        for line in block.split('END:VEVENT')[0].splitlines():
            if ':' in line:
                key,value=line.split(':',1);fields[key]=value
        start=[(k,v) for k,v in fields.items() if k.startswith('DTSTART')]
        if len(start)!=1 or not fields.get('UID') or not fields.get('SUMMARY'):raise ValueError('incomplete calendar event')
        key,value=start[0]
        if 'VALUE=DATE' in key:continue
        if value.endswith('Z'):at=dt.datetime.strptime(value,'%Y%m%dT%H%M%SZ').replace(tzinfo=UTC)
        else:
            tzid=key.split('TZID=',1)[-1] if 'TZID=' in key else None
            if tzid is None:raise ValueError('floating release time not accepted')
            zone='America/New_York' if tzid=='US-Eastern' else tzid
            at=dt.datetime.strptime(value,'%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo(zone)).astimezone(UTC)
        events.append({'event_id':fields['UID'],'title':fields['SUMMARY'],'release_utc':at.isoformat(),
            'release_МСК':at.astimezone(ZoneInfo('Europe/Moscow')).isoformat(),
            'schedule_received_utc':received.isoformat(),'source':receipt['source'],'vintage_sha256':receipt['sha256'],
            'schedule_known_before_release':received<at,'historical_vintage_before_receipt_proven':False,
            'consensus_value':None,'first_release_value':None,'surprise_value':None,
            'numeric_macro_surprise_available':False,'trading_authority':False})
    return sorted(events,key=lambda x:x['release_utc'])

if __name__=='__main__':
    root=pathlib.Path('inputs/macro_calendar');receipt=json.loads((root/'receipt.json').read_text());events=parse((root/'bls.ics').read_bytes(),receipt)
    output={'schema':'bls-received-calendar-v1','events':events,'macro_used_by_current_frozen_forecast':False,'full_system_ready':False}
    pathlib.Path('btc_core_forecast/runtime/bls_received_calendar.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print('REAL_CALENDAR_PARSED',len(events),'future available',sum(e['schedule_known_before_release'] for e in events),flush=True)
