import os
import re
import glob
import json
import time
import base64
import urllib.parse
import datetime
import requests
import feedparser
from bs4 import BeautifulSoup
import pytz

HKT = pytz.timezone('Asia/Hong_Kong')
NOW_HKT = datetime.datetime.now(HKT)
TODAY_DATE_STR = NOW_HKT.strftime("%Y-%m-%d")
WINDOW_START = NOW_HKT - datetime.timedelta(hours=26)

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "zh-HK,zh-TW;q=0.9,zh;q=0.8,en;q=0.7"
}

EDU_KEYWORDS = [
    "教育", "學校", "中學", "小學", "幼稚園", "大學", "院校", "教資會", "教育局", "蔡若蓮", "施俊輝",
    "DSE", "文憑試", "考評局", "學額", "縮班", "殺校", "收生", "派位", "自行分配", "統一派位", "JUPAS",
    "老師", "教師", "校長", "學生", "學童", "家長", "校董", "法團校董會", "校政", "課程", "公民科",
    "國民教育", "國安教育", "STEM", "STEAM", "SEN", "特殊教育", "學費", "直資", "津貼", "官立", "私校",
    "國際學校", "北都大學城", "留學香港", "八大", "港大", "中大", "科大", "理大", "城大", "浸大", "嶺大", "教大",
    "都大", "恒大", "樹仁", "VTC", "職訓局", "副學士", "高級文憑", "獎學金", "呈分試", "TSA", "學友社",
    "教聯會", "津小議會", "中學校長會", "輔導", "欺凌", "學童自殺", "三層應急機制", "研資局",
    "愛國主義工作小組", "愛國主義教育工作小組", "爱国主义工作小组", "立法會議員鄧飛", "立法会议员邓飞", "鄧飛", "邓飞",
    "高校", "北都", "大學城", "航天", "太空人", "升學", "學界", "開班", "辦學", "祖苗", "聯招"
]

TRACK_A_FB_PAGES = [
    {"name": "教育刺針", "url": "https://www.facebook.com/edupiercing"},
    {"name": "蔡若蓮局長", "url": "https://www.facebook.com/choiyuklin.hk"},
    {"name": "鄧飛議員", "url": "https://www.facebook.com/tangfei.hk"}
]

AD_KEYWORDS = [
    "BB手語", "流感針", "親子好去處", "即睇活動詳情", "湯水", "食滯", "食譜",
    "低至", "推介", "買一送一", "營養師推薦", "紙包飲品卡路里", "快手靚湯", "治癒系繪本",
    "WhatsApp Group", "國慶好去處", "分娩前3大重要訊號", "拼多多", "特約內容", "優惠碼",
    "妝容", "化妝", "造型拆解", "穿搭"
]

MINGPAO_TEACHING_COLS = [
    "經典解讀", "活用策略", "公民議題", "資訊素養", "活動速遞", "自我增值", "齊學SDGs", "Talk of the town",
    "Grammar", "Answers", "Game", "考考你", "大人ing", "中文同樂會", "網言網語", "文字發酵", "書到用時",
    "時事金點子", "小學生的科學", "謎之身體", "化學生活", "認識地球", "賣乜東東", "唱乜東東", "AI尋人記",
    "寫作筆記", "中文解剖師", "IB中文", "Comic", "Horizon", "社區導賞", "做一做", "名家演繹", "參考答案",
    "閱讀篇章", "閱讀策略", "尋根究柢", "時事大問答", "自我增值站", "實戰篇", "名家學堂", "視聽之娛",
    "有價講", "書之異世界", "超譯中文", "見聞識玩", "遊住學", "講故事", "中華遊樂場", "星級專訪", "答案"
]


def is_edu(text):
    if not text:
        return False
    return any(k.lower() in text.lower() for k in EDU_KEYWORDS)


