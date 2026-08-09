import sys
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SERVER = _HERE.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))
