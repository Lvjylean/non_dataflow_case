"""Exercise the real controller with a rejecting native-process stand-in."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class Retry(unittest.TestCase):
    @unittest.skipUnless(Path('/proc/meminfo').exists(), 'Controller admission uses Linux /proc')
    def test_two_rejections_stop_without_route_or_reusing_failed_checkpoint(self):
        code=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as td:
            t=Path(td);inp=t/'post_opt.dcp';inp.write_bytes(b'clean-fixture')
            fp=t/'floorplan';fp.mkdir();val=t/'validation.json';val.write_text('{"status":"PASS"}')
            fake=t/'vivado';fake.write_text('#!'+sys.executable+'\n'+r'''
from pathlib import Path
import json,sys
args=sys.argv;tail=args[args.index('-tclargs')+1:]
if args[args.index('-source')+1].endswith('/chain.tcl'):
    root=Path(tail[2]);out=root/'generic/implementation'
    (root/'base').mkdir();(root/'base/pre_route.dcp').write_bytes(b'unchanged-placed-fixture')
else:
    out=Path(tail[1]);root=out.parents[1]
    assert Path(tail[0]).read_bytes()==b'unchanged-placed-fixture'
    assert (root/'generic/rejected_attempt0/joint_placed/reject_ids.json').is_file()
(out/'joint_placed').mkdir(parents=True)
(out/'joint_placed/reject_ids.json').write_text('["candidate@SLR0"]')
with (root/'fake_calls.txt').open('a') as f:f.write(args[args.index('-source')+1]+'\n')
sys.exit(77)
''');fake.chmod(0o755)
            root=t/'run'
            p=subprocess.run([sys.executable,str(code/'run_case.py'),'--input',str(inp),
                '--expected-sha256',hashlib.sha256(inp.read_bytes()).hexdigest(),'--floorplan',str(fp),
                '--period','6.7','--work-root',str(root),'--validation-json',str(val),
                '--vivado',str(fake),'--memory-required-gib','0','--fixture'],capture_output=True,text=True)
            state=json.loads((root/'status.json').read_text())
            self.assertEqual(state['status'],'STOPPED_WITH_EVIDENCE')
            self.assertIn('Bounded joint timing retry',state['error'])
            self.assertEqual(len((root/'fake_calls.txt').read_text().splitlines()),2)
            self.assertEqual([s['returncode'] for s in state['stages']],[77,77])
            self.assertFalse(list(root.rglob('post_route.dcp')))
            self.assertEqual(inp.read_bytes(),b'clean-fixture')


if __name__=='__main__':unittest.main()
