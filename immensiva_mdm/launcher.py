"""Local Windows operator launcher. Stops only its recorded server process."""
from pathlib import Path
import argparse,json,os,subprocess,sys,time,urllib.request,webbrowser
import psutil

ROOT=Path(__file__).resolve().parent.parent
def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=1) as response:
            return json.load(response).get('product')=='IMMENSIVA MDM'
    except Exception:return False

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--stop',action='store_true')
    parser.add_argument('--port',type=int,default=7070)
    parser.add_argument('--data-dir',default=str(ROOT/'MDM'))
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    logs=ROOT/'logs';logs.mkdir(exist_ok=True)
    record=logs/f'server-{args.port}.json'
    if args.stop:
        if record.exists():
            data=json.loads(record.read_text())
            try:
                process=psutil.Process(data['pid'])
                if abs(process.create_time()-data['created'])<.01 and 'immensiva_mdm.server' in process.cmdline():
                    process.terminate();process.wait(timeout=8)
            except psutil.NoSuchProcess:pass
        return
    if not health(args.port):
        python=ROOT/'runtime/python.exe'
        if not python.exists():python=Path(sys.executable)
        environment=dict(os.environ,PYTHONPATH=str(ROOT),PYTHONUTF8='1')
        with (logs/'server.log').open('ab') as output:
            process=subprocess.Popen([str(python),'-m','immensiva_mdm.server','--port',str(args.port),'--data-dir',args.data_dir],cwd=ROOT,env=environment,stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        record.write_text(json.dumps({'pid':process.pid,'created':psutil.Process(process.pid).create_time()}))
        deadline=time.monotonic()+20
        while not health(args.port):
            if process.poll() is not None:raise RuntimeError('Server exited. See logs/server.log; check whether another MDM server owns discovery or this port.')
            if time.monotonic()>deadline:raise RuntimeError('Startup timed out. See logs/server.log.')
            time.sleep(.25)
    if not args.no_browser:webbrowser.open(f'http://127.0.0.1:{args.port}/')

if __name__=='__main__':
    try:main()
    except Exception as error:
        if os.name=='nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,str(error),'IMMENSIVA MDM',0x10)
        raise