def is_ad_or_evergreen(title, url=""):
    if not title:
        return True
    if any(ad in title for ad in AD_KEYWORDS):
        return True
    if "/promotion/" in url.lower():
        return True
    if re.search(r'\d+校網|校園天地|DSE\s*20\d\d\s*報名指南|持續進修基金.*懶人包', title):
        return True
    return False


# 外國教育新聞過濾：標題含外國地區/人名標記，且標題+描述均不含香港標記則剔除。
# 這些標記只用於「過濾」，絕不作為採集查詢目標；與香港教育密切相關的事件（含香港標記）一律保留。
FOREIGN_MARKERS = ["韓國", "韩国", "南韓", "南韩", "韓", "韩", "日本", "美國", "美国", "英國", "英国",
                   "台灣", "台湾", "臺灣", "新加坡", "澳洲", "加拿大", "法國", "法国", "德國", "德国", "印度",
                   "釜山", "首爾", "首尔", "東京", "东京", "大阪", "京都", "名古屋", "早苗",
                   "麻省理工", "哈佛", "史丹福", "斯坦福", "牛津", "劍橋大學", "耶魯", "普林斯頓"]
HK_MARKERS = ["香港", "港", "大灣區", "大湾区", "灣區", "湾区", "北都", "教育局", "教育局局長", "蔡若蓮"]


def is_foreign_news(title, desc=""):
    if not title:
        return False
    if not any(m in title for m in FOREIGN_MARKERS):
        return False
    # 標題或描述含香港標記 → 與香港密切相關，保留
    return not any(m in (title + " " + desc) for m in HK_MARKERS)


def decode_google_news_url(gnews_url):
    """將 Google News 的 /articles/CBMi... 跳轉鏈解碼為原文直鏈；解碼失敗則返回原鏈。"""
    try:
        token = gnews_url.split('/articles/')[-1].split('?')[0]
        padding = '=' * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + padding)
        match = re.search(rb'https?://[\x20-\x7e]+', raw)
        if match:
            return match.group(0).decode('ascii', errors='ignore')
    except Exception:
        pass
    return gnews_url


def is_mingpao_teaching(title):
    if title.strip() == "答案":
        return True
    return any(col in title for col in MINGPAO_TEACHING_COLS)


def in_window(dt_obj):
    if not dt_obj:
        return False
    if dt_obj.tzinfo is None:
        dt_obj = HKT.localize(dt_obj)
    else:
        dt_obj = dt_obj.astimezone(HKT)
    return WINDOW_START <= dt_obj <= NOW_HKT + datetime.timedelta(minutes=30)


def fmt_dt(dt_obj):
    return dt_obj.astimezone(HKT).strftime("%Y-%m-%d %H:%M")


def parse_rss_dt(entry):
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        ts = time.mktime(entry.published_parsed)
        return datetime.datetime.fromtimestamp(ts, tz=pytz.utc).astimezone(HKT)
    return None


