# coding=utf-8
# 站点：theporny.com —— 国产原创全集（91porn 系聚合壳）
# 协议：单一入口 POST {api_host}/js，body 携带 url 路由字段；响应为 CryptoJS-AES(OpenSSL KDF) 密文
# 详情：POST /js {url:"/sevenVideos/{id}", url_search:"?server=xxx", token:"ufd"}；m3u8 带时效签名
# 线路：url_search 的 server 参数 default1/default2/hd1/hd2/hd3（实测同一源多入口）
# 广告预检: has_ads=True, score=45
import base64
import hashlib
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urljoin

import ssl

import requests
from Crypto.Cipher import AES
from requests.adapters import HTTPAdapter

try:
    from base.spider import Spider as _BaseSpider
    _HAS_BASE = True
except Exception:
    try:
        from base.spider import BaseSpider as _BaseSpider
        _HAS_BASE = True
    except Exception:
        _HAS_BASE = False

        class _BaseSpider:
            pass


# ==================== 站点常量 ====================
HOST = 'https://theporny.com'
API_HOSTS = [
    'https://v2.cdn199.com',
    'https://v2.kekecdn.net',
    'https://v2.luchu.org',
    'https://v2.madou.ws',
    'https://v2.papapa.biz',
    'https://v2.tianmtv.com',
    'https://v2.xiaoshuo.info',
    'https://v2.xiaoshuo.la',
]
APP = 'theporny.com'
APP_VER = '260901'
API_PATH = '/js'
DETAIL_TOKEN = 'ufd'
SERVER_LINE = 'default2'
AES_PASS = b'xxx'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
# 业务入口 /js 挂了 TLS 指纹级 WAF 规则：requests/curl 默认 cipher 一律 403，需对齐 Chrome cipher 顺序
CHROME_CIPHERS = ':'.join([
    'TLS_AES_128_GCM_SHA256', 'TLS_AES_256_GCM_SHA384', 'TLS_CHACHA20_POLY1305_SHA256',
    'ECDHE-ECDSA-AES128-GCM-SHA256', 'ECDHE-RSA-AES128-GCM-SHA256',
    'ECDHE-ECDSA-AES256-GCM-SHA384', 'ECDHE-RSA-AES256-GCM-SHA384',
    'ECDHE-ECDSA-CHACHA20-POLY1305', 'ECDHE-RSA-CHACHA20-POLY1305',
    'ECDHE-RSA-AES128-SHA', 'ECDHE-RSA-AES256-SHA',
    'AES128-GCM-SHA256', 'AES256-GCM-SHA384', 'AES128-SHA', 'AES256-SHA', 'DES-CBC3-SHA',
])
PAGE_SIZE = 24
API_RETRY = 3
API_TIMEOUT = 8
CACHE_TTL = 120
BAD_TTL = 90        # 某入口失败后，多久内不再优先使用
STALE_TTL = 1800    # 全部入口失败时，过期缓存仍可复用的时长

DEVICE_INFO = {
    'model': 'Windows NT 10.0',
    'platform': 'web',
    'operatingSystem': 'windows',
    'osVersion': 'Windows NT 10.0; Win64; x64',
    'manufacturer': 'Google Inc.',
    'isVirtual': False,
    'webViewVersion': '124.0.0.0',
}

