#!/usr/bin/env python3
import json
import sys
import os
import subprocess
import urllib.request
import urllib.error
import time

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
TRANSLATIONS_FILE = os.path.join(SCRIPT_DIR, 'translations.json')

def load_config():
    # Evaluate config.sh to get environment variables
    config_script = os.path.join(PROJECT_DIR, 'config.sh')
    cmd = f"source {config_script} && env"
    output = subprocess.check_output(cmd, shell=True, executable="/bin/bash").decode('utf-8')
    config = {}
    for line in output.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            config[k] = v
    return config

def load_translations():
    with open(TRANSLATIONS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def send_ntfy(server, topic, token, title, body, tags, click):
    url = f"{server}/{topic}"
    cmd = [
        "curl", "-sf",
        "-H", "Markdown: yes",
        "-H", f"Title: {title}",
        "-H", f"Tags: {tags}",
        "-H", "Priority: default"
    ]
    if token:
        cmd.extend(["-H", f"Authorization: Bearer {token}"])
    if click:
        cmd.extend(["-H", f"Click: {click}"])
    
    cmd.extend(["--data-binary", body, url])
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"Failed to send to {topic} (curl exited with {e.returncode})", file=sys.stderr)

def main():
    if len(sys.argv) < 5:
        print("Usage: template_sender.py <category> <template_prefix> <tags> <click_url> [key=value ...]", file=sys.stderr)
        sys.exit(1)

    category = sys.argv[1]
    template_prefix = sys.argv[2]
    tags = sys.argv[3]
    click_url = sys.argv[4]
    
    args_dict = {}
    for arg in sys.argv[5:]:
        if '=' in arg:
            k, v = arg.split('=', 1)
            args_dict[k] = v

    config = load_config()
    server = config.get("NTFY_SERVER", "https://ntfy.sh")
    prefix = config.get("TOPIC_PREFIX", "nowl")
    token = config.get("NTFY_TOKEN", "")
    
    # parse LANGUAGES from config
    # format: LANGUAGES=(en zh ja vi th de es fr pt it ru ar id pl tr)
    # the env output doesn't cleanly export bash arrays, so we read it directly
    langs = ["en", "zh", "ja", "vi", "th", "de", "es", "fr", "pt", "it", "ru", "ar", "id", "pl", "tr"]

    translations = load_translations()
    test_mode = os.environ.get("TEST_MODE") == "true"

    for lang in langs:
        if test_mode:
            topic = "nowl-test"
        else:
            topic = f"{prefix}-{lang}-{category}"
            
        t = translations.get(lang, translations.get("en"))
        
        # Render title
        title_template = t.get(f"{template_prefix}_TITLE", "")
        body_template = t.get(f"{template_prefix}_BODY", "")
        
        title = title_template.format(**args_dict)
        
        # Determine optional prev/days block
        previous_block = ""
        days_block = ""
        if args_dict.get("last_version") or args_dict.get("last_fmt"):
            prev_tmpl = t.get(f"{template_prefix}_PREV", "")
            if prev_tmpl:
                previous_block = prev_tmpl.format(**args_dict)
        if args_dict.get("days_diff"):
            days_tmpl = t.get(f"{template_prefix}_DAYS", "")
            if days_tmpl:
                days_block = days_tmpl.format(**args_dict)
        
        args_dict["previous"] = previous_block
        args_dict["days_diff"] = days_block
        
        body = body_template.format(**args_dict)
        
        send_ntfy(server, topic, token, title, body, tags, click_url)
        time.sleep(2)

if __name__ == "__main__":
    main()
