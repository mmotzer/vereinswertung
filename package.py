"""Create secret-free NAS delivery archives from the explicit source allowlist."""
import tarfile
import zipfile

from app import ROOT, public_source_files


def main():
    folder=ROOT/'artifacts'
    folder.mkdir(exist_ok=True)
    files = public_source_files()
    with zipfile.ZipFile(folder/'vereinswertung-nas.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for p in files:archive.write(p,p.relative_to(ROOT))
    with tarfile.open(folder/'vereinswertung-build.tar.gz','w:gz') as archive:
        for p in files:archive.add(p,arcname=str(p.relative_to(ROOT)))
    print(f'{len(files)} Quelldateien verpackt; keine Datenbank und keine Zugangsschlüssel.')
    print(folder/'vereinswertung-nas.zip')
    print(folder/'vereinswertung-build.tar.gz')


if __name__=='__main__':
    main()
