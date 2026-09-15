import json
import re
import os
import hashlib
import time
import base64
from urllib.parse import urlparse, parse_qs, quote, unquote, urljoin

for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
    os.environ.pop(k, None)

try:
    import requests as _req
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from base.spider import Spider as _Base
except ImportError:
    class _Base:
        def init(self, extend=""):
            pass

MINOR_KW = ['萝莉', '幼女', '少女', 'teen', 'loli', 'schoolgirl', '豆蔻', '玉蕊', '碧玉', '稚子']


def _is_minor(text):
    if not text:
        return False
    t = text.lower()
    return any(k.lower() in t for k in MINOR_KW)


class Spider(_Base):
    site_name = '傻傻视频'
    base_url = 'https://okgo88.com'
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

    categories = [
        {'type_id': '48', 'type_name': '中文字幕'},
        {'type_id': '13', 'type_name': '强奸乱伦'},
        {'type_id': '270', 'type_name': '日本无码'},
        {'type_id': '269', 'type_name': '日本有码'},
        {'type_id': '92', 'type_name': '制服诱惑'},
        {'type_id': '401', 'type_name': 'AV明星'},
        {'type_id': '259', 'type_name': '日韩无码'},
        {'type_id': '254', 'type_name': '无码专区'},
        {'type_id': '86', 'type_name': '动漫精品'},
        {'type_id': '438', 'type_name': '女优明星'},
        {'type_id': '93', 'type_name': '巨乳美乳'},
        {'type_id': '274', 'type_name': '成人动漫'},
        {'type_id': '22', 'type_name': '亚洲情色'},
        {'type_id': '105', 'type_name': '亚洲有码'},
        {'type_id': '367', 'type_name': '伦理三级'},
        {'type_id': '260', 'type_name': '欧美精品'},
        {'type_id': '392', 'type_name': 'AV解说'},
        {'type_id': '130', 'type_name': '卡通动漫'},
        {'type_id': '452', 'type_name': 'SWAG'},
        {'type_id': '52', 'type_name': '欧美性爱'},
        {'type_id': '453', 'type_name': '激情动漫'},
        {'type_id': '115', 'type_name': '女同性恋'},
        {'type_id': '125', 'type_name': '童颜巨乳'},
        {'type_id': '275', 'type_name': '日韩精品'},
        {'type_id': '111', 'type_name': '美乳巨乳'},
        {'type_id': '265', 'type_name': '欧美情色'},
        {'type_id': '266', 'type_name': '欧美极品'},
        {'type_id': '425', 'type_name': '性感人妻'},
        {'type_id': '23', 'type_name': '人妻熟女'},
        {'type_id': '658', 'type_name': '欧美-高清无码'},
        {'type_id': '454', 'type_name': '黑丝诱惑'},
        {'type_id': '84', 'type_name': '三级伦理'},
        {'type_id': '273', 'type_name': '邻家人妻'},
        {'type_id': '101', 'type_name': '人妻系列'},
        {'type_id': '99', 'type_name': '巨乳系列'},
        {'type_id': '416', 'type_name': '麻豆传媒'},
        {'type_id': '267', 'type_name': '熟女人妻'},
        {'type_id': '129', 'type_name': '多人群交'},
        {'type_id': '403', 'type_name': '日本片商'},
        {'type_id': '5', 'type_name': '空姐模特'},
        {'type_id': '134', 'type_name': '激情口交'},
        {'type_id': '424', 'type_name': '丝袜OL'},
        {'type_id': '149', 'type_name': '动漫卡通'},
        {'type_id': '110', 'type_name': '口交视频'},
        {'type_id': '106', 'type_name': 'SM重味'},
        {'type_id': '451', 'type_name': 'VR视角'},
        {'type_id': '131', 'type_name': '欧美系列'},
        {'type_id': '357', 'type_name': 'AI换脸'},
        {'type_id': '64', 'type_name': '亚洲无码'},
        {'type_id': '132', 'type_name': '女同性爱'},
        {'type_id': '467', 'type_name': '日本精品'},
        {'type_id': '96', 'type_name': '高潮喷吹'},
        {'type_id': '657', 'type_name': '日本-中文字幕'},
        {'type_id': '653', 'type_name': '韩国-主播'},
        {'type_id': '643', 'type_name': '禁漫'},
        {'type_id': '432', 'type_name': '日本女优'},
        {'type_id': '644', 'type_name': '伦理片'},
        {'type_id': '54', 'type_name': '韩国明星学生'},
        {'type_id': '666', 'type_name': '日本-高清有码'},
        {'type_id': '120', 'type_name': '伦理影片'},
        {'type_id': '516', 'type_name': '换脸明星'},
        {'type_id': '44', 'type_name': '韩国伦理'},
        {'type_id': '717', 'type_name': '日本-素人'},
        {'type_id': '246', 'type_name': '欧美无码'},
        {'type_id': '124', 'type_name': 'HEYZO'},
    ]

    def __init__(self):
        self._sess = None
        self.extend = {}
        self.proxyUrl = ''

    def init(self, extend):
        self.extend = extend
        if isinstance(extend, dict):
            if extend.get('siteUrl'):
                self.base_url = extend['siteUrl'].rstrip('/')
            if extend.get('proxy'):
                self.proxyUrl = extend['proxy']
        elif isinstance(extend, str) and extend.strip():
            try:
                d = json.loads(extend)
                if d.get('siteUrl'):
                    self.base_url = d['siteUrl'].rstrip('/')
                if d.get('proxy'):
                    self.proxyUrl = d['proxy']
            except Exception:
                pass

    def _session(self):
        if self._sess is None:
            self._sess = _req.Session()
            self._sess.headers.update({
                'User-Agent': self.ua,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            })
        return self._sess

    def _solve_pow(self, seed, difficulty):
        prefix = '0' * difficulty
        nonce = 0
        while True:
            nh = format(nonce, 'x').zfill(16)
            if hashlib.sha256((seed + nh).encode()).hexdigest()[:difficulty] == prefix:
                return nh
            nonce += 1

    def _do_pow(self, s, r):
        m = re.search(r'<script id="__cdnlah_pow_config" type="application/json">(.*?)</script>', r.text)
        if not m:
            return
        cfg = json.loads(m.group(1))
        nonce = self._solve_pow(cfg['seed'], cfg['difficulty'])
        p = {
            'seed': cfg['seed'],
            'nonce': nonce,
            'redirect': cfg.get('redirect', '/'),
            'challenge_cookie': cfg.get('challenge_cookie', ''),
        }
        mf = cfg.get('metadata_field', '')
        mt = cfg.get('metadata_token', '')
        if mf and mt:
            p[mf] = mt
        try:
            s.post(self.base_url + cfg['verify_path'], data=p, timeout=30, allow_redirects=False)
        except Exception:
            pass

    def _do_fp(self, s, r):
        fp_m = re.search(r'<script src="(/__cdnlah/fp\.js\?[^"]+)"', r.text)
        fp_params = {}
        if fp_m:
            qs = parse_qs(urlparse(fp_m.group(1)).query)
            fp_params = {k: v[0] for k, v in qs.items()}
        fp_data = {
            'ua': self.ua,
            'platform': 'Win32',
            'language': 'zh-CN',
            'languages': ['zh-CN', 'zh', 'en'],
            'hardware_concurrency': 8,
            'device_memory': 8,
            'max_touch_points': 0,
            'webdriver': False,
            'plugins_count': 3,
            'screen_width': 1920,
            'screen_height': 1080,
            'color_depth': 24,
            'avail_width': 1920,
            'avail_height': 1040,
            'device_pixel_ratio': 1,
            'canvas_hash': 'a1b2c3d4',
            'webgl_renderer': 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)',
            'webgl_vendor': 'Google Inc. (Intel)',
            'audio_hash': 'e5f6a7b8',
            'fonts_count': 50,
            'cookie_enabled': True,
            'local_storage': True,
            'session_storage': True,
            'collect_ms': 15,
            '_n': fp_params.get('n', ''),
            '_t': int(fp_params.get('t', '0')),
            '_s': fp_params.get('s', ''),
        }
        try:
            s.post(self.base_url + '/__cdnlah/fp', json=fp_data, timeout=30)
        except Exception:
            pass

    def fetch(self, path, retries=4):
        s = self._session()
        url = self.base_url + path
        for i in range(retries):
            try:
                r = s.get(url, timeout=30)
            except Exception:
                time.sleep(1)
                continue
            if r.status_code == 200:
                return r.text
            if r.status_code == 492:
                self._do_pow(s, r)
                continue
            if r.status_code == 496:
                self._do_fp(s, r)
                self._do_pow(s, r)
                continue
            time.sleep(0.5)
        try:
            return s.get(url, timeout=30).text
        except Exception:
            return ''

    def parse_list(self, html):
        videos = []
        if not html:
            return videos
        pattern = re.compile(
            r'<a class="visited" href="/v/([a-zA-Z0-9]+)">'
            r'<img class="card-img-top" src="([^"]+)" alt="([^"]*)"',
            re.DOTALL
        )
        for m in pattern.finditer(html):
            vid, pic, title = m.groups()
            title = title.strip()
            if _is_minor(title):
                continue
            videos.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': '',
            })
        return videos

    def homeContent(self, *args):
        try:
            classes = [{'type_id': c['type_id'], 'type_name': c['type_name']} for c in self.categories]
            filters = {}
            for c in self.categories:
                filters[c['type_id']] = []
            html = self.fetch('/')
            videos = self.parse_list(html)
            return {
                'class': classes,
                'filters': filters,
                'list': videos,
            }
        except Exception as e:
            print('[傻傻视频 homeContent错误] %s' % e)
            classes = [{'type_id': c['type_id'], 'type_name': c['type_name']} for c in self.categories]
            return {'class': classes, 'filters': {}, 'list': []}

    def homeVideoContent(self, *args):
        try:
            html = self.fetch('/')
            videos = self.parse_list(html)
            return {
                'page': 1,
                'pagecount': 1,
                'limit': 48,
                'total': len(videos),
                'list': videos,
            }
        except Exception as e:
            print('[傻傻视频 homeVideoContent错误] %s' % e)
            return {'page': 1, 'pagecount': 1, 'limit': 48, 'total': 0, 'list': []}

    def categoryContent(self, tid, pg, *args):
        try:
            try:
                page = int(pg) if pg else 1
            except (ValueError, TypeError):
                page = 1
            path = '/cat/%s' % tid
            if page > 1:
                path += '?page=%d' % page
            html = self.fetch(path)
            videos = self.parse_list(html)
            pagecount = 999
            if len(videos) < 40:
                pagecount = page
            return {
                'page': page,
                'pagecount': pagecount,
                'limit': 48,
                'total': len(videos),
                'list': videos,
            }
        except Exception as e:
            print('[傻傻视频 categoryContent错误] %s' % e)
            return {'page': 1, 'pagecount': 1, 'limit': 48, 'total': 0, 'list': []}

    def detailContent(self, ids, *args):
        try:
            if not ids:
                return {'list': []}
            if isinstance(ids, str):
                ids = [ids]
            videos = []
            for vod_id in ids:
                html = self.fetch('/v/%s' % vod_id)
                if not html:
                    continue
                title = ''
                m = re.search(r"<meta property='og:title' content=\"([^\"]+)\"", html)
                if not m:
                    m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
                if m:
                    title = m.group(1).strip()
                if _is_minor(title):
                    continue
                pic = ''
                m = re.search(r"<meta property='og:image' content=\"([^\"]+)\"", html)
                if not m:
                    m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                if m:
                    pic = m.group(1).strip()
                content = ''
                m = re.search(r"<meta name='description' content=\"([^\"]+)\"", html)
                if not m:
                    m = re.search(r'<meta name="description" content="([^"]+)"', html)
                if m:
                    content = m.group(1).strip()
                play_url = ''
                m = re.search(r"<source src=\"([^\"]+\.m3u8[^\"]*)\"", html)
                if not m:
                    m = re.search(r"<source src='([^']+\.m3u8[^']*)'", html)
                if m:
                    play_url = m.group(1).strip()
                if not play_url:
                    continue
                ep_name = title if title else '正片'
                videos.append({
                    'vod_id': str(vod_id),
                    'vod_name': title,
                    'vod_pic': pic,
                    'vod_content': content,
                    'vod_play_from': '线路1',
                    'vod_play_url': '%s$%s' % (ep_name, play_url),
                    'vod_remarks': '',
                })
            return {'list': videos}
        except Exception as e:
            print('[傻傻视频 detailContent错误] %s' % e)
            return {'list': []}

    def playerContent(self, flag, id, vipFlags=None, *args):
        try:
            html = self.fetch('/v/%s' % id)
            play_url = ''
            if html:
                m = re.search(r"<source src=\"([^\"]+\.m3u8[^\"]*)\"", html)
                if not m:
                    m = re.search(r"<source src='([^']+\.m3u8[^']*)'", html)
                if m:
                    play_url = m.group(1).strip()
            final_url = self._proxy_m3u8(play_url)
            return {
                'parse': 0,
                'jx': 0,
                'url': final_url,
                'header': {
                    'User-Agent': self.ua,
                    'Referer': self.base_url + '/',
                },
            }
        except Exception as e:
            print('[傻傻视频 playerContent错误] %s' % e)
            return {'parse': 0, 'jx': 0, 'url': '', 'header': {}}

    def _proxy_m3u8(self, url):
        if not url:
            return url
        if not self.proxyUrl:
            return url
        enc = base64.b64encode(url.encode('utf-8')).decode('utf-8')
        sep = '&' if '?' in self.proxyUrl else '?'
        return '%s%sb64=%s' % (self.proxyUrl, sep, enc)

    def searchContent(self, wd, pg, *args):
        try:
            try:
                page = int(pg) if pg else 1
            except (ValueError, TypeError):
                page = 1
            if _is_minor(wd):
                return {'page': page, 'pagecount': 0, 'limit': 50, 'total': 0, 'list': []}
            path = '/?q=%s' % quote(wd)
            if page > 1:
                path += '&page=%d' % page
            html = self.fetch(path)
            videos = self.parse_list(html)
            return {
                'page': page,
                'pagecount': 1,
                'limit': 50,
                'total': len(videos),
                'list': videos,
            }
        except Exception as e:
            print('[傻傻视频 searchContent错误] %s' % e)
            return {'page': 1, 'pagecount': 1, 'limit': 50, 'total': 0, 'list': []}

    def localProxy(self, path, *args):
        if not path:
            return [404, 'text/plain', '']
        b64 = ''
        m = re.search(r'[?&]b64=([^&]+)', path)
        if m:
            b64 = m.group(1)
        if not b64:
            return [404, 'text/plain', '']
        try:
            url = base64.b64decode(b64).decode('utf-8')
        except Exception:
            return [404, 'text/plain', '']
        try:
            r = _req.get(url, timeout=30, headers={'User-Agent': self.ua})
            if r.status_code != 200:
                return [404, 'text/plain', '']
            text = r.text
        except Exception:
            return [404, 'text/plain', '']
        cleaned = self._clean_m3u8(text, url)
        return [200, 'application/vnd.apple.mpegurl', cleaned]

    def _clean_m3u8(self, text, base_url):
        if not text or not text.startswith('#EXTM3U'):
            return text
        lines = text.split('\n')
        if '#EXT-X-STREAM-INF' in text:
            out = []
            i = 0
            while i < len(lines):
                line = lines[i]
                if line.startswith('#EXT-X-STREAM-INF'):
                    out.append(line)
                    if i + 1 < len(lines):
                        child = lines[i + 1].strip()
                        if child and not child.startswith('#'):
                            child_abs = urljoin(base_url, child)
                            enc = base64.b64encode(child_abs.encode('utf-8')).decode('utf-8')
                            if self.proxyUrl:
                                sep = '&' if '?' in self.proxyUrl else '?'
                                out.append('%s%sb64=%s' % (self.proxyUrl, sep, enc))
                            else:
                                out.append(child_abs)
                        else:
                            out.append(child)
                    i += 2
                    continue
                out.append(line)
                i += 1
            return '\n'.join(out)
        base_path = ''
        parsed = urlparse(base_url)
        parts = parsed.path.strip('/').split('/')
        if len(parts) >= 2:
            base_path = '/%s/%s/' % (parts[0], parts[1])
        out = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith('#EXTINF'):
                if i + 1 < len(lines):
                    ts_line = lines[i + 1].strip()
                    if ts_line and not ts_line.startswith('#'):
                        ts_abs = urljoin(base_url, ts_line)
                        ts_parsed = urlparse(ts_abs)
                        if base_path and base_path in ts_parsed.path:
                            out.append(line)
                            out.append(ts_abs)
                        i += 2
                        continue
                i += 1
                continue
            out.append(line)
            i += 1
        return '\n'.join(out)

    def getDependence(self, *args):
        return ''

    def isVideoFormat(self, *args):
        return True

    def manualVideoCheck(self, *args):
        return False

    def action(self, *args):
        return {}

    def destroy(self, *args):
        self._sess = None
