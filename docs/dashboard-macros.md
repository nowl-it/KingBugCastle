# Admin Dashboard Macros

The Next.js Admin Dashboard (`http://localhost:8081/players`) supports "Macro Profiles". These are 1-click preset packages you can grant to players without needing to manually edit their state json.

Currently available macros:
- **Max Wealth**: Grants 99M Gold, 99M Cash, 99K Hearts, and 99K of all tokens (Arena, Clan, KingGod, Event, Babel, Raid).
- **Max All Inventory Items**: Grants 99K copies of every defined `InventoryItem` in the game.
- **Max All Heroes**: Unlocks every available hero in the player's card list, setting them to level 30 and 999 Souls.

## Modifying Macros
You can edit or add new macro logic in `server/dashboard.py` within the `api_player_macro` route (e.g. `POST /api/player/{pid}/macro`). 
To add new buttons to the UI, update `server/webui-next/src/app/players/page.tsx` and re-run `npm run build` in the `webui-next` directory to update the static assets.

## Realtime Charts
The dashboard also features real-time charts on the overview page (`/`). It polls the `GET /api/stats/realtime` endpoint every 2 seconds to plot the concurrent active users (CCU) and system stats. This endpoint computes active players by checking saves updated in the last 24 hours.
