import json
from server import r_player, load_state
print(json.dumps(r_player({}, load_state())["keyValues"], indent=2))
