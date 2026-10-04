from worker import first_passage

def row(low,high):return [0,'100',str(high),str(low),'100','1',3599999]
assert first_passage([row(90,100),row(80,100)],85,115)=='lower_first'
assert first_passage([row(90,120)],85,115)=='upper_first'
assert first_passage([row(80,120)],85,115)=='ambiguous'
assert first_passage([row(90,100)],85,115)=='neither'
print('fixed barrier selftest OK')
