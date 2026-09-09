# coding=utf-8
# //@name:蘑菇影院
# //@id:mgyy
# //@version:2
#
# 四壳契约（TVBox / 影视仓 / OK影视 / PickTV）：
#  - 双协议兼容继承 base.spider（try导入失败则本地最小基类兜底）
#  - 13 标准接口齐全且全部可调用，方法 *args 兼容两种签名
#  - homeContent: class + filters 为 dict
#  - 列表五键 page/pagecount/limit/total/list
#  - 详情多线路 $$$、多集 #、集名与地址 $
#  - playerContent header 为 dict、parse=0/jx=0
#  - init 预热网络通道
#  - Accept-Encoding 统一 gzip, deflate（不声明 br）
#  - 铁律11：内置 CLASSICAL_MAP + desensitize()，智能判断（不含敏感词直接返回原文），返回前对展示文本脱敏
#  - 铁律13：未成年相关条目（萝莉/幼女/少女/童/teen/loli/schoolgirl等）脱敏后直接剔除不返回
#  - 铁律15：本站无 Cloudflare/WAF，默认直连原始站点；ext.proxy/ext.siteUrl 可启用反代，playerContent.header 含 Referer+Origin 破防盗链
#  - 铁律17：广告处理为建议项，保留完整 m3u8 广告清洗能力（localProxy+_clean_m3u8+_is_ad_segment），运行时 auto 智能开关

import ast
import json
import os
import re
import ssl
import threading
import time
from urllib.parse import quote, unquote, urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.poolmanager import PoolManager
    HAS_URLLIB3 = True
except Exception:
    PoolManager = None
    HAS_URLLIB3 = False

# 双协议兼容继承（铁律8）：有 base.spider 就继承，没有则本地最小基类兜底
try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    class _BaseSpider:
        def init(self, extend=""):
            pass

DEFAULT_HOST = "https://abp.mgyy5.skin"
PAGE_SIZE = 72
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
PLAYER_UA = DEFAULT_UA

NAV_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-User": "?1",
}

CHALLENGE_MARKERS = (
    "cf-browser-verification", "just a moment", "attention required",
    "turnstile", "enable javascript and cookies to continue",
)

# 硬编码分类兜底（首页动态解析失败时使用），按首页导航顺序
FALLBACK_CATEGORIES = (
    ("20", "亚洲情色"), ("21", "制服师生"), ("22", "卡通动漫"),
    ("23", "丝袜美腿"), ("24", "强奸乱伦"), ("25", "偷拍自拍"),
    ("29", "人妻熟女"), ("30", "无码专区"), ("32", "自淫系列"),
    ("36", "国产精品"), ("33", "拳交系列"), ("28", "欧美性爱"),
    ("31", "SM捆绑"), ("35", "男同女同"), ("26", "4K岛国"),
    ("27", "中文字幕"), ("37", "三级伦理"),
)

SORTS = (
    ("", "默认"),
)

PACKED_RE = re.compile(
    r"}\('(?P<p>(?:\\.|[^'\\])*)',(?P<a>\d+),(?P<c>\d+),'(?P<k>(?:\\.|[^'\\])*)'\.split\('\|'\)"
)
SOURCE_ASSIGN_RE = re.compile(r"(source(?:\d+)?)\s*=\s*'(https?://[^']+\.m3u8[^']*)'", re.I)
_B36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"

# ========== 铁律11：敏感词古典映射脱敏表（智能判断，不含则原文返回） ==========
CLASSICAL_MAP = {
    "成人": "风月", "色情": "风月", "情色": "春宫", "淫": "风月", "黄色": "春宫", "淫秽": "猥亵",
    "AV": "光影", "av": "光影", "三级": "风月",
    "激情": "云雨", "做爱": "云雨", "性交": "交欢", "欲": "情思", "高潮": "云端",
    "偷拍": "窥帘", "偷窥": "窥帘", "乱伦": "禁脔", "强奸": "强占", "轮奸": "群辱",
    "迷奸": "迷占", "无码": "素纱", "有码": "遮面", "熟女": "徐娘",
    "萝莉": "豆蔻", "幼女": "玉蕊", "少女": "碧玉", "学生": "书生",
    "人妻": "罗敷", "少妇": "艳妇", "御姐": "玉人", "护士": "药女",
    "教师": "先生", "医生": "郎中", "警察": "捕快", "军人": "军爷",
    "秘书": "掌印", "老板": "东家", "丈夫": "夫君", "妻子": "拙荆",
    "情人": "相好", "小三": "外遇", "二奶": "外室", "出轨": "翻墙",
    "偷情": "私会", "通奸": "私通", "嫖娼": "寻花", "卖淫": "卖身",
    "妓女": "花娘", "性骚扰": "轻薄", "猥亵": "猥亵", "露阴": "曝玉",
    "咸猪手": "禄山爪", "丝袜": "丝履", "网袜": "网履", "内衣": "亵衣",
    "内裤": "亵裤", "情趣": "风月", "春药": "催情", "巨乳": "丰盈",
    "爆乳": "丰盈", "胸": "酥胸", "乳": "玉兔", "美乳": "玉兔",
    "臀": "玉臀", "屁股": "玉臀", "脚": "莲步", "玉足": "莲步",
    "腿": "玉腿", "裸体": "玉体", "全裸": "玉体", "半裸": "半褪",
    "走光": "泄春", "露点": "泄玉", "自慰": "弄玉", "口交": "含朱",
    "口活": "含朱", "肛交": "后庭", "屁眼": "后庭", "肛门": "后庭",
    "群交": "合卺", "乳交": "玉兔", "足交": "莲步", "车震": "车行",
    "野战": "郊合", "精液": "元阳", "精子": "元阳", "阴道": "幽处",
    "阴户": "幽处", "阴茎": "玉茎", "阳具": "玉茎", "SM": "调教",
    "制服": "官衣", "OL": "衙内", "空姐": "行云", "继母": "继室",
    "姐妹": "同根", "同学": "同窗", "邻居": "东邻", "处女": "处子",
    "初夜": "破瓜", "暴力": "杀伐", "血腥": "殷红", "恐怖": "幽冥",
    "赌博": "孤注", "毒品": "药石", "枪支": "火器", "刀具": "利刃",
}

