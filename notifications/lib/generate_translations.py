import json
import time
from deep_translator import GoogleTranslator

LANGUAGES = ['en', 'zh', 'ja', 'vi', 'th', 'de', 'es', 'fr', 'pt', 'it', 'ru', 'ar', 'id', 'pl', 'tr']

def translate(text, target):
    if target == 'en': return text
    if target == 'zh': target = 'zh-CN'
    for _ in range(3):
        try:
            return GoogleTranslator(source='en', target=target).translate(text)
        except:
            time.sleep(1)
    return text

base_texts = {
    "APP_TITLE": "{icon} KGC {platform} · v{version}",
    "APP_BODY": "**New {platform} version available**\n\n{icon} **v{version}**{previous}\n\n[Open Store ↗]({store_url})",
    "APP_PREV": "\n📅 Previous: v{last_version}",
    "PATCH_TITLE": "📦 KGC Patch · {latest_fmt}",
    "PATCH_BODY": "**New CDN patch is live**\n\n🆕 **{latest_fmt}**{previous}{days_diff}\n\n[Open CDN folder ↗]({patch_url})",
    "PATCH_PREV": "\n📅 Previous: {last_fmt}",
    "PATCH_DAYS": "\n⏱️ {days_diff} day(s) since last patch",
    "NOTICE_TITLE": "📢 KGC Notice · {notice_title}",
    "NOTICE_BODY": "**{notice_title}**\n\n{excerpt}\n\n[Read full notice ↗]({notice_url})"
}

result = {}

for lang in LANGUAGES:
    print(f"Translating {lang}...")
    lang_dict = {}
    for k, v in base_texts.items():
        if '{' in v:
            # We must be careful not to translate the placeholders.
            # But deep-translator sometimes messes up {}.
            # Let's replace placeholders with easily identifiable strings like __VAR__
            import re
            placeholders = re.findall(r'\{[a-z_]+\}', v)
            temp = v
            for i, p in enumerate(placeholders):
                temp = temp.replace(p, f' X{i}X ')
            
            translated = translate(temp, lang)
            for i, p in enumerate(placeholders):
                translated = translated.replace(f' X{i}X ', p).replace(f'X{i}X', p).replace(f' X{i} X', p)
            
            # Google Translate sometimes adds spaces inside **bold** markers
            translated = translated.replace("** ", "**").replace(" **", "**")
            lang_dict[k] = translated
        else:
            translated = translate(v, lang)
            translated = translated.replace("** ", "**").replace(" **", "**")
            lang_dict[k] = translated
    result[lang] = lang_dict

with open('/home/nowl/Code/kgc/notifications/lib/translations.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, indent=4, ensure_ascii=False)

print("Done")
