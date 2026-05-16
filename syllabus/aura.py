import json
import os
import re
import urllib.request
import urllib.parse
from datetime import date

from pathlib import Path

# キャッシュファイルはリポジトリルートに置く
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CTX_FILE = PROJECT_ROOT / ".syllabus_ctx.json"

AURA_ENDPOINT = (
    "https://syllabus.ritsumei.ac.jp/syllabus/s/sfsites/aura"
    "?r=1&aura.ApexAction.execute=1"
)


def academic_year() -> str:
    today = date.today()
    return str(today.year if today.month >= 4 else today.year - 1)


def load_ctx() -> dict | None:
    try:
        with open(CTX_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def save_ctx(ctx: dict):
    with open(CTX_FILE, "w") as f:
        json.dump(ctx, f, indent=2)


def call_api(course_code: str, year: str, ctx: dict) -> tuple[str | None, bool]:
    """
    Returns (syllabus_url | None, ctx_error: bool)
    ctx_error=True のとき fwuid が古い可能性がある
    """
    aura_ctx = {
        "mode": "PROD",
        "fwuid": ctx["fwuid"],
        "app": "siteforce:communityApp",
        "loaded": {
            "APPLICATION@markup://siteforce:communityApp": ctx["loaded"]
        },
        "dn": [], "globals": {}, "uad": True,
    }
    message = {
        "actions": [{
            "id": "1;a",
            "descriptor": "aura://ApexActionController/ACTION$execute",
            "callingDescriptor": "UNKNOWN",
            "params": {
                "namespace": "",
                "classname": "R_SyllabusPublicPageController",
                "method":    "getSyllabusRecords",
                "params": {
                    "action": {
                        "lang": "ja", "keyword": course_code,
                        "faculty": None, "year": year,
                        "term": None, "week": [], "period": [],
                        "professionalCareer": None, "limits": 5,
                    }
                },
                "cacheable": False, "isContinuation": False,
            }
        }]
    }
    body = urllib.parse.urlencode({
        "message": json.dumps(message, separators=(',', ':')),
        "aura.context": json.dumps(aura_ctx, separators=(',', ':')),
        "aura.pageURI": "/syllabus/s/?language=ja",
        "aura.token": "null",
    }).encode()

    req = urllib.request.Request(
        AURA_ENDPOINT, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  [通信エラー] {e}")
        return None, False

    if "event" in data and "descriptor" in data.get("event", {}):
        return None, True

    action = (data.get("actions") or [{}])[0]
    if action.get("state") != "SUCCESS":
        errs = action.get("error", [])
        msgs = [e.get("message", "") for e in errs]
        ctx_err = any(
            kw in m for m in msgs
            for kw in ("INVALID", "RELOAD", "REFRESH", "OUT_OF_DATE", "framework")
        )
        if ctx_err or not errs:
            return None, True
        print(f"  [API エラー] {msgs}")
        return None, False

    results = (
        (action.get("returnValue") or {})
        .get("returnValue", {})
        .get("result")
        or []
    )
    if not results:
        return None, False

    sf_id = results[0]["Id"]
    url = (
        f"https://syllabus.ritsumei.ac.jp/syllabus/s/r-syllabus"
        f"/{sf_id}/{course_code}?language=ja"
    )
    return url, False


def fetch_fresh_ctx() -> dict | None:
    print("  → ブラウザを起動して Aura コンテキストを自動取得中...")
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
    except Exception:
        print("  [ERROR] selenium が見つかりません。pip install selenium を実行してください。")
        return None

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])

    try:
        driver = webdriver.Chrome(options=opts)
    except Exception as e:
        print(f"  [ERROR] Chrome 起動失敗: {e}")
        return None

    try:
        driver.get("https://syllabus.ritsumei.ac.jp/syllabus/s/?language=ja")

        WebDriverWait(driver, 20).until(lambda d: d.execute_script(
            "return performance.getEntriesByType('resource')"
            ".some(r => r.name.includes('bootstrap.js'))"
        ))

        bootstrap_url = driver.execute_script("""
            return performance.getEntriesByType('resource')
                .map(r => r.name)
                .find(n => n.includes('/l/') && n.includes('bootstrap.js'));
        """)

        if not bootstrap_url:
            print("  [ERROR] bootstrap.js URL が見つかりません。")
            return None

        m = re.search(r"/l/([^/]+)/bootstrap\.js", bootstrap_url)
        if not m:
            print("  [ERROR] bootstrap URL の解析失敗。")
            return None

        ctx_json = json.loads(urllib.parse.unquote(m.group(1)))
        fwuid = ctx_json.get("fwuid")
        loaded = ctx_json.get("loaded", {}).get(
            "APPLICATION@markup://siteforce:communityApp"
        )

        if not fwuid or not loaded:
            print(f"  [ERROR] 取得失敗 fwuid={fwuid}, loaded={loaded}")
            return None

        print(f"  → 取得成功 (fwuid: {fwuid[:20]}...)")
        return {"fwuid": fwuid, "loaded": loaded}

    finally:
        driver.quit()
