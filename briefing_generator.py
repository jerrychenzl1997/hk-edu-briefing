import os
import re
import json
import time
import asyncio
import datetime
import requests
import pytz
import markdown
import edge_tts
from google import genai

HKT = pytz.timezone('Asia/Hong_Kong')
NOW_HKT = datetime.datetime.now(HKT)
TODAY_STR = NOW_HKT.strftime("%Y年%m月%d日")
UPDATE_TIME_STR = NOW_HKT.strftime("%H:%M")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in os.environ.get(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3.5-flash-lite,gemini-3.8-flash-lite,gemini-3.8-pro"
    ).split(",") if m.strip()
]
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "").strip()


def get_pages_url():
    if "/" in GITHUB_REPOSITORY:
        owner, repo = GITHUB_REPOSITORY.split("/", 1)
        return f"https://{owner.lower()}.github.io/{repo}/"
    return ""


def load_json_safe(filepath, default_val):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default_val


def generate_briefing_with_gemini(news_list, history_events):
    if not GEMINI_API_KEY:
        raise ValueError("缺少環境變量 GEMINI_API_KEY")

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
你是一位資深的香港教育政策分析師與新聞總編輯。請根據以下過去 24 小時採集到的香港教育新聞、連登社區討論以及 Facebook 核心教育專頁貼文，為用戶撰寫一份精煉、專業、易於在手機閱讀與語音播報的《香港教育新聞早報》（日期：{TODAY_STR}）。

【昨日/近期持續追蹤事件參考】：
{json.dumps(history_events, ensure_ascii=False, indent=2)}

【今日採集原始數據（共 {len(news_list)} 條）】：
{json.dumps(news_list, ensure_ascii=False, indent=2)}

【編審與排版鐵律】：
1. **高度去重與合併**：多間傳媒報導同一件事時，必須合併為一條，並在括號內註明所有報導媒體名稱（如：`[明報、HK01、RTHK]`）。
2. **連續報導事件自動標記規則**：
   - 對比【昨日/近期持續追蹤事件參考】與今日新聞：
   - 若某事件已**連續 2 天出現，且今日有 ≥3 篇報導**，請在該條新聞標題前加上 **`【跟進】`** 標籤。
   - 若某事件已**連續 3 天或以上持續報導**，請在該條新聞標題前加上 **`【重大事件持續追蹤】`** 標籤，並深度梳理事件演變脈絡。
3. **結構清晰（使用 Markdown 格式，默認繁體中文）**：
   - **📌 今日教育頭條（2-3條）**：最重磅的政策變動（教育局、考評局、DSE、八大動態、殺校縮班、愛國主義教育、鄧飛議員動態等），每條給出「核心事實 + 影響解讀」。
   - **📱 社交平台核心信源與深度輿情（FB / 連登 LIHKG）**：
     * 總結「教育刺針」、「蔡若蓮局長」、「鄧飛議員」等 Facebook 核心專頁的最新發聲與互動熱度（讚好/留言數）。
     * 若今日觸發了「重大事件社交輿情深挖」，請重點剖析網民、家長與前線教師的真實情緒傾向與爭議焦點。
     * 歸納連登校園台/吹水台的熱門教育話題。
   - **🏫 基礎教育與學界動態**：中小學、幼稚園、家校、學童身心健康等新聞。
   - **🎓 高等教育與大專資訊**：八大院校、自資院校、科研、留學香港等動態。
4. **保留原文連結**：每條新聞末尾請附上 `[原文](連結)` 方便點擊查閱。
5. **語言風格**：使用流暢、道地的香港書面繁體中文，語氣客觀專業，總字數控制在 1600～2400 字之間。
6. **嚴禁編造**：僅基於提供的數據進行歸納，若某個板塊今日無相關數據，可簡短註明「今日暫無重大新增動態」。
7. **地域限定**：純外國教育新聞（如韓國、日本、台灣、歐美等地院校動態、外國高考政策，且與香港無直接關聯）一律不收，不納入簡報。

