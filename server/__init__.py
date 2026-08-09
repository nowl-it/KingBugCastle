import sys
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
_BUILDERS = _HERE / "builders"
_CLI = _HERE / "cli"

for _path in (_HERE, _BUILDERS, _CLI):
    _sp = str(_path)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)
