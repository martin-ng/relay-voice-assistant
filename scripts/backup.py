"""Consistent online backup; refuses to overwrite an existing backup."""
import argparse
import sqlite3
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('destination',type=Path)
parser.add_argument('--database',type=Path,default=Path('data/relay.db'))
args=parser.parse_args()
if args.destination.exists():
    parser.error('Destination already exists; choose a new file.')
if not args.database.is_file():
    parser.error('Source database does not exist.')
args.destination.parent.mkdir(parents=True,exist_ok=True)
source=sqlite3.connect(f'{args.database.resolve().as_uri()}?mode=ro',uri=True)
target=sqlite3.connect(args.destination)
try:
    source.backup(target)
finally:
    target.close()
    source.close()
print(f'Backup written to {args.destination}')