【系統內部追蹤數據輸出要求（極重要）】：
在整份 Markdown 簡報的最末尾，請務必附上一段標準 JSON 代碼塊（用 ```json 和 ``` 包裹），提取今日最值得跨日追蹤的 2～4 個核心事件關鍵詞（每個詞組 2～6 個字），供明日爬蟲系統自動判斷是否觸發深度輿情追蹤。格式嚴格如下：
```json
{{
  "hot_keywords": ["關鍵詞1", "關鍵詞2"]
}}
```

"""

    response = None
    last_error = None

    # Build candidate model list: primary -> curated fallbacks -> auto-discovered text models
    candidates = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
    exclude_markers = ("image", "embedding", "tts", "audio", "live", "veo", "imagen", "gemma", "thinking", "banana")
    try:
        discovered = []
        for m in client.models.list():
            name = (getattr(m, "name", "") or "").split("/")[-1]
            actions = str(getattr(m, "supported_actions", "") or "").lower()
            low = name.lower()
            if not name or name in candidates:
                continue
            if any(b in low for b in exclude_markers):
                continue
            if "generatecontent" in actions and ("flash" in low or "pro" in low):
                discovered.append(name)
        candidates.extend(discovered)
    except Exception as ex:
        print(f"[WARN] Gemini model discovery failed: {ex}")

    candidates = candidates[:8]
    print(f"[INFO] Gemini candidate models: {candidates}")

    for model_name in candidates:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                print(f"[INFO] Gemini generation succeeded with model: {model_name}")
                break
            except Exception as ex:
                last_error = ex
                err_str = str(ex)
                code_match = re.search(r'(?:ClientError|ServerError): (\d{3})', err_str)
                code = code_match.group(1) if code_match else ""
                # 404 (model unavailable) / 429 (quota exhausted) -> skip to next model immediately
                if code in ("404", "429"):
                    print(f"[WARN] Model {model_name} unusable ({code}); skipping to next candidate.")
                    break
                wait_sec = 90 * (attempt + 1)
                print(f"[WARN] Model {model_name} attempt {attempt + 1} failed: {err_str[:300]}. Retrying in {wait_sec}s...")
                if attempt < 2:
                    time.sleep(wait_sec)
        if response is not None:
            break

    if response is None:
        raise last_error
    full_text = response.text

    hot_keywords = []
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', full_text, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            hot_keywords = parsed.get("hot_keywords", [])
        except Exception:
            pass
        clean_briefing = full_text[:json_match.start()].strip()
    else:
        clean_briefing = full_text.strip()

    return clean_briefing, hot_keywords


def clean_markdown_for_tts(md_text):
    text = f"各位早上好，現在為您播報 {TODAY_STR} 的香港教育新聞早報。\n\n" + md_text
    text = re.sub(r'\[原文\]\(https?://[^)]+\)', '', text)
    text = re.sub(r'\[([^]]+)\]\(https?://[^)]+\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[📌📱🏫🎓📰*#>`\-_]', ' ', text)
    text = re.sub(r'\[([^]]+)\]', r'，據\1報導，', text)
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text += "\n\n以上是今日香港教育新聞早報的全部內容，感謝您的收聽，祝您有愉快的一天。"
    return text.strip()


async def generate_tts_audio_async(speech_text, output_mp3="latest_briefing.mp3"):
    communicate = edge_tts.Communicate(speech_text, voice="zh-CN-XiaoxiaoNeural", rate="+5%")
    await communicate.save(output_mp3)


def build_mobile_html(briefing_md, total_items_count):
    body_html = markdown.markdown(
        briefing_md,
        extensions=['extra', 'nl2br', 'sane_lists']
    )
    body_html = body_html.replace('<a href="', '<a target="_blank" rel="noopener noreferrer" href="')

    html_template = f"""<!DOCTYPE html>