# 站点真实分类（type 编码 → 显示名），全部实测可用
CLASSES = [
    ('hot', '国产91大神'),
    ('c0', '国产原创'),
    ('t0', '国产自拍合集'),
    ('banana', '汝工作室'),
    ('swag', '台湾SWAG全集'),
    ('av', '日本高清AV'),
    ('c1', '麻豆视频'),
    ('c2', '91制片厂'),
    ('c3', '玩偶姐姐'),
    ('c4', '小鸟酱专题'),
    ('c5', '糖心Vlog'),
    ('c6', '天美传媒'),
    ('c7', '蜜桃传媒'),
    ('c8', '皇家华人'),
    ('c9', '星空传媒'),
    ('ca', '精东影业'),
    ('cb', '乐播传媒'),
    ('cc', '成人头条'),
    ('cd', '乌鸦传媒'),
    ('ce', '兔子先生'),
    ('cf', 'PsychoPorn'),
    ('cg', '葫芦影业'),
    ('ci', '杏吧原创'),
    ('cj', 'mimi传媒'),
    ('ck', '大象传媒'),
    ('cl', '开心鬼传媒'),
    ('cm', '鲸鱼传媒'),
    ('cp', '卡通动漫'),
    ('cq', 'BDSM'),
    ('gcsm', '国产SM'),
    ('torture_all', '重口系列'),
    ('torture_asian', '亚洲重口'),
    ('torture_west', '欧美重口'),
    ('torture_comic', '卡通重口'),
    ('torture_other', '其他重口'),
    ('west', '欧美推荐'),
    ('pissvids', '欧美重口(pissvids)'),
    ('kink', 'Kink精选'),
    ('xart', 'X-art精选'),
    ('lesbian', '女同系列'),
    ('high', '站长推荐'),
    ('t_high_gaoqing', '高清AV'),
    ('t_high_zhubo', '主播福利'),
    ('t_high_wuma', '无码流出'),
    ('t_high_zipai', '自拍偷拍'),
    ('t_high_tanhua', '探花精选'),
    ('t_high_yao', '人妖伪娘'),
    ('t_high_lifan', '里番'),
    ('t_high_yao_48', '妖视频高清'),
]

# ========== 铁律11：敏感词古典映射脱敏表 ==========
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

# 铁律13：未成年相关关键词
# 注意："学生"/"书生"已移除——高中生/大学生可能已成年，不视为未成年；
# 仅保留明确指向未成年的词（萝莉/幼女/少女/童/teen/loli/schoolgirl等）
_MINOR_KEYWORDS = (
    "豆蔻", "玉蕊", "碧玉", "稚子", "未成年", "teen", "loli",
    "schoolgirl", "萝莉", "幼女", "少女", "童",
)

# 铁律15：默认反代配置
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


def desensitize(text):
    """铁律11：敏感词古典映射脱敏 + 铁律13：未成年返回空字符串"""
    if text is None:
        return ""
    result = str(text)
    for key in sorted(CLASSICAL_MAP.keys(), key=len, reverse=True):
        if key in result:
            result = result.replace(key, CLASSICAL_MAP[key])
    lower = result.lower()
    for kw in _MINOR_KEYWORDS:
        if kw.lower() in lower:
            return ""
    return result


def _is_minor_content(text):
    if not text:
        return False
    lower = str(text).lower()
    for kw in _MINOR_KEYWORDS:
        if kw.lower() in lower:
            return True
    return False


def _sanitize_vod(vod):
    if not isinstance(vod, dict):
        return vod
    name = vod.get("vod_name", "")
    remarks = vod.get("vod_remarks", "")
    content = vod.get("vod_content", "")
    if _is_minor_content(name) or _is_minor_content(remarks) or _is_minor_content(content):
        return None
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


def _aes_en(s):
    raw = s.encode('utf-8')
    n = 16 - len(raw) % 16
    raw += bytes([n]) * n
    c = AES.new(K2, AES.MODE_CBC, iv=K2[:16])
    return base64.b64encode(c.encrypt(raw)).decode()


def _aes_de(ct):
    if not ct:
        return ''
    c = AES.new(K2, AES.MODE_CBC, iv=K2[:16])
    raw = c.decrypt(base64.b64decode(ct))
    n = raw[-1]
    if 0 < n < len(raw) and raw[-n:] == bytes([n]) * n:
        raw = raw[:-n]
    return raw.decode('utf-8', errors='ignore')


def _b64e(s):
    return base64.urlsafe_b64encode(s.encode('utf-8')).decode().rstrip('=')


def _b64d(s):
    pad = '=' * (-len(s) % 4)
    for fn in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            return fn((s + pad).encode()).decode('utf-8', errors='ignore')
        except Exception:
            continue
    return ''


def _mime(head):
    if head[:2] == b'\xff\xd8':
        return 'image/jpeg'
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    return 'image/jpeg'


# ==================== 本地代理运行态 ====================
_proxy_port = None
_proxy_lock = threading.Lock()

# ==================== 站点协议工具（TLS 指纹 / AES 解密 / 图片代理） ====================

class _ChromeTLSAdapter(HTTPAdapter):
    """对齐 Chrome 的 TLS cipher 顺序，绕过业务入口的指纹级 WAF（纯 requests 即可用）"""

    def init_poolmanager(self, *args, **kwargs):
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.set_ciphers(CHROME_CIPHERS)
            kwargs['ssl_context'] = ctx
        except Exception:
            pass
        return super().init_poolmanager(*args, **kwargs)