def collect_rss_sources():
    feeds = [
        ("明報·港聞", "https://news.mingpao.com/rss/pns/s00002.xml", "kw"),
        ("明報·教育", "https://news.mingpao.com/rss/pns/s00011.xml", "mp_edu"),
        ("明報·觀點", "https://news.mingpao.com/rss/pns/s00012.xml", "mp_op"),
        ("明報·即時港聞", "https://news.mingpao.com/rss/ins/s00001.xml", "kw"),
        ("香港電台RTHK", "https://rthk.hk/rthk/news/rss/c_expressnews_clocal.xml", "kw"),
        ("政府新聞公報", "https://www.info.gov.hk/gia/rss/general_zh.xml", "kw"),
        ("灼見名家", "https://www.master-insight.com/feed/", "kw"),
    ]
    results = []
    for src, url, mode in feeds:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            feed = feedparser.parse(resp.content)
            if resp.status_code != 200 or not feed.entries:
                print(f"[WARN] RSS {src}: HTTP {resp.status_code}, {len(feed.entries)} entries parsed "
                      f"(possible anti-bot block, wrong URL, or no recent items)")
            src_count = 0
            for e in feed.entries:
                title = e.get("title", "").strip()
                link = e.get("link", "").strip()
                desc = BeautifulSoup(e.get("description", ""), "html.parser").get_text().strip()
                dt = parse_rss_dt(e)
                if not dt or not in_window(dt):
                    continue
                if is_ad_or_evergreen(title, link):
                    continue
                if is_foreign_news(title, desc[:200]):
                    continue

                if mode == "mp_edu":
                    if is_mingpao_teaching(title):
                        continue
                    category = "觀點評論" if ("：" in title and not is_edu(title)) else "主流新聞"
                    src_count += 1
                    results.append({
                        "title": title, "link": link, "src": src, "cat": category,
                        "dt": fmt_dt(dt), "desc": desc[:500]
                    })
                elif mode == "mp_op":
                    if is_edu(title + " " + desc):
                        src_count += 1
                        results.append({
                            "title": title, "link": link, "src": src, "cat": "觀點評論",
                            "dt": fmt_dt(dt), "desc": desc[:500]
                        })
                else:
                    if is_edu(title + " " + desc[:100]):
                        src_count += 1
                        results.append({
                            "title": title, "link": link, "src": src, "cat": "主流新聞",
                            "dt": fmt_dt(dt), "desc": desc[:500]
                        })
            print(f"[INFO] RSS {src}: {src_count} items (in window)")
        except Exception as ex:
            print(f"[WARN] RSS {src} failed: {ex}")
    return results


def collect_google_news_hk():
    # (查詢語句, require_edu)：require_edu=True 時標題必須含教育關鍵詞（用於 YouTube 等雜訊多的信源）
    queries = [
        ("香港 教育局 OR DSE OR 學校 OR 殺校 OR 縮班", False),
        ("香港 大學 OR 港大 OR 中大 OR 科大 OR 教資會 OR 研究 OR 課程", False),
        ("香港 蔡若蓮 OR 留學香港 OR 北都大學城 OR 鄧飛 OR 愛國主義工作小組", False),
        ("香港 教育 OR 教育局 OR DSE OR 學校 OR 升學 OR 派位 OR 選校 OR 學界 OR 校園 site:youtube.com", True),
        ("site:hk01.com 教育 OR DSE OR 學校 OR 小學 OR 中學 OR 教師 OR 校長 OR 大學 OR 課程 OR 收生 OR AI", False),
        ("site:stheadline.com 教育 OR DSE OR 學校 OR 小學 OR 中學 OR 教師 OR 校長 OR 大學 OR 課程 OR 收生", False),
        ("site:mingpao.com 教育 OR DSE OR 學校 OR 小學 OR 中學 OR 教師 OR 校長 OR 大學 OR 課程 OR 收生", False),
        ("site:scmp.com Hong Kong education OR university OR DSE OR students", False),
        ("site:thestandard.com.hk Hong Kong education OR university OR students", False)
    ]
    results = []
    seen_links = set()
    for q, require_edu in queries:
        encoded_q = urllib.parse.quote(q)
        url = f"https://news.google.com/rss/search?q={encoded_q}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            feed = feedparser.parse(resp.content)
            q_count = 0
            for e in feed.entries[:25]:
                title = e.get("title", "").strip()
                link = decode_google_news_url(e.get("link", "").strip())
                dt = parse_rss_dt(e)
                if not dt or not in_window(dt) or link in seen_links:
                    continue
                # 先分離「 - 來源」後綴再做過濾，否則「香港01」等來源名會令外國過濾失效
                parts = title.rsplit(" - ", 1)
                clean_title = parts[0]
                src_name = parts[1] if len(parts) > 1 else "港媒綜合"
                if is_ad_or_evergreen(clean_title, link):
                    continue
                if is_foreign_news(clean_title):
                    continue
                if require_edu and not is_edu(clean_title):
                    continue
                seen_links.add(link)
                q_count += 1
                results.append({
                    "title": clean_title, "link": link, "src": src_name, "cat": "主流新聞",
                    "dt": fmt_dt(dt), "desc": clean_title
                })
            print(f"[INFO] Google News query [{q[:40]}]: {q_count} items")
        except Exception as ex:
            print(f"[WARN] Google News query '{q}' failed: {ex}")
    return results


