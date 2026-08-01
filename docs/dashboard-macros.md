# Admin Dashboard Macros & Tier Strategy

The Next.js Admin Dashboard (`http://localhost:8081/players`) supports "Macro Profiles" (1-click preset packages) and implements a **Freemium Private Server** structure to balance game testing and monetization.

## 1. Tier 1: Free "Starter" (Test Game)
By default, **every new account** created on the server automatically receives a Tier 1 Starter package. This gives new players a balanced start to test the game without ruining the progression loop.
- **Max Resources:** Grants `290909` Gold, Cash, Heart, sets Level to 100, and Exp to 9999999.
- **Basic Heroes:** All released heroes are unlocked at **Level 20**.
- **Basic Legacies:** All released artifacts are unlocked at **0-star** (`count=1`).

## 2. Tier 2: Premium "Supporter/VIP" (Monetization)
For players who donate or purchase VIP packages, Server Admins can grant maximum-level items directly from the Admin Dashboard using Macro buttons.
- **max_resources:** (Available as a manual macro if needed)
- **hero_basic / hero_advanced / hero_max:** 
  - `hero_max` grants all heroes at Level 30, **including unreleased ones (e.g. D.Cathy)**.
- **legacy_basic / legacy_advanced / legacy_max:**
  - `legacy_max` grants all artifacts at 10-star (`count=99999`), **including unreleased artifacts**.
- **accessory_admin:** Grants best-in-slot Admin tier accessories.

## Modifying Macros
You can edit or add new macro logic in `server/dashboard.py` within the `api_player_macro` route (e.g. `POST /api/player/{pid}/macro`). 
To add new buttons to the UI, update `server/webui-next/src/app/players/page.tsx` and re-run `npm run build` in the `server/webui-next` directory to update the static assets.

## Realtime Charts
The dashboard also features real-time charts on the overview page (`/`). It polls the `GET /api/stats/realtime` endpoint every 2 seconds to plot the concurrent active users (CCU) and system stats. This endpoint computes active players by checking saves updated in the last 24 hours.