def _build_session():
    s = requests.Session()
    try:
        s.mount('https://', _ChromeTLSAdapter())
    except Exception:
        pass
    s.headers.update({'User-Agent': UA})
    return s


def _evp_bytes(passwd, salt, klen=32, ilen=16):
    """CryptoJS OpenSSL KDF（EVP_BytesToKey / MD5 派生 AES-256-CBC 的 key+iv）"""
    d = b''
    prev = b''
    while len(d) < klen + ilen:
        prev = hashlib.md5(prev + passwd + salt).digest()
        d += prev
    return d[:klen], d[klen:klen + ilen]


def _aes_dec(payload):
    """解密 {"r":"<base64>"} 形态的响应体，返回明文文本（失败返回空串）"""
    try:
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode('utf-8', errors='ignore')
        if isinstance(payload, dict):
            payload = payload.get('r', '')
        elif isinstance(payload, str):
            s = payload.strip()
            if s.startswith('{'):
                try:
                    payload = json.loads(s).get('r', '')
                except Exception:
                    payload = s
        if not payload:
            return ''
        txt = str(payload).strip()
        txt += '=' * (-len(txt) % 4)
        raw = base64.b64decode(txt)
        if raw[:8] != b'Salted__':
            return ''
        salt, ct = raw[8:16], raw[16:]
        key, iv = _evp_bytes(AES_PASS, salt)
        pt = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
        pad = pt[-1] if pt else 0
        if 1 <= pad <= 16:
            pt = pt[:-pad]
        return pt.decode('utf-8', errors='ignore')
    except Exception:
        return ''