# 铁律13：未成年相关关键词（脱敏后仍命中则剔除不返回）
# "学生"/"书生"不纳入——高中生/大学生可能已成年；仅明确指向未成年的词
_MINOR_KEYWORDS = (
    "豆蔻", "玉蕊", "碧玉", "稚子", "未成年", "teen", "loli",
    "schoolgirl", "萝莉", "幼女", "少女", "童",
)

# 铁律15：默认反代配置路径（本站默认直连，仅 ext.proxy 时启用）
_PROXY_CONFIG_PATHS = (
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "proxy_config.json"),
    os.path.expanduser("~/.super_doubao/super-doubao-runtime/workspace/.user_skills/tvbox-dev/assets/proxy_config.json"),
)
_DEFAULT_PROXY_FALLBACK = "https://xsz-shared-proxy.97471201.workers.dev"


def _load_default_proxy():
    for path in _PROXY_CONFIG_PATHS:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                proxy = data.get("default_proxy", "").strip()
                if proxy:
                    return proxy
        except Exception:
            continue
    return _DEFAULT_PROXY_FALLBACK


def _has_sensitive_word(text):
    """铁律11智能判断：检测文本是否含任何敏感词，不含则直接返回原文（零误触）"""
    if not text:
        return False
    s = str(text)
    for key in CLASSICAL_MAP:
        if key in s:
            return True
    return False


def desensitize(text):
    """铁律11：智能判断脱敏——不含敏感词直接返回原文，含则古典映射替换；
    铁律13：未成年相关词命中则返回空字符串（跳过不展示）"""
    if text is None:
        return ""
    result = str(text)
    # 智能判断：不含任何敏感词直接返回原文，零误触
    if not _has_sensitive_word(result):
        # 仍需检测未成年（原始词）
        lower = result.lower()
        for kw in _MINOR_KEYWORDS:
            if kw.lower() in lower:
                return ""
        return result
    # 含敏感词：长词优先全局替换
    for key in sorted(CLASSICAL_MAP.keys(), key=len, reverse=True):
        if key in result:
            result = result.replace(key, CLASSICAL_MAP[key])
    # 脱敏后检测未成年，命中则返回空字符串（铁律13）
    lower = result.lower()
    for kw in _MINOR_KEYWORDS:
        if kw.lower() in lower:
            return ""
    return result


def _is_minor_content(text):
    """铁律13：检测文本是否含未成年相关内容（脱敏前后都检测）"""
    if not text:
        return False
    lower = str(text).lower()
    for kw in _MINOR_KEYWORDS:
        if kw.lower() in lower:
            return True
    return False


def _sanitize_vod(vod):
    """铁律11+13：对单个vod字典做脱敏，未成年条目返回None"""
    if not isinstance(vod, dict):
        return vod
    name = vod.get("vod_name", "")
    remarks = vod.get("vod_remarks", "")
    content = vod.get("vod_content", "")
    # 铁律13：未成年条目直接剔除
    if _is_minor_content(name) or _is_minor_content(remarks) or _is_minor_content(content):
        return None
    # 铁律11：智能脱敏
    vod["vod_name"] = desensitize(name)
    if vod.get("vod_remarks") is not None:
        vod["vod_remarks"] = desensitize(remarks)
    if vod.get("vod_content") is not None:
        vod["vod_content"] = desensitize(content)
    if not vod["vod_name"]:
        return None
    return vod


def _sanitize_list(vod_list):
    if not isinstance(vod_list, list):
        return vod_list
    result = []
    for item in vod_list:
        cleaned = _sanitize_vod(item)
        if cleaned is not None:
            result.append(cleaned)
    return result


def _sanitize_classes(classes):
    if not isinstance(classes, list):
        return classes
    result = []
    for cat in classes:
        if not isinstance(cat, dict):
            result.append(cat)
            continue
        name = cat.get("type_name", "")
        if _is_minor_content(name):
            continue
        cat["type_name"] = desensitize(name)
        if cat["type_name"]:
            result.append(cat)
    return result


def _clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


def _bounded_int(value, default, minimum, maximum):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return min(max(number, minimum), maximum)


def _parse_config(value):
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (list, tuple)):
        merged = {}
        for item in value:
            merged.update(_parse_config(item))
        return merged
    text = str(value or "").strip()
    if not text:
        return {}
    for loader in (json.loads, ast.literal_eval):
        try:
            data = loader(text)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def _normalize_origin(value):
    text = str(value or DEFAULT_HOST).strip().rstrip("/")
    if text and "://" not in text:
        text = "https://" + text
    try:
        parsed = urlsplit(text)
    except Exception:
        return DEFAULT_HOST
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return DEFAULT_HOST
    return parsed.scheme + "://" + parsed.netloc


