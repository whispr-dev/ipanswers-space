#!/usr/bin/env python3
"""Download, verify and atomically activate monthly DB-IP Lite databases."""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request
import maxminddb


def validate(path: Path, kind: str):
    with maxminddb.open_database(str(path)) as reader:
        if kind not in reader.metadata().database_type.lower():
            raise ValueError('Unexpected database type')
        reader.get('8.8.8.8')
        reader.get('2606:4700:4700::1111')


def download(directory: Path, kind: str, month: str):
    destination = directory / f'dbip-{kind}-lite-{month}.mmdb'
    if destination.exists():
        try:
            validate(destination, kind)
            return destination.name
        except (ValueError, OSError, maxminddb.InvalidDatabaseError):
            pass  # Replace a corrupt copy only after its replacement validates.
    url = f'https://download.db-ip.com/free/dbip-{kind}-lite-{month}.mmdb.gz'
    fd, name = tempfile.mkstemp(prefix='.download-', dir=directory)
    os.close(fd)
    zipped = Path(name)
    unpacked = Path(name+'.mmdb')
    try:
        req = urllib.request.Request(url, headers={'User-Agent':'IPAnswers/1.0 (+https://ipanswers.space)'})
        with urllib.request.urlopen(req, timeout=60) as response, zipped.open('wb') as output:
            total = 0
            while chunk := response.read(1024*1024):
                total += len(chunk)
                if total > 300*1024*1024:
                    raise ValueError('Database download too large')
                output.write(chunk)
        with gzip.open(zipped, 'rb') as source, unpacked.open('wb') as output:
            total = 0
            while chunk := source.read(1024*1024):
                total += len(chunk)
                if total > 600*1024*1024:
                    raise ValueError('Unpacked database too large')
                output.write(chunk)
        validate(unpacked, kind)
        unpacked.chmod(0o644)
        os.replace(unpacked, destination)
        return destination.name
    finally:
        zipped.unlink(missing_ok=True)
        unpacked.unlink(missing_ok=True)


def update(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    today = dt.datetime.now(dt.timezone.utc).date().replace(day=1)
    for date in (today, today-dt.timedelta(days=1)):
        month = date.strftime('%Y-%m')
        try:
            files = {kind:download(directory, kind, month) for kind in ('city', 'asn')}
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        files['release'] = month
        fd, tmp = tempfile.mkstemp(prefix='.manifest-', dir=directory)
        try:
            with os.fdopen(fd, 'w') as out:
                json.dump(files, out)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(tmp, 0o644)
            os.replace(tmp, directory/'current.json')
        finally:
            Path(tmp).unlink(missing_ok=True)
        # Keep this and the preceding release; mapped old readers remain valid on Linux.
        for kind in ('city', 'asn'):
            existing = sorted(directory.glob(f'dbip-{kind}-lite-????-??.mmdb'), reverse=True)
            for old in existing[2:]:
                if old.name != files[kind]:
                    old.unlink()
        print(f'DB-IP Lite {month} verified and active', flush=True)
        return
    raise RuntimeError('Neither current nor previous month is available; existing databases preserved')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    # The systemd service serializes updates. Initial installation runs before enabling it.
    update(args.data_dir.resolve())