<html lang="zh-Hant">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0" />
  <title>香港教育新聞早報 · {TODAY_STR}</title>
  <style>
    :root {{
      --bg-color: #f6f7f9;
      --card-bg: #ffffff;
      --text-primary: #1a1d20;
      --text-secondary: #5a626a;
      --accent-color: #0f62fe;
      --accent-soft: #e8f0fe;
      --border-color: #e5e8eb;
      --base-font-size: 17px;
    }}
    [data-theme="dark"] {{
      --bg-color: #121417;
      --card-bg: #1c1f24;
      --text-primary: #e8eaed;
      --text-secondary: #9aa0a6;
      --accent-color: #6ea8fe;
      --accent-soft: #1e2a3a;
      --border-color: #2d3239;
    }}
    * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
    body {{
      margin: 0; padding: 0;
      background-color: var(--bg-color);
      color: var(--text-primary);
      font-family: -apple-system, BlinkMacSystemFont, "PingFang HK", "PingFang TC", "Microsoft JhengHei", sans-serif;
      font-size: var(--base-font-size);
      line-height: 1.75;
      transition: background-color 0.25s ease, color 0.25s ease;
    }}
    .top-toolbar {{
      position: sticky; top: 0; z-index: 100;
      background-color: var(--card-bg);
      border-bottom: 1px solid var(--border-color);
      padding: 10px 14px;
      display: flex; justify-content: space-between; align-items: center; gap: 8px;
    }}
    .toolbar-group {{ display: flex; align-items: center; gap: 6px; }}
    .btn-ctrl {{
      background: var(--bg-color); color: var(--text-primary);
      border: 1px solid var(--border-color); border-radius: 8px;
      padding: 6px 11px; font-size: 14px; font-weight: 600; cursor: pointer;
    }}
    .container {{ max-width: 720px; margin: 0 auto; padding: 16px 14px 48px; }}
    .header-card, .audio-card, .content-card {{
      background: var(--card-bg); border-radius: 16px; padding: 18px;
      margin-bottom: 14px; border: 1px solid var(--border-color);
    }}
    .header-title {{ margin: 0 0 6px 0; font-size: 1.45em; font-weight: 800; line-height: 1.3; }}
    .header-meta {{ font-size: 0.82em; color: var(--text-secondary); display: flex; flex-wrap: wrap; gap: 10px; }}
    .audio-label {{ font-size: 0.85em; font-weight: 700; color: var(--accent-color); display: flex; justify-content: space-between; margin-bottom: 8px; }}
    audio {{ width: 100%; height: 40px; border-radius: 8px; }}
    .content-card h1, .content-card h2, .content-card h3 {{
      margin-top: 1.4em; margin-bottom: 0.6em; line-height: 1.4;
      border-bottom: 1px solid var(--border-color); padding-bottom: 6px;
    }}
    .content-card h2:first-child, .content-card h3:first-child {{ margin-top: 0; }}
    .content-card ul, .content-card ol {{ padding-left: 1.25em; }}
    .content-card li {{ margin-bottom: 0.85em; }}
    .content-card a {{
      color: var(--accent-color); text-decoration: none; font-weight: 600;
      padding: 1px 6px; background: var(--accent-soft); border-radius: 6px; font-size: 0.88em;
    }}
    .footer {{ text-align: center; font-size: 0.8em; color: var(--text-secondary); margin-top: 24px; }}
  </style>
