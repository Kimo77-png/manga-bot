import os
import re
import json
import requests
from bs4 import BeautifulSoup
from flask import Flask, request

app = Flask(__name__)

PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "n6ma_verify_123")
MANGADEX_API = "https://api.mangadex.org"
PREFS_FILE = "user_prefs.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en;q=0.9",
}

# ─────────────────────────────────────────────
# Sites list  (order = menu numbering)
# ─────────────────────────────────────────────
SITES = [
    {
        "number": 1,
        "name": "مانجا ليك",
        "key": "mangalek",
        "base": "https://mangalek.com",
        "search": "/?s={query}",
        "result_sel": "h3.entry-title a, div.post-title a, .listupd .bs .bsx a",
        "img_sel": "div.page-break img, div.reading-content img, #readerarea img",
    },
    {
        "number": 2,
        "name": "سوات مانجا",
        "key": "swatmanga",
        "base": "https://swatmanga.me",
        "search": "/?s={query}",
        "result_sel": "h3.entry-title a, div.post-title a, .listupd .bs .bsx a",
        "img_sel": "div.page-break img, div.reading-content img, #readerarea img",
    },
    {
        "number": 3,
        "name": "تيم إكس",
        "key": "teamx",
        "base": "https://teamxnovel.com",
        "search": "/?s={query}",
        "result_sel": "h3.entry-title a, div.post-title a, .listupd .bs .bsx a",
        "img_sel": "div.page-break img, div.reading-content img, #readerarea img",
    },
    {
        "number": 4,
        "name": "مانجا فريكس",
        "key": "mangafreaks",
        "base": "https://mangafreaks.net",
        "search": "/?s={query}",
        "result_sel": "h3.entry-title a, div.post-title a, .listupd .bs .bsx a",
        "img_sel": "div.page-break img, div.reading-content img, #readerarea img",
    },
    {
        "number": 5,
        "name": "مانجا عرب",
        "key": "mangaarab",
        "base": "https://www.manga-arab.net",
        "search": "/?s={query}",
        "result_sel": "h3.entry-title a, div.post-title a, .listupd .bs .bsx a",
        "img_sel": "div.page-break img, div.reading-content img, #readerarea img",
    },
    {
        "number": 6,
        "name": "MangaDex (إنجليزي)",
        "key": "mangadex",
        "base": None,
        "search": None,
        "result_sel": None,
        "img_sel": None,
    },
]

SITE_BY_KEY = {s["key"]: s for s in SITES}
SITE_BY_NUM = {s["number"]: s for s in SITES}

MENU_TEXT = (
    "📚 اختر موقع المانجا المفضل لديك:\n\n"
    + "\n".join(f"{s['number']}. {s['name']}" for s in SITES)
    + "\n\nأرسل الرقم فقط للاختيار.\n"
    "يمكنك تغيير الموقع في أي وقت بإرسال: مصادر"
)

CHANGE_TRIGGERS = {"مصادر", "مواقع", "تغيير", "sites", "change", "source", "sources"}
MORE_TRIGGERS = {"more", "استمر", "المزيد", "باقي", "اكمل", "أكمل", "كمل"}
NEXT_CHAPTER_TRIGGERS = {
    "الفصل التالي", "next chapter", "فصل تالي",
    "التالي", "next", "الفصل القادم", "+1", "فصل+"
}

CHAPTER_WORDS = r"(?:chapter|ch\.?|فصل|الفصل|chap\.?|ح\.?)"

# ─────────────────────────────────────────────
# User preference persistence
# ─────────────────────────────────────────────

def load_prefs():
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_prefs(prefs):
    try:
        with open(PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False)
    except Exception:
        pass


def get_user_site(sender_id):
    prefs = load_prefs()
    key = prefs.get(str(sender_id))
    return SITE_BY_KEY.get(key) if key else None


def set_user_site(sender_id, site_key):
    prefs = load_prefs()
    prefs[str(sender_id)] = site_key
    save_prefs(prefs)


