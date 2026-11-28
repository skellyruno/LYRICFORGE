import copy
from studio_voice_alignment import align

def test_original_script_exact_reconciliation_and_fail_closed():
    r={'duration':3.,'lines':[{'text':'DSP works.','start':0.,'end':2.,'words':[{'text':'DSP','start':0.,'end':1.},{'text':'works.','start':1.,'end':2.}]}]};old=copy.deepcopy(r)
    recognized=[{'words':[{'text':'D','start':.1,'end':.2},{'text':'S','start':.2,'end':.4},{'text':'P','start':.4,'end':.6},{'text':'works','start':.9,'end':1.4}]}]
    x=align(r,recognized);assert r==old and x['alignment']['status']=='matched';assert x['lines'][0]['text']=='DSP works.' and x['lines'][0]['words'][0]['end']==.6
    recognized[0]['words'][-1]['text']='wrong';assert align(r,recognized) is None
    recognized[0]['words'][-1]['text']='works';recognized[0]['words'][-1]['probability']=.1;assert align(r,recognized) is None
