"""Create secret-free NAS delivery archives from the explicit source allowlist."""
import tarfile
import zipfile

from app import ROOT, SOURCE_FILES


def main():
    folder=ROOT/'artifacts'
    folder.mkdir(exist_ok=True)
    files=[ROOT/name for name in SOURCE_FILES if (ROOT/name).is_file()]
    for name in ('static','reference','tests','docs'):
        files.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    with zipfile.ZipFile(folder/'vereinswertung-nas.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in files:archive.write(p,p.relative_to(ROOT))
    with tarfile.open(folder/'vereinswertung-build.tar.gz','w:gz') as archive:
        for p in files:archive.add(p,arcname=str(p.relative_to(ROOT)))
    print(f'{len(files)} Quelldateien verpackt; keine Datenbank und keine Zugangsschlüssel.')
    print(folder/'vereinswertung-nas.zip')
    print(folder/'vereinswertung-build.tar.gz')


if __name__=='__main__':
    main()