def clear_user_site(sender_id):
    prefs = load_prefs()
    prefs.pop(str(sender_id), None)
    save_prefs(prefs)


def save_session(sender_id, images, pos, label):
    """Save remaining pages for the 'more' command."""
    prefs = load_prefs()
    prefs[f"session_{sender_id}"] = {"images": images, "pos": pos, "label": label}
    save_prefs(prefs)


def get_session(sender_id):
    prefs = load_prefs()
    return prefs.get(f"session_{sender_id}")


def clear_session(sender_id):
    prefs = load_prefs()
    prefs.pop(f"session_{sender_id}", None)
    save_prefs(prefs)


def save_last_request(sender_id, title, chapter_num, manga_name):
    prefs = load_prefs()
    prefs[f"last_{sender_id}"] = {
        "title": title,
        "chapter_num": float(chapter_num),
        "manga_name": manga_name or title,
    }
    save_prefs(prefs)


def get_last_request(sender_id):
    prefs = load_prefs()
    return prefs.get(f"last_{sender_id}")


# ─────────────────────────────────────────────
# Messenger helpers
# ─────────────────────────────────────────────

def send_message(recipient_id, message_data):
    url = f"https://graph.facebook.com/v21.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": message_data,
        "messaging_type": "RESPONSE",
    }
    return requests.post(url, json=payload, timeout=10)


def send_text(recipient_id, text):
    return send_message(recipient_id, {"text": text})


def send_image_url(recipient_id, img_url):
    return send_message(recipient_id, {
        "attachment": {
            "type": "image",
            "payload": {"url": img_url, "is_reusable": True},
        }
    })


# ─────────────────────────────────────────────
# MangaDex
# ─────────────────────────────────────────────

def mangadex_search(title):
    try:
        resp = requests.get(f"{MANGADEX_API}/manga", params={
            "title": title,
            "limit": 5,
            "availableTranslatedLanguage[]": "en",
            "order[relevance]": "desc",
        }, timeout=15)
        results = resp.json().get("data", [])
        return results[0] if results else None
    except Exception:
        return None


def mangadex_get_chapter(manga_id, chapter_num):
    try:
        resp = requests.get(f"{MANGADEX_API}/chapter", params={
            "manga": manga_id,
            "chapter": str(chapter_num),
            "translatedLanguage[]": "en",
            "limit": 1,
            "order[chapter]": "asc",
        }, timeout=15)
        results = resp.json().get("data", [])
        return results[0] if results else None
    except Exception:
        return None


def mangadex_get_images(chapter_id):
    try:
        resp = requests.get(f"{MANGADEX_API}/at-home/server/{chapter_id}", timeout=15)
        data = resp.json()
        base_url = data["baseUrl"]
        ch = data["chapter"]
        return [f"{base_url}/data-saver/{ch['hash']}/{p}" for p in ch["dataSaver"]]
    except Exception:
        return []


def fetch_from_mangadex(title, chapter_num):
    manga = mangadex_search(title)
    if not manga:
        return None, []
    manga_title = (
        manga["attributes"]["title"].get("en")
        or list(manga["attributes"]["title"].values())[0]
        or title
    )
    ch = mangadex_get_chapter(manga["id"], chapter_num)
    if not ch:
        return manga_title, []
    return manga_title, mangadex_get_images(ch["id"])


# ─────────────────────────────────────────────
# Arabic site scraper
# ─────────────────────────────────────────────

def scrape_chapter_images(chapter_url, img_sel):
    try:
        resp = requests.get(chapter_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        imgs = soup.select(img_sel)
        urls = []
        for img in imgs:
            src = (
                img.get("src") or img.get("data-src")
                or img.get("data-lazy-src") or ""
            ).strip()
            if src.startswith("http") and any(
                ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]
            ):
                urls.append(src)
        return urls
    except Exception:
        return []


