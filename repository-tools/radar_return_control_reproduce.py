"""Fresh synthetic return-control repeat; no municipal input downloads needed."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'shock-radar/runs/N1_N2_return_control_20261007'
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    subprocess.run([sys.executable,str(ROOT/'shock-radar/src/return_regime_control.py'),'--frozen-r7',str(ROOT/'shock-radar/runs/R7_v2/manifest.json'),'--protocol',str(RUN/'protocol.json'),'--out',str(args.out)],check=True)
    subprocess.run([sys.executable,str(ROOT/'shock-radar/src/audit_return_regime_control.py'),'--frozen-r7',str(ROOT/'shock-radar/runs/R7_v2/manifest.json'),'--protocol',str(RUN/'protocol.json'),'--calculation',str(args.out),'--destination',str(args.out/'independent-audit.json')],check=True)
    expected=json.loads((RUN/'metrics.json').read_text())['summary'];actual=json.loads((args.out/'metrics.json').read_text())['summary']
    assert expected==actual,'Return control reference metrics differ'
    print('RETURN_CONTROL_REFERENCE_PASS:36 cells; scientific_pass remains false')
if __name__=='__main__':main()