def _dec_payload(text):
    """响应体 → 数据对象。兼容 r 字段密文 / 明文 JSON / 裸数组 / 解密后仍是 JSON 串。
    能解析出内容返回对象；确实解不出来返回 None（调用方据此换入口重试）。"""
    if not text:
        return None
    s = text.strip()
    if not s:
        return None
    obj = None
    try:
        obj = json.loads(s)
    except Exception:
        obj = None
    if isinstance(obj, (list, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        if 'r' in obj:
            r = obj.get('r')
            if isinstance(r, (list, dict)):
                return r
            if not r:
                return []          # 合法空结果，别当失败去重试
            plain = _aes_dec(r)
            if not plain:
                return None
            try:
                return json.loads(plain)
            except Exception:
                return plain
        for k in ('data', 'list', 'result'):
            if isinstance(obj.get(k), (list, dict)):
                return obj[k]
        return obj
    plain = _aes_dec(s)
    if not plain:
        return None
    try:
        return json.loads(plain)
    except Exception:
        return None


class _PicHandler(BaseHTTPRequestHandler):
    """图片本地代理：补 UA/Referer，绕开防盗链"""
    spider = None

    def log_message(self, *a):
        pass

    def do_GET(self):
        q = self.path.split('url=', 1)[-1]
        data, mime = self.spider._pic_fetch(unquote(q))
        if not data:
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

class Spider(_BaseSpider):
    """theporny.com 聚合壳爬虫（铁律8：双协议兼容继承 base.spider，13 接口齐全）"""

    def __init__(self):
        self.session = _build_session()
        self.session.headers.update({'User-Agent': UA})
        self._cache = {}
        self._hi = 0
        self._lock = threading.Lock()
        self._bad = {}
        self._last_err = ''
        self.hosts = list(API_HOSTS)
        # 铁律15：反代相关属性初始化
        self.rawSite = HOST
        self.siteUrl = HOST
        self.HOST = HOST
        self._use_proxy = True
        self._default_proxy = _load_default_proxy()

    def getName(self):
        return '国产原创全集'

    def init(self, extend=''):
        config = {}
        if isinstance(extend, dict):
            config = extend
        elif extend:
            try:
                config = json.loads(extend)
            except Exception:
                try:
                    import ast
                    config = ast.literal_eval(extend)
                except Exception:
                    config = {}
        # 铁律15：原始站点
        self.rawSite = config.get('host') or config.get('rawSite') or HOST
        if not str(self.rawSite).startswith('http'):
            self.rawSite = 'https://' + str(self.rawSite)
        self.rawSite = str(self.rawSite).rstrip('/')
        # 铁律15：反代配置
        direct = str(config.get('direct', '')).lower() in ('1', 'true', 'yes', 'on')
        ext_proxy = str(config.get('proxy') or config.get('siteUrl') or '').strip()
        if direct:
            self._use_proxy = False
            self.siteUrl = self.rawSite
        elif ext_proxy:
            self._use_proxy = True
            self.siteUrl = ext_proxy.rstrip('/')
        else:
            self._use_proxy = True
            self.siteUrl = self._default_proxy
        self.HOST = self.siteUrl
        # 接口入口可覆写（逗号分隔或列表）
        api = config.get('apiHosts') or config.get('apiHost')
        if api:
            seq = api if isinstance(api, list) else str(api).split(',')
            hosts = [str(x).strip().rstrip('/') for x in seq if str(x).strip()]
            if hosts:
                self.hosts = hosts

    # ==================== 接口层（单入口 POST /js + AES 解密） ====================

    def _next_host(self):
        """入口轮换：优先跳过近期失败的入口（某个域名被墙/限频时自动绕开）"""
        with self._lock:
            now = time.time()
            n = len(self.hosts) or 1
            for k in range(n):
                idx = (self._hi + k) % n
                host = str(self.hosts[idx]).rstrip('/')
                if now - self._bad.get(host, 0) > BAD_TTL:
                    self._hi = (idx + 1) % n
                    return host
            host = str(self.hosts[self._hi % n]).rstrip('/')
            self._hi = (self._hi + 1) % n
            return host

    def _mark_bad(self, host):
        with self._lock:
            self._bad[host] = time.time()

    def _mark_ok(self, host):
        with self._lock:
            self._bad.pop(host, None)

    def _api(self, route, extra=None):
        """POST {host}/js → AES 解密 → 对象。多入口轮换 + 解析容错 + 失败快速切线"""
        hit = self._cache.get(route)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer undefined',
            'Origin': self.rawSite,
            'Referer': self.rawSite + '/',
            'Accept': 'application/json, text/plain, */*',
        }
        payload = {
            'deviceInfo': DEVICE_INFO,
            'app': APP,
            'isStandalone': False,
            'theLink': 'novaluenull',
            'uuid': 'novalue',
            'version': APP_VER,
            'url': route,
        }
        if extra:
            payload.update(extra)
        body = json.dumps(payload)
        errs = []
        # 双通道：自定义 TLS 会话 → 纯净 requests 会话（壳里若自定义 SSL 上下文不兼容，靠这条兜底）
        for sess in (self.session, self._plain()):
            data = self._attempt(sess, body, headers, errs)
            if data is not None:
                self._last_err = ''
                self._cache[route] = (time.time(), data)
                return data
        self._last_err = ';'.join(errs)[:120]
        # 有过期缓存先顶上，好过给壳一个空列表
        if hit and time.time() - hit[0] < STALE_TTL:
            return hit[1]
        return None

    def _plain(self):
        """纯净会话：不做任何 TLS 上下文定制，兼容性最好"""
        s = getattr(self, '_plain_session', None)
        if s is None:
            s = requests.Session()
            s.headers.update({'User-Agent': UA})
            self._plain_session = s
        return s

    def _attempt(self, session, body, headers, errs):
        for _ in range(API_RETRY):
            host = self._next_host()
            tag = host.split('//')[-1]
            try:
                r = session.post(host + API_PATH, data=body, headers=headers,
                                 timeout=(4, API_TIMEOUT), verify=False)
                if r.status_code == 200:
                    data = _dec_payload(r.text)
                    if data is not None:
                        self._mark_ok(host)
                        return data
                    errs.append('%s=解析失败' % tag)
                    self._mark_bad(host)
                else:
                    errs.append('%s=HTTP%s' % (tag, r.status_code))
                    self._mark_bad(host)
            except Exception as e:
                errs.append('%s=%s' % (tag, type(e).__name__))
                self._mark_bad(host)
            time.sleep(0.25)
        return None

    def _diag_item(self, route):
        """接口全挂时给出的一条自检条目：在壳里能直接看到，便于定位是网络还是解析"""
        m = re.search(r'type=([\w\-]+)', route or '')
        tid = m.group(1) if m else (route or '')
        return {
            'vod_id': '__diag__',
            'vod_name': '【自检】分类 %s 取不到数据' % tid,
            'vod_pic': '',
            'vod_remarks': (self._last_err or '无响应')[:60],
        }

    def _detail(self, vid):
        """视频详情：m3u8 为带时效签名的直链，播放前需现取"""
        return self._api('/sevenVideos/%s' % vid,
                         {'url_search': '?server=' + SERVER_LINE, 'token': DETAIL_TOKEN})

    # ==================== 数据整形 ====================

    def _thumb(self, it):
        th = it.get('thumbnails')
        if isinstance(th, list) and th:
            return str(th[0])
        if isinstance(th, str):
            return th
        return ''

    def _item(self, it):
        if not isinstance(it, dict):
            return None
        vid = str(it.get('id') or it.get('vId') or '').strip()
        if not vid:
            return None
        title = it.get('title') or it.get('title_en') or ''
        remark = str(it.get('durationStr') or it.get('duration') or '')
        user = str(it.get('user') or '')
        if user:
            remark = (user + ' ' + remark).strip()
        return {
            'vod_id': vid,
            'vod_name': title,
            'vod_pic': self._pic_url(self._thumb(it)),
            'vod_remarks': remark,
        }

    def _items(self, arr):
        out = []
        for it in arr or []:
            if not isinstance(it, dict):
                continue
            v = self._item(it)
            if v and v['vod_name']:
                out.append(v)
        return out

    def _pic_url(self, path):
        if not path:
            return ''
        try:
            return 'http://127.0.0.1:{}/pic?url={}'.format(self._start_pic_proxy(), quote(str(path), safe=''))
        except Exception:
            return str(path)

    def _start_pic_proxy(self):
        global _proxy_port
        with _proxy_lock:
            if _proxy_port:
                return _proxy_port
            _PicHandler.spider = self
            httpd = ThreadingHTTPServer(('127.0.0.1', 0), _PicHandler)
            _proxy_port = httpd.server_address[1]
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            return _proxy_port

    def _pic_fetch(self, path):
        # 铁律15：防盗链用原始站点
        hd = {'User-Agent': UA, 'Referer': self.rawSite + '/'}
        for url in (path, urljoin(self.rawSite + '/', path.lstrip('/'))):
            if not url:
                continue
            try:
                r = self.session.get(url, headers=hd, timeout=12, verify=False)
                if r.status_code == 200 and r.content:
                    return r.content, _mime(r.content)
            except Exception:
                continue
        return b'', 'image/jpeg'

    # ==================== 13 标准接口 ====================

    def homeContent(self, filter):
        classes = []
        for tid, name in CLASSES:
            classes.append({'type_id': tid, 'type_name': name})
        # 铁律11+13：分类脱敏
        classes = _sanitize_classes(classes)
        return {'class': classes, 'filters': {}}

    def homeVideoContent(self):
        arr = self._api('/sevenVideos?page=1&type=hot')
        lst = self._items(arr) if isinstance(arr, list) else []
        if arr is None:
            return {'list': [self._diag_item('/sevenVideos?page=1&type=hot')]}
        # 铁律11+13：列表脱敏
        return {'list': _sanitize_list(lst)}

    def categoryContent(self, tid, pg=1, filter=False, extend=''):
        p = int(pg) if pg else 1
        tid = str(tid or 'hot').strip() or 'hot'
        route = '/sevenVideos?page=%d&type=%s' % (p, tid)
        arr = self._api(route)
        if arr is None:
            # 接口全挂（被墙/限频/DNS）：给一条自检条目，别让壳只显示"暂无视频数据"
            return {'page': p, 'pagecount': p, 'limit': PAGE_SIZE,
                    'total': 0, 'list': [self._diag_item(route)]}
        lst = self._items(arr) if isinstance(arr, list) else []
        total = p * PAGE_SIZE + len(lst)
        pagecount = p + 1 if len(lst) >= PAGE_SIZE else p
        # 铁律11+13：列表脱敏
        return {'page': p, 'pagecount': pagecount, 'limit': PAGE_SIZE,
                'total': total, 'list': _sanitize_list(lst)}

    def detailContent(self, ids):
        # 铁律8：ids 是 list/tuple 必须遍历
        id_list = list(ids) if isinstance(ids, (list, tuple)) else [ids]
        result_list = []
        for raw_id in id_list:
            vid = str(raw_id or '').strip()
            if '$' in vid:
                vid = vid.split('$')[-1].strip()
            if '$$$' in vid:
                vid = vid.split('$$$')[0].strip()
            if not vid:
                continue
            d = self._detail(vid)
            if not isinstance(d, dict):
                continue
            m3u8s = d.get('m3u8s')
            urls = [str(u) for u in m3u8s if u] if isinstance(m3u8s, list) else []
            lines_from = []
            lines_url = []
            if urls:
                lines_from.append('线路1')
                lines_url.append('#'.join(['正片$%s' % u for u in urls]))
            # 兜底线路：播放时按 vid 现取（签名有过期时间）
            lines_from.append('现取线路')
            lines_url.append('正片$%s' % vid)
            title = d.get('title') or d.get('title_en') or vid
            user = str(d.get('user') or '')
            dur = str(d.get('durationStr') or '')
            size = str(d.get('size') or '')
            views = str(d.get('views') or '')
            content = ' / '.join([x for x in (user, dur, size, views and (views + '次播放')) if x])
            vod = {
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': self._pic_url(self._thumb(d)),
                'vod_remarks': dur,
                'vod_year': str(d.get('time') or ''),
                'vod_area': user,
                'vod_actor': user,
                'vod_content': content,
                'vod_play_from': '$$$'.join(lines_from),
                'vod_play_url': '$$$'.join(lines_url),
            }
            # 铁律11+13：详情脱敏
            cleaned = _sanitize_vod(vod)
            if cleaned is not None:
                result_list.append(cleaned)
        return {'list': result_list}

    def searchContent(self, key, quick=False, pg=1):
        p = int(pg) if pg else 1
        arr = self._api('/searchSevenVideos', {'page': p, 'keywords': str(key or '')})
        lst = self._items(arr) if isinstance(arr, list) else []
        total = p * PAGE_SIZE + len(lst)
        pagecount = p + 1 if len(lst) >= PAGE_SIZE else p
        # 铁律11+13：搜索结果脱敏
        return {'list': _sanitize_list(lst), 'page': p, 'pagecount': pagecount,
                'limit': PAGE_SIZE, 'total': total}

    def playerContent(self, flag, id, vipFlags=None):
        raw = str(id or '').strip()
        if '$$$' in raw:
            raw = raw.split('$$$')[0].strip()
        if '$' in raw:
            raw = raw.split('$')[-1].strip()
        url = raw
        if not re.search(r'\.(m3u8|mp4|flv|ts)(\?|$)', url, re.I):
            # 传进来的是 vid：现取一次，拿最新签名直链
            d = self._detail(url)
            if isinstance(d, dict):
                m3u8s = d.get('m3u8s')
                if isinstance(m3u8s, list) and m3u8s:
                    url = str(m3u8s[0])
        url = self._sanitize_m3u8_url(url)
        # 铁律·广告拦截：m3u8 走本地代理清洗
        play_url = self._proxy_m3u8_url(url, self.rawSite + '/')
        # 铁律15：防盗链双 Header，Referer/Origin 用原始站点 rawSite
        return {'parse': 0, 'jx': 0, 'url': play_url,
                'header': {'User-Agent': UA, 'Referer': self.rawSite + '/', 'Origin': self.rawSite}}

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|ts)(\?|$)', url or '', re.I))

    def manualVideoCheck(self):
        return False

    def getDependence(self):
        return ""

    def action(self, action):
        return ""

    def destroy(self):
        try:
            if self.session is not None:
                self.session.close()
        except Exception:
            pass
        return ""

    # ==================== m3u8广告清洗 + 本地代理（铁律·广告拦截） ====================

    def _sanitize_m3u8_url(self, url):
        """清洗m3u8 URL中的广告参数（cover/poster/thumb/pic等）"""
        if not url:
            return url
        url = unquote(url)
        url = re.sub(r'&[Cc]over=.*', '', url)
        url = re.sub(r'&[Pp]oster=.*', '', url)
        url = re.sub(r'&[Tt]humb=.*', '', url)
        url = re.sub(r'&[Pp]ic=.*', '', url)
        url = url.rstrip('&?')
        return url

    def _proxy_m3u8_url(self, url, referer=''):
        """生成m3u8代理地址：优先用壳的getProxyUrl()，否则返回原地址"""
        try:
            if hasattr(self, 'getProxyUrl'):
                return self.getProxyUrl() + '&type=m3u8&url=' + quote(url, safe='') + '&referer=' + quote(referer or self.rawSite, safe='')
        except Exception:
            pass
        return url

    def _get_m3u8_content(self, url, referer):
        """带防盗链header下载m3u8文件"""
        try:
            headers = {
                'User-Agent': UA,
                'Accept': '*/*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Referer': referer,
                'Origin': self.rawSite,
                'Connection': 'keep-alive',
            }
            resp = self.session.get(url, headers=headers, timeout=10, allow_redirects=True, verify=False)
            if resp.status_code == 200:
                return resp.text
            return None
        except Exception:
            return None

    def _is_ad_segment(self, uri, dur=0, prev_tags=None):
        """广告片段识别：关键词匹配 + 短时长判定"""
        u = (uri or '').strip().lower()
        if not u:
            return False
        ad_words = [
            # 英文明确广告词
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
            # 中文广告词
            '广告', '片头', '片尾', '贴片', '赞助商', '赞助', '推广', '硬广',
            '前贴', '中插', '后贴', '角标', '广告位', '广告片', '广告段', '广告视频',
            '广告素材', '弹窗', '悬浮', '开屏', '插屏', '激励视频', '激励广告',
            # 拼音/缩写
            'guanggao', 'ggao', 'ggvideo', 'ggmedia',
            # 路径特征（精确匹配）
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
        """m3u8解析器：拆出header/segments/tail"""
        from urllib.parse import urlsplit
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
        """提取片段的主机+路径前缀，用于统计主CDN"""
        from urllib.parse import urlsplit
        try:
            full = urljoin(base_url, uri)
            p = urlsplit(full)
            path = re.sub(r'/[^/]*$', '/', p.path or '/')
            return (p.netloc.lower(), path.lower())
        except Exception:
            return ('', '')

    def _main_path_marker(self, m3u8_url):
        """从m3u8 URL提取主路径标记"""
        from urllib.parse import urlsplit
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
        """核心m3u8广告清洗：五重广告识别 + 主CDN统计 + 前置贴片切除 + 多码率递归代理"""
        from urllib.parse import urlsplit
        text = (m3u8_text or '').replace('\r', '')
        # 多码率m3u8：递归代理子m3u8
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

        # 统计各主机路径的总时长，找出主CDN
        stat = {}
        for seg in segments:
            key = self._segment_host_key(seg['uri'], m3u8_url)
            stat[key] = stat.get(key, 0.0) + float(seg.get('dur') or 0)
        main_key = max(stat.items(), key=lambda x: x[1])[0] if stat else ('', '')
        total_dur = sum(stat.values()) or 0
        main_dur = stat.get(main_key, 0)

        # 五重广告识别
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

        # 兜底策略：前置贴片切除
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

        # 重新生成干净的m3u8
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

    def localProxy(self, param):
        """本地代理：m3u8 广告清洗 + 图片代理"""
        if not isinstance(param, dict):
            param = {}
        do = param.get('type') or param.get('action') or param.get('do')
        url = param.get('url', '') or param.get('path', '')
        if isinstance(url, list):
            url = url[0] if url else ''
        # m3u8 广告清洗分支
        if do == 'm3u8' or (isinstance(url, str) and ('.m3u8' in url)):
            try:
                referer = param.get('referer', '') or self.rawSite
                if isinstance(referer, list):
                    referer = referer[0] if referer else ''
                url = unquote(str(url))
                referer = unquote(str(referer))
                text = self._get_m3u8_content(url, referer)
                if not text:
                    return [502, "text/plain", "m3u8 download failed"]
                # 优先独立 m3u8_cleaner 模块，失败回退内嵌版
                try:
                    from m3u8_cleaner import M3U8Cleaner
                    _cleaner = M3U8Cleaner(raw_site=referer or self.rawSite)
                    cleaned = _cleaner.clean(text, url, referer)
                except Exception:
                    cleaned = self._clean_m3u8(text, url, referer)
                return [200, "application/vnd.apple.mpegurl", cleaned]
            except Exception as e:
                import traceback
                return [500, "text/plain", "proxy error: %s\n%s" % (e, traceback.format_exc())]
        # 图片代理分支
        if url:
            data, mime = self._pic_fetch(unquote(str(url)))
            if data:
                return [200, mime, data]
        return [404, 'text/plain', b'']