def build_chapter_url(manga_url, chapter_num):
    manga_url = manga_url.rstrip("/")
    candidates = [
        f"{manga_url}/chapter-{chapter_num}/",
        f"{manga_url}/ch-{chapter_num}/",
        f"{manga_url}/{chapter_num}/",
        f"{manga_url}/الفصل-{chapter_num}/",
    ]
    for url in candidates:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200 and len(r.text) > 500:
                return url
        except Exception:
            continue
    return None


def fetch_from_site(site, title, chapter_num):
    try:
        query = title.replace(" ", "+")
        search_url = site["base"] + site["search"].format(query=query)
        resp = requests.get(search_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")
        links = soup.select(site["result_sel"])
        if not links:
            return None, []
        manga_url = links[0].get("href", "")
        manga_name = links[0].get_text(strip=True)
        if not manga_url:
            return None, []
        chapter_url = build_chapter_url(manga_url, chapter_num)
        if not chapter_url:
            return None, []
        images = scrape_chapter_images(chapter_url, site["img_sel"])
        return (manga_name if images else None), images
    except Exception:
        return None, []


# ─────────────────────────────────────────────
# Batch sender
# ─────────────────────────────────────────────

BATCH_SIZE = 25

def send_batch(sender_id, images, pos, label):
    """Send up to BATCH_SIZE images starting at pos. Save session if more remain."""
    chunk = images[pos: pos + BATCH_SIZE]
    total = len(images)
    end = pos + len(chunk)
    failed = 0

    for url in chunk:
        try:
            r = send_image_url(sender_id, url)
            if r and r.status_code != 200:
                failed += 1
        except Exception:
            failed += 1

    sent = len(chunk) - failed
    remaining = total - end

    if remaining > 0:
        save_session(sender_id, images, end, label)
        send_text(sender_id,
            f"📌 تم إرسال {sent} صفحة ({end} من {total}).\n"
            f"تبقّى {remaining} صفحة — أرسل: المزيد"
        )
    else:
        clear_session(sender_id)
        send_text(sender_id, f"✅ اكتمل الفصل! ({sent} صفحة)")


# ─────────────────────────────────────────────
# Request parsing
# ─────────────────────────────────────────────

def parse_manga_request(text):
    text = text.strip()
    patterns = [
        rf"^(.+?)\s+{CHAPTER_WORDS}\s*(\d+(?:\.\d+)?)$",
        r"^(.+?)\s+(\d+(?:\.\d+)?)$",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return None, None


# ─────────────────────────────────────────────
# Message handler
# ─────────────────────────────────────────────

def handle_message(sender_id, text):
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # ── "Next chapter" ──
    if text_lower in NEXT_CHAPTER_TRIGGERS:
        last = get_last_request(sender_id)
        if not last:
            send_text(sender_id,
                "لم أجد طلباً سابقاً.\n"
                "أرسل اسم المانجا ورقم الفصل أولاً."
            )
            return
        chosen_site = get_user_site(sender_id)
        if not chosen_site:
            send_text(sender_id, MENU_TEXT)
            return
        next_num = last["chapter_num"] + 1
        next_num_str = str(int(next_num)) if next_num == int(next_num) else str(next_num)
        title = last["title"]
        clear_session(sender_id)
        send_text(sender_id,
            f"⏭ الفصل التالي: {last['manga_name']} — فصل {next_num_str}\n"
            f"📡 المصدر: {chosen_site['name']}"
        )
        if chosen_site["key"] == "mangadex":
            manga_name, images = fetch_from_mangadex(title, next_num_str)
        else:
            manga_name, images = fetch_from_site(chosen_site, title, next_num_str)
        if not images:
            send_text(sender_id,
                f"❌ لم أجد فصل {next_num_str} على {chosen_site['name']}.\n"
                "ربما لم يُترجم بعد، أو جرّب موقعاً آخر: مصادر"
            )
            return
        label = f"{manga_name or title} — فصل {next_num_str}"
        total = len(images)
        save_last_request(sender_id, title, next_num_str, manga_name)
        send_text(sender_id, f"✅ {label}\n📄 {total} صفحة. جاري الإرسال...")
        send_batch(sender_id, images, 0, label)
        return

    # ── "More" — continue sending remaining pages ──
    if text_lower in MORE_TRIGGERS:
        session = get_session(sender_id)
        if not session:
            send_text(sender_id,
                "لا توجد صفحات محفوظة.\n"
                "أرسل اسم المانجا ورقم الفصل لتبدأ."
            )
            return
        label = session["label"]
        images = session["images"]
        pos = session["pos"]
        remaining = len(images) - pos
        send_text(sender_id,
            f"📖 متابعة: {label}\n"
            f"جاري إرسال {min(BATCH_SIZE, remaining)} صفحة..."
        )
        send_batch(sender_id, images, pos, label)
        return

    # ── Change/show site menu ──
    if text_lower in CHANGE_TRIGGERS:
        clear_user_site(sender_id)
        clear_session(sender_id)
        send_text(sender_id, MENU_TEXT)
        return

    # ── Site selection by number ──
    if re.fullmatch(r"\d", text_stripped):
        num = int(text_stripped)
        site = SITE_BY_NUM.get(num)
        if site:
            set_user_site(sender_id, site["key"])
            clear_session(sender_id)
            send_text(
                sender_id,
                f"✅ تم الاختيار: {site['name']}\n\n"
                "الآن أرسل اسم المانجا ورقم الفصل، مثلاً:\n"
                "  ون بيس فصل 1000\n"
                "  Solo Leveling 100\n\n"
                "لتغيير الموقع أرسل: مصادر"
            )
            return
        else:
            send_text(sender_id, f"❌ رقم غير صحيح. اختر من 1 إلى {len(SITES)}.")
            return

    # ── Check if user has chosen a site ──
    chosen_site = get_user_site(sender_id)
    if not chosen_site:
        send_text(sender_id, MENU_TEXT)
        return

    # ── Parse manga request ──
    title, chapter = parse_manga_request(text_stripped)
    if not title or not chapter:
        send_text(sender_id,
            "أرسل اسم المانجا ورقم الفصل، مثلاً:\n"
            "  ون بيس فصل 1000\n"
            "  Solo Leveling chapter 100\n"
            "  Naruto 700\n\n"
            "لتغيير الموقع: مصادر"
        )
        return

    # New request clears any previous session
    clear_session(sender_id)

    send_text(sender_id,
        f"🔍 جاري البحث عن: {title} — فصل {chapter}\n"
        f"📡 المصدر: {chosen_site['name']}"
    )

    # ── Fetch chapter ──
    if chosen_site["key"] == "mangadex":
        manga_name, images = fetch_from_mangadex(title, chapter)
    else:
        manga_name, images = fetch_from_site(chosen_site, title, chapter)

    if not images:
        send_text(sender_id,
            f"❌ لم أجد {title} فصل {chapter} على {chosen_site['name']}.\n"
            "تأكد من الاسم والرقم، أو غيّر الموقع بإرسال: مصادر"
        )
        return

    label = f"{manga_name or title} — فصل {chapter}"
    total = len(images)
    save_last_request(sender_id, title, chapter, manga_name)
    send_text(sender_id,
        f"✅ {label}\n"
        f"📄 {total} صفحة. جاري الإرسال..."
    )

    send_batch(sender_id, images, 0, label)


# ─────────────────────────────────────────────
# Flask routes
# ─────────────────────────────────────────────

@app.route("/")
def home():
    return "MangaBot 📚 يعمل!"


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "Verification failed", 403

    data = request.get_json(silent=True) or {}
    if data.get("object") == "page":
        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = event["sender"]["id"]
                if "message" in event and not event["message"].get("is_echo"):
                    text = event["message"].get("text", "")
                    if text:
                        try:
                            handle_message(sender_id, text)
                        except Exception:
                            send_text(sender_id, "❌ حدث خطأ. حاول مرة أخرى.")
    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

