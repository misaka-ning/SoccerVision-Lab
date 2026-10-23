#!/usr/bin/env python3
"""Direct profiles of frozen legacy plans after the main collection finishes."""
import argparse
import json
from pathlib import Path
import time
from execute_robot import command,save


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();r=a.run
    while not (r/'collection_complete.json').exists():
        if (r/'failed_collection.json').exists() or (r/'failed_build.json').exists():
            raise RuntimeError('Earlier stage failed; legacy profiler not started')
        time.sleep(3)
    base=r/'profiles_legacy';base.mkdir()
    for repeat in range(1,4):
        for tag in ['E01_baseline','E02_c3k2']:
            d=base/('%s_r%d' % (tag,repeat));d.mkdir()
            command(r,['/usr/src/tensorrt/bin/trtexec','--loadEngine='+str(r/'legacy'/(tag+'.plan')),
                       '--streams=1','--warmUp=2000','--duration=10','--iterations=200','--noDataTransfers',
                       '--loadInputs=images:'+str(r/'inputs/representative_batch2.bin'),
                       '--separateProfileRun','--dumpProfile','--exportProfile='+str(d/'profile.json'),
                       '--dumpLayerInfo','--exportLayerInfo='+str(d/'layers.json')],d/'profile.log','D_legacy_'+tag+'_r'+str(repeat))
    save(r/'legacy_profiles_complete.json',dict(status='complete',repeats=3,source='exact frozen legacy plan bytes; no rebuild'))


if __name__=='__main__':main()