def _classify_response(response):
    status = int(getattr(response, "status_code", 0) or 0)
    text = str(getattr(response, "text", "") or "")
    lower = text.lower()
    if any(marker in lower for marker in CHALLENGE_MARKERS):
        return "cloudflare-managed-challenge"
    if status == 429:
        return "rate-limited"
    if 500 <= status <= 599:
        return "upstream-error"
    if status >= 400:
        return "http-error"
    if not text.strip():
        return "empty-response"
    return "ok"


def _js_unescape(text):
    return (
        str(text or "").replace("\\\\", "\x00").replace("\\'", "'")
        .replace('\\"', '"').replace("\\/", "/").replace("\\n", "\n")
        .replace("\x00", "\\")
    )


def _base_convert(number, radix):
    out = ""
    while True:
        number, remainder = divmod(number, radix)
        out = (_B36_DIGITS[remainder] if remainder < 36 else chr(remainder + 29)) + out
        if number == 0:
            return out


def unpack_eval_blocks(text):
    results = []
    for match in PACKED_RE.finditer(str(text or "")):
        try:
            payload = _js_unescape(match.group("p"))
            radix = int(match.group("a"))
            count = int(match.group("c"))
            words = _js_unescape(match.group("k")).split("|")
            table = {}
            for index in range(count):
                key = _base_convert(index, radix)
                value = words[index] if index < len(words) else ""
                table[key] = value if value else key
            results.append(re.sub(r"\b\w+\b", lambda m: table.get(m.group(0), m.group(0)), payload))
        except Exception:
            continue
    return results


def extract_play_sources(html_text):
    sources = {}
    for block in unpack_eval_blocks(html_text):
        for name, url in SOURCE_ASSIGN_RE.findall(block):
            sources[name.lower()] = url
    if not sources:
        for name, url in SOURCE_ASSIGN_RE.findall(str(html_text or "")):
            sources[name.lower()] = url
    return sources


class CloudflareTLSAdapter(HTTPAdapter):
    def __init__(self, ciphers=None, use_x25519=False, **kwargs):
        self._ciphers = ciphers
        self._use_x25519 = use_x25519
        super(CloudflareTLSAdapter, self).__init__(**kwargs)

    def _build_context(self):
        context = ssl.create_default_context()
        if self._ciphers:
            try:
                context.set_ciphers(self._ciphers)
            except Exception:
                pass
        try:
            context.minimum_version = ssl.TLSVersion.TLSv1_2
        except Exception:
            pass
        try:
            context.set_alpn_protocols(["h2", "http/1.1"])
        except Exception:
            pass
        if self._use_x25519:
            for curve in ("X25519", "prime256v1"):
                try:
                    context.set_ecdh_curve(curve)
                    break
                except Exception:
                    continue
        return context

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        context = self._build_context()
        if HAS_URLLIB3 and PoolManager is not None:
            kwargs["ssl_context"] = context
            self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block, **kwargs)
        else:
            super(CloudflareTLSAdapter, self).init_poolmanager(connections, maxsize, block=block, **kwargs)

    def proxy_manager_for(self, proxy, **kwargs):
        try:
            kwargs["ssl_context"] = self._build_context()
        except Exception:
            pass
        return super(CloudflareTLSAdapter, self).proxy_manager_for(proxy, **kwargs)


def build_tls_session(user_agent=None, cookie="", use_x25519=False):
    session = requests.Session()
    try:
        session.headers.clear()
    except Exception:
        pass
    headers = dict(NAV_HEADERS)
    headers["User-Agent"] = user_agent or DEFAULT_UA
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)
    try:
        session.mount("https://", CloudflareTLSAdapter(use_x25519=use_x25519))
    except Exception:
        pass
    return session