</head>
<body>
  <div class="top-toolbar">
    <div class="toolbar-group">
      <button class="btn-ctrl" onclick="changeFontSize(-2)">A-</button>
      <button class="btn-ctrl" onclick="resetFontSize()">標準</button>
      <button class="btn-ctrl" onclick="changeFontSize(2)">A+</button>
    </div>
    <div class="toolbar-group">
      <button class="btn-ctrl" id="themeToggle" onclick="toggleTheme()">🌙 深色</button>
    </div>
  </div>
  <div class="container">
    <div class="header-card">
      <h1 class="header-title">📰 香港教育新聞早報</h1>
      <div class="header-meta">
        📅 {TODAY_STR}
        ⏰ {UPDATE_TIME_STR} 更新
        📊 篩選自 {total_items_count} 條原始資訊
      </div>
    </div>
    <div class="audio-card">
      <div class="audio-label">
        🎧 普通話語音早報（微軟 AI 播報）
        曉曉女聲
      </div>
      <audio controls preload="none">
        <source src="latest_briefing.mp3?t={int(NOW_HKT.timestamp())}" type="audio/mpeg">
      </audio>
    </div>
    <main class="content-card">{body_html}</main>
    <div class="footer">全自動雲端生成 · 數據每日歸檔並滾動保留 30 天</div>
  </div>
  <script>
    let currentSize = parseInt(localStorage.getItem('edu_briefing_font_size')) || 17;
    function applyFontSize(size) {{
      currentSize = Math.min(26, Math.max(13, size));
      document.documentElement.style.setProperty('--base-font-size', currentSize + 'px');
      localStorage.setItem('edu_briefing_font_size', currentSize);
    }}
    function changeFontSize(delta) {{ applyFontSize(currentSize + delta); }}
    function resetFontSize() {{ applyFontSize(17); }}
    applyFontSize(currentSize);

    const themeBtn = document.getElementById('themeToggle');
    function applyTheme(theme) {{
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('edu_briefing_theme', theme);
      themeBtn.textContent = theme === 'dark' ? '☀️ 淺色' : '🌙 深色';
    }}
    function toggleTheme() {{
      const curr = document.documentElement.getAttribute('data-theme');
      applyTheme(curr === 'dark' ? 'light' : 'dark');
    }}
    const savedTheme = localStorage.getItem('edu_briefing_theme');
    if (savedTheme) {{ applyTheme(savedTheme); }}
    else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {{ applyTheme('dark'); }}

  </script>
</body>
</html>"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)


def update_event_tracker(briefing_md, hot_keywords, old_tracker):
    new_entry = {
        "date": TODAY_STR,
        "hot_keywords": hot_keywords,
        "summary": briefing_md[:800]
    }
    tracker = old_tracker if isinstance(old_tracker, list) else []
    tracker.append(new_entry)
    return tracker[-3:]


def push_to_wechat(title, markdown_content):
    if not PUSHPLUS_TOKEN:
        print("[INFO] 未配置 PUSHPLUS_TOKEN，跳過微信推送。")
        return

    pages_url = get_pages_url()
    header_banner = ""
    if pages_url:
        header_banner = (
            f"> 🎧 **聽語音播報 / 手機深淺色與大字體閱讀**：\n"
            f"> 👉 [點擊打開手機端語音早報網頁]({pages_url})\n\n---\n\n"
        )

    url = "http://www.pushplus.plus/send"
    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": header_banner + markdown_content,
        "template": "markdown",
        "topic": os.environ.get("PUSHPLUS_TOPIC", "hk-edu-briefing-Git").strip()
    }
    resp = requests.post(url, json=payload, timeout=20)
    print(f"PushPlus 推送結果：{resp.text}")


def main():
    raw_payload = load_json_safe("latest_edu_raw.json", {})
    news_list = raw_payload.get("items", []) if isinstance(raw_payload, dict) else []
    history_events = load_json_safe("event_tracker.json", [])

    if not news_list:
        briefing_md = f"### 📰 香港教育新聞早報（{TODAY_STR}）\n\n今日過去 24 小時內暫未採集到符合條件的教育新聞。"
        hot_keywords = []
    else:
        briefing_md, hot_keywords = generate_briefing_with_gemini(news_list, history_events)

    with open("latest_briefing.md", "w", encoding="utf-8") as f:
        f.write(briefing_md)

    try:
        speech_text = clean_markdown_for_tts(briefing_md)
        asyncio.run(generate_tts_audio_async(speech_text, "latest_briefing.mp3"))
    except Exception as ex:
        print(f"[WARN] TTS error: {ex}")

    build_mobile_html(briefing_md, len(news_list))

    updated_tracker = update_event_tracker(briefing_md, hot_keywords, history_events)
    with open("event_tracker.json", "w", encoding="utf-8") as f:
        json.dump(updated_tracker, f, ensure_ascii=False, indent=2)

    push_to_wechat(f"📰 香港教育新聞早報 ({TODAY_STR})", briefing_md)
    print("All tasks finished successfully.")


if __name__ == "__main__":
    main()
