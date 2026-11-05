"""Bundle a supplied, approved Python runtime; no downloads or live venue data."""
from pathlib import Path
import argparse,shutil

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runtime',required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parent.parent
    source=Path(args.runtime).resolve()
    if not (source/'python.exe').is_file():raise ValueError('A Windows Python runtime containing python.exe is required')
    target=root/'dist/IMMENSIVA-MDM-Windows'
    if target.exists():raise ValueError('Output already exists; archive it before building again')
    target.mkdir(parents=True)
    shutil.copytree(source,target/'runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (target/'runtime/python311._pth').write_text('python311.zip\n.\nLib\nDLLs\nLib/site-packages\n..\nimport site\n')
    shutil.copytree(root/'immensiva_mdm',target/'immensiva_mdm',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(root/'docs',target/'docs')
    for filename in ['Start IMMENSIVA MDM.cmd','Stop IMMENSIVA MDM.cmd','README.md','LICENSE','NOTICE','BRAND_ASSETS.md']:
        shutil.copy2(root/filename,target/filename)
    shutil.make_archive(str(target),'zip',target.parent,target.name)
    print(target.with_suffix('.zip'))

if __name__=='__main__':main()