class Spider(_BaseSpider):
    name = "蘑菇影院"
    backend_parse = False
    category_mode = False

    def __init__(self):
        self.host = DEFAULT_HOST
        self.rawSite = DEFAULT_HOST
        self.siteUrl = DEFAULT_HOST
        self.HOST = DEFAULT_HOST
        self.timeout = 15
        self.cookie = ""
        self.max_retries = 2
        self.total_budget = 8.0
        self.use_x25519 = False
        self._warmed = False
        self._page_cache = {}
        self._cache_lock = threading.RLock()
        self.cache_ttl = 60
        self.warmup_enabled = True
        self._categories = []
        # 铁律15：本站无CF/WAF，默认直连（_use_proxy=False）
        self._use_proxy = False
        self._default_proxy = _load_default_proxy()
        self.session = self._build_session()

    def getDependence(self):
        return ""

    def getName(self):
        return self.name

    def init(self, extend=""):
        config = _parse_config(extend)
        # 铁律15：原始站点（用于Referer/Origin防盗链）
        self.rawSite = _normalize_origin(config.get("host") or DEFAULT_HOST)
        # 铁律15：本站默认直连；ext.proxy/ext.siteUrl 可启用反代；ext.direct=true 强制直连
        direct = _bool(config.get("direct"), True)  # 默认直连
        ext_proxy = str(config.get("proxy") or config.get("siteUrl") or "").strip()
        if ext_proxy and not direct:
            self._use_proxy = True
            self.siteUrl = _normalize_origin(ext_proxy)
        else:
            self._use_proxy = False
            self.siteUrl = self.rawSite
        self.host = self.siteUrl
        self.HOST = self.siteUrl
        self.timeout = _bounded_int(config.get("timeout"), 15, 5, 40)
        self.cookie = str(config.get("cookie") or "").strip()
        self.max_retries = _bounded_int(config.get("max_retries"), 2, 0, 6)
        self.total_budget = max(float(_bounded_int(config.get("total_budget"), 8, 3, 40)), 3.0)
        self.use_x25519 = _bool(config.get("use_x25519"), False)
        self.cache_ttl = _bounded_int(config.get("cache_ttl"), 60, 0, 900)
        self.warmup_enabled = _bool(config.get("warmup"), True)
        self._categories = []
        self._warmed = False
        with self._cache_lock:
            self._page_cache = {}
        self.session = self._build_session()
        try:
            self._warmup()
        except Exception:
            pass
        return ""

    def _warmup(self):
        if self._warmed or not self.warmup_enabled:
            return
        self._warmed = True
        try:
            url = self.host + "/"
            html_text, final_url = self._fetch_url(url, referer=self.rawSite + "/",
                                                     timeout=min(self.timeout, 12), retries=0)
            self._cache_put(url, (html_text, final_url))
            self._categories = self._parse_categories(html_text)
        except Exception:
            pass

    def _build_session(self):
        return build_tls_session(DEFAULT_UA, self.cookie, use_x25519=self.use_x25519)

    def _request_headers(self, referer):
        headers = dict(NAV_HEADERS)
        headers["User-Agent"] = DEFAULT_UA
        if referer:
            headers["Referer"] = referer
            headers["Sec-Fetch-Site"] = "same-origin"
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    def _cache_put(self, key, value):
        with self._cache_lock:
            self._page_cache[key] = (time.time(), value)
            if len(self._page_cache) > 24:
                oldest = sorted(self._page_cache.items(), key=lambda kv: kv[1][0])[:8]
                for stale_key, _ in oldest:
                    self._page_cache.pop(stale_key, None)

    def _cache_get(self, key):
        with self._cache_lock:
            hit = self._page_cache.get(key)
        if not hit:
            return None
        stamp, value = hit
        if time.time() - stamp > self.cache_ttl:
            with self._cache_lock:
                self._page_cache.pop(key, None)
            return None
        return value

    def _fetch_direct(self, url, referer, timeout, retries, deadline=None):
        headers = self._request_headers(referer)
        last_exc = None
        for attempt in range(max(retries, 0) + 1):
            if deadline is not None and time.time() >= deadline:
                break
            slot = timeout
            if deadline is not None:
                slot = max(min(timeout, deadline - time.time()), 2)
            try:
                response = self.session.get(url, headers=headers, timeout=slot, allow_redirects=True)
                verdict = _classify_response(response)
                if verdict == "cloudflare-managed-challenge":
                    if attempt < retries:
                        time.sleep(min(0.6 * (attempt + 1), 2.0))
                        continue
                    raise ValueError("Cloudflare 挑战页")
                if verdict == "rate-limited":
                    if attempt < retries:
                        time.sleep(min(0.6 * (attempt + 1), 2.0))
                        continue
                    raise ValueError("请求被限流 (429)")
                if verdict in ("http-error", "upstream-error"):
                    raise ValueError("HTTP %s" % getattr(response, "status_code", "?"))
                if verdict == "empty-response":
                    raise ValueError("空响应")
                return response.text, str(getattr(response, "url", url))
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    time.sleep(min(0.6 * (attempt + 1), 2.0))
                    continue
                break
        raise last_exc or RuntimeError("请求失败")

    def _fetch_url(self, url, referer=None, timeout=None, retries=None):
        if timeout is None:
            timeout = self.timeout
        if retries is None:
            retries = self.max_retries
        deadline = time.time() + max(self.total_budget, timeout)
        try:
            result = self._fetch_direct(url, referer, timeout, retries, deadline=deadline)
            return result
        except Exception as exc:
            raise ValueError(_clean_text(exc) or "请求失败")

    def isVideoFormat(self, url):
        text = str(url or "").lower()
        return bool(text) and bool(re.search(r"\.(?:m3u8|mp4|mkv|flv|avi|ts)(?:[?#]|$)", text))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        return ""

    def destroy(self):
        try:
            if self.session is not None:
                self.session.close()
        except Exception:
            pass
        return ""

    # ==================== 分类解析（蘑菇影院：/vodtype/<id>.html 平级分类） ====================

    def _parse_categories(self, html_text):
        classes = []
        seen = set()
        # 蘑菇影院分类链接：<a href="/vodtype/数字.html" ...>分类名</a>
        for m in re.finditer(
            r'<a[^>]*href="/vodtype/(\d+)\.html"[^>]*>([^<]+)</a>',
            str(html_text or "")
        ):
            tid, tname = m.group(1), _clean_text(m.group(2))
            if tid in seen or not tname or tname in ("网站首页", "首页"):
                continue
            seen.add(tid)
            classes.append({"type_id": tid, "type_name": tname})
        # 动态解析失败则用硬编码兜底
        if not classes:
            for tid, tname in FALLBACK_CATEGORIES:
                classes.append({"type_id": tid, "type_name": tname})
        return classes

    def _ensure_categories(self):
        if self._categories:
            return self._categories
        try:
            html_text, _ = self._fetch_url(self.host + "/", referer=self.rawSite + "/")
            self._categories = self._parse_categories(html_text)
        except Exception:
            self._categories = [{"type_id": tid, "type_name": tname} for tid, tname in FALLBACK_CATEGORIES]
        return self._categories

    def _filters(self):
        options = [{"n": label, "v": value} for value, label in SORTS]
        cats = self._ensure_categories()
        return {
            cat["type_id"]: [{"key": "sort", "name": "排序", "init": "", "value": options}]
            for cat in cats
        }

    # ==================== 13 标准接口 ====================

    def homeContent(self, *args):
        cats = _sanitize_classes(self._ensure_categories())
        result = {
            "class": cats,
            "filters": self._filters(),
            "list": [],
        }
        try:
            first_tid = cats[0]["type_id"] if cats else "20"
            result["list"] = _sanitize_list(self.categoryContent(first_tid, 1).get("list", []))
        except Exception:
            result["list"] = []
        return result

    def homeVideoContent(self, *args):
        cats = self._ensure_categories()
        first_tid = cats[0]["type_id"] if cats else "20"
        result = self.categoryContent(first_tid, 1)
        result["list"] = _sanitize_list(result.get("list", []))
        return result

    def categoryContent(self, *args):
        # 兼容 (tid, pg, filter, extend) 和 (tid, pg)
        tid = args[0] if len(args) > 0 else "20"
        pg = args[1] if len(args) > 1 else 1
        page = _bounded_int(pg, 1, 1, 100000)
        slug = str(tid or "").strip()
        if not slug:
            return self._empty_page(page)
        # 蘑菇影院分类分页：第1页 /vodtype/<id>.html，第N页 /vodtype/<id>-<N>.html
        if page <= 1:
            url = self.host + "/vodtype/" + slug + ".html"
        else:
            url = self.host + "/vodtype/" + slug + "-" + str(page) + ".html"
        result = self._list_page(url, page)
        result["list"] = _sanitize_list(result.get("list", []))
        return result

    def searchContent(self, *args):
        # 兼容 (wd, page) / (key, quick) / (key, quick, pg)
        key = args[0] if len(args) > 0 else ""
        pg = 1
        if len(args) >= 3:
            pg = args[2]
        elif len(args) == 2:
            # 第二个参数可能是 quick(bool) 或 page
            second = args[1]
            if isinstance(second, (int, float)) or (isinstance(second, str) and second.isdigit()):
                pg = second
        keyword = _clean_text(key)
        page = _bounded_int(pg, 1, 1, 100000)
        if not keyword:
            return self._empty_page(page)
        # 蘑菇影院搜索：/s/<urlencode关键词>/page/<N>.html
        url = self.host + "/s/" + quote(keyword) + "/page/" + str(page) + ".html"
        try:
            result = self._list_page(url, page, tolerate_empty=True)
            result["list"] = _sanitize_list(result.get("list", []))
            return result
        except Exception:
            return self._empty_page(page)

    def _empty_page(self, page):
        return {"page": page, "pagecount": page, "limit": PAGE_SIZE, "total": 0, "list": []}

    def _list_page(self, url, page, tolerate_empty=False):
        try:
            cached = self._cache_get(url)
            if cached is not None:
                html_text, final_url = cached
            else:
                html_text, final_url = self._fetch_url(url, referer=self.rawSite + "/")
                self._cache_put(url, (html_text, final_url))
            items = self._parse_list(html_text)
            if not items and tolerate_empty:
                return {"page": page, "pagecount": page, "limit": PAGE_SIZE, "total": 0, "list": []}
            pagecount = self._parse_pagecount(html_text, page)
            if items and pagecount <= page:
                pagecount = page + 1
            limit = len(items) or PAGE_SIZE
            return {"page": page, "pagecount": pagecount, "limit": limit, "total": pagecount * limit, "list": items}
        except Exception as exc:
            if tolerate_empty:
                raise
            message = _clean_text(exc) or "列表加载失败"
            return {"page": page, "pagecount": page, "limit": PAGE_SIZE, "total": 1, "list": [{
                "vod_id": "error:" + message, "vod_name": "访问受限：" + message,
                "vod_pic": "", "vod_remarks": "可在插件配置里填写代理网关",
            }]}

    def _parse_list(self, html_text):
        """蘑菇影院列表卡片：<a href="/<id>.html">...<img src="封面">...clamp2标题</div>"""
        items = []
        seen = set()
        pattern = re.compile(
            r'<a[^>]*href="/(\d+)\.html"[^>]*>.*?'
            r'<img[^>]*src="([^"]+)"[^>]*>.*?'
            r'class="[^"]*clamp2[^"]*">([^<]+)</div>',
            re.DOTALL
        )
        for m in pattern.finditer(str(html_text or "")):
            vid, pic, name = m.group(1), m.group(2), _clean_text(m.group(3))
            if not vid or vid in seen:
                continue
            seen.add(vid)
            if not name:
                name = "未命名"
            # 封面可能是相对路径或绝对路径
            if pic and not pic.startswith("http"):
                pic = urljoin(self.host + "/", pic)
            items.append({
                "vod_id": vid, "vod_name": name,
                "vod_pic": pic, "vod_remarks": "", "vod_year": "",
                "vod_area": "", "vod_type": "",
            })
        return items

    @staticmethod
    def _parse_pagecount(html_text, current):
        """蘑菇影院分页：/vodtype/<id>-<N>.html 或 /s/关键词/page/<N>.html"""
        pages = [current]
        for m in re.finditer(r'/vodtype/\d+-(\d+)\.html', str(html_text or "")):
            pages.append(_bounded_int(m.group(1), current, 1, 100000))
        for m in re.finditer(r'/page/(\d+)\.html', str(html_text or "")):
            pages.append(_bounded_int(m.group(1), current, 1, 100000))
        return max(pages)

    def detailContent(self, ids):
        # 铁律8：ids是list/tuple必须遍历，不能只取第一个
        id_list = list(ids) if isinstance(ids, (list, tuple)) else [ids]
        result_list = []
        for source_id in id_list:
            vid = str(source_id or "").strip()
            if vid.startswith("error:"):
                result_list.append(self._error_detail(vid[6:]))
                continue
            if not vid or not re.search(r'\d', vid):
                result_list.append(self._error_detail("缺少有效的详情标识"))
                continue
            # 蘑菇影院详情页：/<id>.html
            detail_url = self.host + "/" + vid + ".html"
            try:
                html_text, final_url = self._fetch_url(detail_url, referer=self.rawSite + "/")
            except Exception as exc:
                result_list.append(self._error_detail(_clean_text(exc)))
                continue
            html_text = re.sub(r'<!--.*?-->', '', html_text, flags=re.DOTALL)
            # 标题：<title>标题 - 蘑菇影院</title>
            name = ""
            t_m = re.search(r'<title>([^<]+)</title>', html_text)
            if t_m:
                name = re.sub(r'\s*[-—|]\s*蘑菇影院.*$', '', t_m.group(1)).strip()
            if not name:
                name = vid
            # 封面：详情页可能没有独立封面，留空（列表页已有）
            pic = ""
            pic_m = re.search(r'<div[^>]*class="[^"]*(?:detail-poster|vod-pic|video-cover)[^"]*"[^>]*>.*?<img[^>]*src="([^"]+)"', html_text, re.DOTALL)
            if pic_m:
                pic = pic_m.group(1)
                if pic and not pic.startswith("http"):
                    pic = urljoin(self.host + "/", pic)
            # 播放地址：详情页内嵌 DPlayer，const rawUrl = 'https://...m3u8';
            real_url = ""
            raw_m = re.search(r"rawUrl\s*=\s*['\"](https?://[^'\"]+\.m3u8[^'\"]*)['\"]", html_text, re.I)
            if raw_m:
                real_url = raw_m.group(1)
            if not real_url:
                # 兜底：任意 m3u8 链接
                m3u8_m = re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html_text)
                if m3u8_m:
                    real_url = m3u8_m.group(0)
            if not real_url:
                # 再兜底：eval 解包 source
                sources = extract_play_sources(html_text)
                if sources:
                    real_url = list(sources.values())[0]
            # 单线路单集（蘑菇影院无多线路/剧集）
            source_name = "默认线路"
            if real_url:
                play_from = source_name
                play_url = "正片$" + real_url
            else:
                play_from = source_name
                play_url = ""
            vod = {
                "vod_id": vid, "vod_name": name, "vod_pic": pic,
                "vod_remarks": "", "vod_year": "", "vod_area": "",
                "vod_lang": "", "vod_actor": "", "vod_director": "",
                "vod_type": "", "vod_content": name,
                "vod_play_from": play_from,
                "vod_play_url": play_url,
            }
            # 铁律11+13：详情页脱敏，未成年条目跳过
            cleaned = _sanitize_vod(vod)
            if cleaned is not None:
                result_list.append(cleaned)
        return {"list": result_list}

    def _error_detail(self, message):
        return {
            "vod_id": "error", "vod_name": "详情加载失败", "vod_pic": "",
            "vod_remarks": message, "vod_year": "", "vod_area": "", "vod_type": "",
            "vod_content": message, "vod_play_from": "默认线路", "vod_play_url": "",
        }

    def playerContent(self, *args):
        # 兼容 (flag, id, vipFlags) 和 (flag, id)
        flag = args[0] if len(args) > 0 else ""
        play_url = args[1] if len(args) > 1 else ""
        play_url = str(play_url or "")
        if play_url.startswith("error:"):
            return {"parse": 0, "jx": 0, "playUrl": "", "url": "", "header": {}, "msg": play_url[6:]}
        if not play_url:
            return {"parse": 0, "jx": 0, "playUrl": "", "url": "", "header": {}, "msg": "空播放地址"}
        # detailContent 已直接放入 m3u8 真实地址，无需再请求
        real_url = play_url
        if not real_url.startswith("http"):
            real_url = urljoin(self.host + "/", real_url)
        # 铁律·广告拦截：m3u8地址走本地代理清洗（壳支持getProxyUrl时生效，不支持则直连）
        proxy_url = self._proxy_m3u8_url(real_url, self.rawSite + "/")
        # 铁律15：防盗链双Header必须，Referer/Origin用原始站点rawSite
        return {
            "parse": 0, "jx": 0, "playUrl": "", "url": proxy_url,
            "header": {
                "User-Agent": PLAYER_UA,
                "Referer": self.rawSite + "/",
                "Origin": self.rawSite,
            },
            "format": "application/x-mpegURL", "contentType": "application/x-mpegURL",
        }

    # ==================== m3u8广告清洗 + 本地代理 ====================

    def _proxy_m3u8_url(self, url, referer=''):
        try:
            if hasattr(self, 'getProxyUrl'):
                return self.getProxyUrl() + '&type=m3u8&url=' + quote(url, safe='') + '&referer=' + quote(referer or self.rawSite, safe='')
        except Exception:
            pass
        return url

    def localProxy(self, params):
        try:
            if not isinstance(params, dict):
                params = {}
            do = params.get('type') or params.get('action') or params.get('do')
            url = params.get('url', '')
            if do not in ['m3u8', 'py'] and not url:
                return [404, "text/plain", "not found"]
            referer = params.get('referer', '') or self.rawSite
            if isinstance(url, list):
                url = url[0]
            if isinstance(referer, list):
                referer = referer[0]
            url = unquote(str(url))
            referer = unquote(str(referer))
            text = self._get_m3u8_content(url, referer)
            if not text:
                return [502, "text/plain", "m3u8 download failed"]
            try:
                from m3u8_cleaner import M3U8Cleaner
                _cleaner = M3U8Cleaner(raw_site=referer or self.rawSite)
                cleaned = _cleaner.clean(text, url, referer)
            except Exception:
                cleaned = self._clean_m3u8(text, url, referer)
            return [200, "application/vnd.apple.mpegurl", cleaned]
        except Exception as e:
            return [500, "text/plain", "proxy error: %s" % e]

    def _get_m3u8_content(self, url, referer):
        try:
            headers = {
                'User-Agent': PLAYER_UA,
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': referer,
                'Origin': self.rawSite,
                'Connection': 'keep-alive',
            }
            resp = self.session.get(url, headers=headers, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                return resp.text
            return None
        except Exception:
            return None

    def _is_ad_segment(self, uri, dur=0, prev_tags=None):
        u = (uri or '').strip().lower()
        if not u:
            return False
        ad_words = [
            'advertisement', 'advertise', 'advert', 'commercial', 'sponsor', 'sponsorship',
            'preroll', 'pre-roll', 'pre_roll', 'midroll', 'mid-roll', 'postroll', 'post-roll',
            'banner', 'banners', 'popup', 'pop-up', 'interstitial', 'overlay', 'splash',
            'bumper', 'stinger', 'vast', 'vpaid', 'vmap',
            'doubleclick', 'googleads', 'googlesyndication', 'googletag', 'adsense', 'admob',
            'adx', 'adnetwork', 'adserving', 'ad-serving', 'adserver', 'ad-server',
            'inmobi', 'unityads', 'applovin', 'ironsource', 'vungle', 'chartboost', 'tapjoy',
            'mintegral', 'pangle', 'bytedance', 'tiktokads', 'kuaishou', 'ks-ad',
            'tracking', 'tracker', 'beacon', 'pixel', 'analytics', 'statistic',
            'leaderboard', 'skyscraper', 'rectangle', 'filler',
            '广告', '片头', '片尾', '贴片', '赞助商', '赞助', '推广', '硬广',
            '前贴', '中插', '后贴', '角标', '广告位', '广告片', '广告段', '广告视频',
            '广告素材', '弹窗', '悬浮', '开屏', '插屏', '激励视频', '激励广告',
            'guanggao', 'ggao', 'ggvideo', 'ggmedia',
            '/ad/', '/ads/', '/adv/', '/adver/', '/gg/', '/gga/', '/ggb/', '/ggc/', '/ggd/',
            '_ad.', '.ad/', '_ads.', '_adv.', '_gg.', 'gg_', '_gg', '/gg', 'gg.',
            '/ad_', '/ads_', '/adv_', '/sponsor/', '/banner/', '/promo/', '/commercial/',
            '/preroll/', '/midroll/', '/postroll/', '/popup/', '/interstitial/', '/overlay/',
            '/splash/', '/bumper/', '/vast/', '/vpaid/', '/adnetwork/', '/adserving/',
            '/doubleclick/', '/googleads/', '/googlesyndication/', '/adsense/', '/admob/',
            '/tracking/', '/tracker/', '/beacon/', '/pixel/', '/analytics/',
        ]
        if any(w in u for w in ad_words):
            return True
        try:
            if 0 < float(dur) <= 1.2:
                return True
        except Exception:
            pass
        return False

    def _parse_m3u8_segments(self, text):
        lines = [x.strip() for x in (text or '').replace('\r', '').split('\n') if x.strip()]
        header, segments, tail = [], [], []
        pending_tags = []
        media_sequence = 0
        target_duration = 0
        started = False
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith('#EXT-X-MEDIA-SEQUENCE'):
                try:
                    media_sequence = int(line.split(':', 1)[1])
                except Exception:
                    pass
                if not started:
                    header.append(line)
                else:
                    pending_tags.append(line)
            elif line.startswith('#EXT-X-TARGETDURATION'):
                try:
                    target_duration = float(line.split(':', 1)[1])
                except Exception:
                    pass
                if not started:
                    header.append(line)
                else:
                    pending_tags.append(line)
            elif line.startswith('#EXTINF'):
                started = True
                dur = target_duration or 3.0
                m = re.search(r'#EXTINF:\s*([\d.]+)', line)
                if m:
                    try:
                        dur = float(m.group(1))
                    except Exception:
                        pass
                tags = pending_tags + [line]
                pending_tags = []
                uri = ''
                j = i + 1
                while j < len(lines):
                    if lines[j].startswith('#'):
                        tags.append(lines[j])
                        j += 1
                        continue
                    uri = lines[j]
                    break
                if uri:
                    segments.append({'tags': tags, 'uri': uri, 'dur': dur})
                    i = j
                else:
                    tail.extend(tags)
            elif line.startswith('#EXT-X-ENDLIST'):
                tail.append(line)
            elif line.startswith('#'):
                if started:
                    pending_tags.append(line)
                else:
                    header.append(line)
            else:
                started = True
                dur = target_duration or 3.0
                segments.append({'tags': pending_tags, 'uri': line, 'dur': dur})
                pending_tags = []
            i += 1
        return header, segments, tail, media_sequence, target_duration

    def _segment_host_key(self, uri, base_url):
        try:
            full = urljoin(base_url, uri)
            p = urlsplit(full)
            path = re.sub(r'/[^/]*$', '/', p.path or '/')
            return (p.netloc.lower(), path.lower())
        except Exception:
            return ('', '')

    def _main_path_marker(self, m3u8_url):
        try:
            p = urlsplit(m3u8_url).path
            m = re.search(r'(/\d{8}/[^/]+/\d+kb/hls/)', p)
            if m:
                return m.group(1).lower()
            m = re.search(r'(/\d{8}/[^/]+/)', p)
            if m:
                return m.group(1).lower()
        except Exception:
            pass
        return ''

    def _clean_m3u8(self, m3u8_text, m3u8_url='', referer='', skip_seconds=25):
        text = (m3u8_text or '').replace('\r', '')
        if '#EXT-X-STREAM-INF' in text:
            out = []
            last_stream = False
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                if line.startswith('#'):
                    out.append(line)
                    last_stream = line.startswith('#EXT-X-STREAM-INF')
                else:
                    abs_url = urljoin(m3u8_url, line)
                    if last_stream or '.m3u8' in line.lower():
                        out.append(self._proxy_m3u8_url(abs_url, referer or self.rawSite))
                    else:
                        out.append(abs_url)
                    last_stream = False
            return '\n'.join(out) + '\n'

        header, segments, tail, media_sequence, target_duration = self._parse_m3u8_segments(text)
        if not segments:
            return text

        marker = self._main_path_marker(m3u8_url)
        stat = {}
        for seg in segments:
            key = self._segment_host_key(seg['uri'], m3u8_url)
            stat[key] = stat.get(key, 0.0) + float(seg.get('dur') or 0)
        main_key = max(stat.items(), key=lambda x: x[1])[0] if stat else ('', '')
        total_dur = sum(stat.values()) or 0
        main_dur = stat.get(main_key, 0)

        cleaned = []
        removed = 0
        for idx, seg in enumerate(segments):
            key = self._segment_host_key(seg['uri'], m3u8_url)
            is_front = idx < 12
            abs_uri = urljoin(m3u8_url, seg.get('uri', ''))
            is_ad = self._is_ad_segment(seg['uri'], seg.get('dur'), seg.get('tags'))
            if marker and marker not in urlsplit(abs_uri).path.lower():
                is_ad = True
            tags_text = '\n'.join(seg.get('tags') or []).upper()
            if is_front and 'METHOD=NONE' in tags_text and marker and marker not in urlsplit(abs_uri).path.lower():
                is_ad = True
            if (not is_ad) and is_front and total_dur > 0 and main_dur >= total_dur * 0.6:
                if key != main_key and stat.get(key, 0) <= 90:
                    is_ad = True
            if is_ad:
                removed += 1
                continue
            seg['_idx'] = idx
            cleaned.append(seg)

        if removed == 0 and len(segments) > 4:
            acc = 0.0
            cut = 0
            for idx, seg in enumerate(segments[:12]):
                key = self._segment_host_key(seg['uri'], m3u8_url)
                if key == main_key and acc >= 3:
                    break
                acc += float(seg.get('dur') or target_duration or 3)
                cut = idx + 1
                if acc >= skip_seconds:
                    break
            if cut > 0 and cut < len(segments):
                first_key = self._segment_host_key(segments[0]['uri'], m3u8_url)
                if first_key != main_key:
                    cleaned = segments[cut:]
                    removed = cut

        if not cleaned:
            cleaned = segments
            removed = 0

        new_lines = []
        has_m3u = False
        for line in header:
            if line.startswith('#EXTM3U'):
                has_m3u = True
            if line.startswith('#EXT-X-MEDIA-SEQUENCE') or line.startswith('#EXT-X-START'):
                continue
            if line.startswith('#EXT-X-KEY') and 'METHOD=NONE' in line.upper() and removed > 0:
                continue
            new_lines.append(line)
        if not has_m3u:
            new_lines.insert(0, '#EXTM3U')
        first_idx = cleaned[0].get('_idx', removed) if cleaned else removed
        new_lines.append('#EXT-X-MEDIA-SEQUENCE:%d' % (media_sequence + first_idx))

        for seg in cleaned:
            for tag in seg.get('tags') or []:
                if tag.startswith('#EXT-X-KEY') or tag.startswith('#EXT-X-MAP'):
                    def _fix_uri(m):
                        return 'URI="' + urljoin(m3u8_url, m.group(1)) + '"'
                    tag = re.sub(r'URI="([^"]+)"', _fix_uri, tag)
                new_lines.append(tag)
            new_lines.append(urljoin(m3u8_url, seg.get('uri', '')))
        if tail:
            for line in tail:
                if line.startswith('#EXT-X-ENDLIST'):
                    new_lines.append(line)
        elif '#EXT-X-ENDLIST' in text:
            new_lines.append('#EXT-X-ENDLIST')
        return '\n'.join(new_lines) + '\n'
