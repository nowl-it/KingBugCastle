# Hero Detail prototype

Standalone visual baseline for the v172.0.01 Hero detail screen. Run from this folder:

```sh
python3 -m http.server 8090
```

The screen image is captured from the currently running client, so its visual geometry and all
game-rendered assets are exact. The hotzones map to the actual `CardInfoPanel` handlers:

- tabs: Hero, Growth, Profile, Skin;
- Hero tab: title, illustration, role, traits, skills, equipment and treasure;
- `OnClickToggleDotIllust`, `OnClickUnitStatistics`, `OnClickSkillButton`, and `OnClickTab(0..3)`.

`assets/farael-illustration.png` and `assets/ui/` are exported directly from the client bundles;
the next implementation pass will replace the visual baseline with independently rendered, source-mapped controls.
