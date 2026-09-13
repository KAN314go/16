# -*- coding: utf-8 -*-
import re
import json
from urllib.parse import quote, urljoin

try:
    from base.spider import Spider
except Exception:
    class Spider:
        def __init__(self):
            self.extend = {}
        def init(self, extend):
            self.extend = extend or {}

class Spider(Spider):
    def __init__(self):
        super().__init__()
        self.siteUrl = "https://www.tongtoubani.cfd"
        self.HOST = self.siteUrl
        self.ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"

    def init(self, extend=""):
        if extend and isinstance(extend, str):
            try:
                self.extend = json.loads(extend)
            except Exception:
                self.extend = {}
        elif extend and isinstance(extend, dict):
            self.extend = extend
        else:
            self.extend = {}
        if self.extend.get("siteUrl"):
            self.siteUrl = self.extend["siteUrl"]
            self.HOST = self.siteUrl

    def homeContent(self, *args):
        classes = [
            {"type_id": "1", "type_name": "国产传媒"},
            {"type_id": "2", "type_name": "国产视频"},
            {"type_id": "3", "type_name": "国产主播"},
            {"type_id": "4", "type_name": "国产明星"},
            {"type_id": "6", "type_name": "抖阴视频"},
            {"type_id": "7", "type_name": "网爆黑料"},
            {"type_id": "8", "type_name": "擦边电影"},
            {"type_id": "9", "type_name": "网红流出"},
            {"type_id": "10", "type_name": "欧美无码"},
            {"type_id": "11", "type_name": "中文字幕"},
            {"type_id": "12", "type_name": "丰满女优"},
            {"type_id": "13", "type_name": "女同性恋"},
            {"type_id": "14", "type_name": "激情动漫"},
            {"type_id": "15", "type_name": "强奸乱伦"},
            {"type_id": "16", "type_name": "日本无码"},
        ]
        filters = {c["type_id"]: [{"key": "class", "name": "分类", "value": [{"n": "全部", "v": ""}]}] for c in classes}
        lst = self._parse_list(self._get(f"{self.siteUrl}/index.php/vod/type/id/1.html"))
        return {"class": classes, "list": lst[:6], "filters": filters}

    def categoryContent(self, tid, page, *args):
        page = int(page) if page else 1
        if page <= 1:
            url = f"{self.siteUrl}/index.php/vod/type/id/{tid}.html"
        else:
            url = f"{self.siteUrl}/index.php/vod/type/id/{tid}/page/{page}.html"
        html = self._get(url)
        lst = self._parse_list(html)
        # 从页面提示提取总页数: "共1074条数据,当前1/45页"
        pagecount = 1
        m = re.search(r'当前\d+/(\d+)页', html)
        if m:
            pagecount = int(m.group(1))
        total = len(lst) * pagecount
        return {"page": page, "pagecount": pagecount, "limit": 24, "total": total, "list": lst}

    def detailContent(self, ids, *args):
        if not ids:
            return {"list": []}
        if isinstance(ids, str):
            ids = [ids]
        out = []
        for vod_id in ids:
            if not vod_id:
                continue
            if vod_id.startswith("http"):
                detail_url = vod_id
                m = re.search(r'/id/(\d+)\.html', vod_id)
                vod_id = m.group(1) if m else vod_id
            elif vod_id.startswith("/"):
                detail_url = f"{self.siteUrl}{vod_id}"
            else:
                detail_url = f"{self.siteUrl}/index.php/vod/detail/id/{vod_id}.html"

            html = self._get(detail_url)
            if not html:
                continue

            title = ""
            tm = re.search(r'<title>([^<]+)</title>', html)
            if tm:
                title = tm.group(1).split("详情介绍")[0].split("在线观看")[0].strip()

            pic = ""
            pm = re.search(r'<img[^>]*src=["\']([^"\']+)["\']', html)
            if pm:
                pic = pm.group(1)
            if pic and not pic.startswith("http"):
                pic = urljoin(self.siteUrl, pic)

            # 提取播放页链接
            play_link = ""
            for pat in [
                r'href=["\'](/index\.php/vod/play/id/\d+/sid/\d+/nid/\d+\.html)["\']',
                r'href=["\'](/vod/play/id/\d+/sid/\d+/nid/\d+\.html)["\']',
            ]:
                pm2 = re.search(pat, html)
                if pm2:
                    play_link = pm2.group(1)
                    break

            play_url = ""
            if play_link:
                play_html = self._get(f"{self.siteUrl}{play_link}")
                if play_html:
                    # 优先从 player_aaaa JSON 提取
                    m = re.search(r'player_aaaa\s*=\s*(\{[^;]+\})', play_html)
                    if m:
                        try:
                            data = json.loads(m.group(1))
                            play_url = data.get("url", "")
                        except Exception:
                            pass
                    if not play_url:
                        # 回退：直接找 m3u8
                        m = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', play_html)
                        if m:
                            play_url = m.group(1)

            play_from = "谢欲频道"
            play_url_str = f"第1集${play_url}" if play_url else ""
            out.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": "",
                "vod_content": title,
                "vod_play_from": play_from,
                "vod_play_url": play_url_str,
            })
        return {"list": out}

    def playerContent(self, flag, id, vipFlags, *args):
        url = id
        if not url.startswith("http"):
            url = urljoin(self.siteUrl, url)
        return {
            "parse": 0,
            "jx": 0,
            "url": url,
            "header": {
                "User-Agent": self.ua,
                "Referer": self.siteUrl + "/",
                "Origin": self.siteUrl,
            },
        }

    def searchContent(self, key, page, *args):
        page = int(page) if page else 1
        url = f"{self.siteUrl}/index.php/vod/search/wd/{quote(key)}.html"
        html = self._get(url)
        lst = self._parse_list(html)
        return {"page": page, "pagecount": 1, "limit": 24, "total": len(lst), "list": lst}

    def _parse_list(self, html):
        if not html:
            return []
        out = []
        seen = set()
        # 匹配所有指向 detail 的 <a> 标签
        pattern = re.compile(
            r'<a[^>]*href=["\'](/index\.php/vod/detail/id/(\d+)\.html)["\'][^>]*>(.*?)</a>',
            re.S
        )
        for m in pattern.finditer(html):
            href = m.group(1)
            vod_id = m.group(2)
            inner = m.group(3)
            if vod_id in seen:
                continue
            seen.add(vod_id)

            title = ""
            tm = re.search(r'title=["\']([^"\']+)["\']', m.group(0))
            if tm:
                title = tm.group(1)
            if not title:
                tm = re.search(r'<h[1-6][^>]*>(.*?)</h[1-6]>', inner, re.S)
                if tm:
                    title = re.sub(r'<[^>]+>', '', tm.group(1)).strip()
            if not title:
                title = f"视频{vod_id}"

            pic = ""
            pm = re.search(r'data-original=["\']([^"\']+)["\']', inner)
            if pm:
                pic = pm.group(1)
            if not pic:
                pm = re.search(r'style=["\'][^"\']*url\(([^)]+)\)', inner)
                if pm:
                    pic = pm.group(1).strip("'\" ")
            if not pic:
                pm = re.search(r'<img[^>]*src=["\']([^"\']+)["\']', inner)
                if pm:
                    pic = pm.group(1)
            if pic and not pic.startswith("http"):
                pic = urljoin(self.siteUrl, pic)

            out.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": "",
            })
        return out

    def _get(self, url):
        try:
            import urllib.request
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=ctx)
            )
            req = urllib.request.Request(url, headers={
                "User-Agent": self.ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            resp = opener.open(req, timeout=20)
            return resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"[谢欲频道] 请求失败 {url}: {e}")
            return ""

    def getDependence(self, *args):
        return ""

    def localProxy(self, *args):
        return [404, "text/plain", ""]

    def isVideoFormat(self, url, *args):
        return any(url.endswith(ext) for ext in [".m3u8", ".mp4", ".avi", ".mkv", ".flv"])

    def manualVideoCheck(self, *args):
        return False

    def destroy(self, *args):
        pass