def collect_lihkg():
    results = []
    lihkg_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Referer": "https://lihkg.com/category/13",
        "X-LI-DEVICE": "web"
    }
    endpoints = [
        ("https://lihkg.com/api_v2/thread/category?cat_id=13&page=1&count=30", True),
        ("https://lihkg.com/api_v2/thread/hot?cat_id=1&page=1&count=40", True)
    ]
    seen_threads = set()
    for api_url, need_kw in endpoints:
        try:
            resp = requests.get(api_url, headers=lihkg_headers, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            items = data.get("response", {}).get("items", [])
            for item in items:
                tid = str(item.get("thread_id", ""))
                if not tid or tid in seen_threads:
                    continue
                seen_threads.add(tid)
                title = item.get("title", "").strip()
                last_reply_ts = item.get("last_reply_time", 0)
                like_count = item.get("like_count", 0)
                dislike_count = item.get("dislike_count", 0)
                no_of_reply = item.get("no_of_reply", 0)

                dt = datetime.datetime.fromtimestamp(last_reply_ts, tz=pytz.utc).astimezone(HKT)
                if not in_window(dt):
                    continue
                if no_of_reply < 5 and like_count < 10:
                    continue
                if need_kw and not is_edu(title):
                    continue

                results.append({
                    "title": title,
                    "link": f"https://lihkg.com/thread/{tid}/page/1",
                    "src": "連登討論區 LIHKG",
                    "cat": "社區輿情",
                    "dt": fmt_dt(dt),
                    "desc": f"連登熱議｜回覆數：{no_of_reply}｜正評：{like_count} / 負評：{dislike_count}"
                })
        except Exception as ex:
            print(f"[WARN] LIHKG fetch failed: {ex}")
    print(f"[INFO] LIHKG: {len(results)} items")
    return results


def run_apify_actor_sync(actor_id, run_input, timeout_sec=120):
    if not APIFY_TOKEN:
        return []
    safe_actor = actor_id.replace("/", "~")
    url = f"https://api.apify.com/v2/acts/{safe_actor}/run-sync-get-dataset-items?token={APIFY_TOKEN}&timeout={timeout_sec}"
    try:
        resp = requests.post(url, json=run_input, timeout=timeout_sec + 15)
        if resp.status_code in (200, 201):
            return resp.json()
    except Exception as ex:
        print(f"[WARN] Apify {actor_id} error: {ex}")
    return []


def collect_apify_track_a():
    if not APIFY_TOKEN:
        return []
    start_urls = [{"url": p["url"]} for p in TRACK_A_FB_PAGES]
    run_input = {
        "startUrls": start_urls,
        "resultsLimit": 5,
        "onlyPostsNewerThan": "1 day",
        "captionText": False
    }
    raw_posts = run_apify_actor_sync("apify/facebook-posts-scraper", run_input, timeout_sec=120)
    results = []
    for post in raw_posts:
        text = (post.get("text") or post.get("message") or "").strip()
        if not text:
            continue
        page_name = post.get("pageName") or post.get("user", {}).get("name") or "Facebook核心信源"
        post_url = post.get("url") or post.get("postUrl") or ""
        likes = post.get("likes", 0)
        comments = post.get("comments", 0)
        shares = post.get("shares", 0)
        title_snippet = text.replace("\n", " ")[:45] + ("..." if len(text) > 45 else "")

        results.append({
            "title": f"【FB動態｜{page_name}】{title_snippet}",
            "link": post_url,
            "src": f"Facebook·{page_name}",
            "cat": "社交核心信源",
            "dt": fmt_dt(NOW_HKT),
            "desc": f"互動數據：👍{likes} | 💬{comments} | 🔁{shares}\n貼文正文：{text[:600]}"
        })
    print(f"[INFO] Apify FB Track A: {len(results)} items")
    return results


def get_escalated_event_keywords(today_news):
    if not os.path.exists("event_tracker.json"):
        return []
    try:
        with open("event_tracker.json", "r", encoding="utf-8") as f:
            tracker = json.load(f)
    except Exception:
        return []

    if not isinstance(tracker, list) or len(tracker) == 0:
        return []

    triggered_keywords = []
    recent_records = tracker[-2:]
    kw_days = {}
    for rec in recent_records:
        for kw in rec.get("hot_keywords", []):
            kw_days[kw] = kw_days.get(kw, 0) + 1

    for kw, past_days in kw_days.items():
        today_hits = sum(1 for n in today_news if kw.lower() in (n["title"] + n.get("desc", "")).lower())
        if (past_days >= 1 and today_hits >= 3) or (past_days >= 2 and today_hits >= 1):
            triggered_keywords.append(kw)

    return triggered_keywords[:2]


def collect_apify_track_b(today_news):
    if not APIFY_TOKEN:
        return []
    keywords = get_escalated_event_keywords(today_news)
    if not keywords:
        return []

    results = []
    for kw in keywords:
        run_input = {
            "searchQueries": [f"香港 {kw}"],
            "resultsLimit": 10,
            "onlyPostsNewerThan": "2 days"
        }
        posts = run_apify_actor_sync("apify/facebook-search-scraper", run_input, timeout_sec=120)
        for p in posts:
            text = (p.get("text") or p.get("message") or "").strip()
            if not text:
                continue
            author = p.get("pageName") or p.get("user", {}).get("name") or "網民/專頁"
            likes = p.get("likes", 0)
            comments = p.get("comments", 0)
            post_url = p.get("url") or ""
            results.append({
                "title": f"【事件深挖｜{kw}】{author}：{text[:40]}...",
                "link": post_url,
                "src": f"FB輿情深挖({kw})",
                "cat": "重大事件社交輿情",
                "dt": fmt_dt(NOW_HKT),
                "desc": f"熱度：👍{likes} 💬{comments}｜觀點正文：{text[:500]}"
            })
    print(f"[INFO] Apify FB Track B (escalation): {len(results)} items")
    return results


def save_and_rotate_raw_json(items):
    payload = {
        "generated_at_hkt": fmt_dt(NOW_HKT),
        "date": TODAY_DATE_STR,
        "total_count": len(items),
        "items": items
    }

    with open("latest_edu_raw.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    os.makedirs("archive", exist_ok=True)
    archive_path = os.path.join("archive", f"edu_raw_{TODAY_DATE_STR}.json")
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    cutoff_date = (NOW_HKT - datetime.timedelta(days=30)).date()
    for filepath in glob.glob("archive/edu_raw_*.json"):
        basename = os.path.basename(filepath)
        m = re.match(r"edu_raw_(\d{4}-\d{2}-\d{2})\.json$", basename)
        if m:
            try:
                file_date = datetime.date.fromisoformat(m.group(1))
                if file_date < cutoff_date:
                    os.remove(filepath)
            except Exception:
                pass


def main():
    all_items = []
    all_items.extend(collect_rss_sources())
    all_items.extend(collect_google_news_hk())
    all_items.extend(collect_lihkg())

    deduped = []
    seen_titles = set()
    for it in all_items:
        norm_title = re.sub(r'\W+', '', it["title"].lower())[:25]
        if norm_title not in seen_titles:
            seen_titles.add(norm_title)
            deduped.append(it)

    deduped.extend(collect_apify_track_a())
    deduped.extend(collect_apify_track_b(deduped))
    save_and_rotate_raw_json(deduped)
    print(f"Done. Total items: {len(deduped)}")


if __name__ == "__main__":
    main()
