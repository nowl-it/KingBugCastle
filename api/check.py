import sys,json;
sys.path.insert(0,'api');
import config, requests
    
RANK='https://kgc-ranking-1.awesomepiece.com'

for p,q in [
    ('/ranking/colosseum-ranking',{'season':69,'useCache':'true'}),
    ('/ranking/colosseum-league-ranking',{'leagueSeason':11,'useCache':'true'}),
    ('/ranking/colosseum-hall-of-fame',{'leagueSeason':11,'useCache':'true'}),
]:
    try:
          r=requests.get(RANK+p,params=q,headers={**config.SESSION.headers,'time':config._time_header()},timeout=15)
          b=config.decode_response(r.content)
          print('%s -> %d | %s'%(p,r.status_code,str(b)[:400]))
    except Exception as e: print(p,'ERR',repr(e)[:80])
