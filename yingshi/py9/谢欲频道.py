# -*- coding: utf-8 -*-
# 谢欲频道 - TVBox FongMi 标准 Spider
# 站点: https://www.tongtoubani.cfd/
# 苹果CMS架构, m1938pc 模板, m3u8 在播放页 player_aaaa JSON 中

import re
import json

try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    class _BaseSpider:
        def init(self, extend=""):
            pass

try:
    from urllib.parse import quote, urljoin
except ImportError:
    from urllib import quote
    from urlparse import urljoin


class Spider(_BaseSpider):
    def init(self, extend=""):
        self.siteUrl = "https://www.tongtoubani.cfd"
        self.HOST = self.siteUrl
        self.ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"

        # 允许通过 extend 覆盖域名
        if extend:
            try:
                cfg = json.loads(extend) if isinstance(extend, str) else extend
                if isinstance(cfg, dict) and cfg.get("siteUrl"):
                    self.siteUrl = cfg["siteUrl"].rstrip("/")
                    self.HOST = self.siteUrl
            except Exception:
                pass

    # =========================================================
    # 首页
    # =========================================================
    def homeContent(self, filter):
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
        filters = {
            c["type_id"]: [{"key": "class", "name": "分类", "value": [{"n": "全部", "v": ""}]}]
            for c in classes
        }
        result = {"class": classes, "filters": filters}
        if filter:
            html = self._get(f"{self.siteUrl}/index.php/vod/type/id/1.html")
            result["list"] = self._parse_list(html)[:6]
        return result

    def homeVideoContent(self):
        html = self._get(self.siteUrl + "/")
        return {"list": self._parse_list(html)[:12]}

    # =========================================================
    # 分类
    # =========================================================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg)
        except Exception:
            page = 1

        if page <= 1:
            url = f"{self.siteUrl}/index.php/vod/type/id/{tid}.html"
        else:
            url = f"{self.siteUrl}/index.php/vod/type/id/{tid}/page/{page}.html"

        html = self._get(url)
        lst = self._parse_list(html)

        # 从页面提取总页数: "当前 1/45 页"
        pagecount = 1
        m = re.search(r'当前\s*\d+\s*/\s*(\d+)\s*页', html)
        if m:
            pagecount = int(m.group(1))
        else:
            nums = re.findall(r'/page/(\d+)\.html', html)
            if nums:
                pagecount = max(int(n) for n in nums)

        return {
            "page": page,
            "pagecount": pagecount,
            "limit": 24,
            "total": len(lst) * pagecount,
            "list": lst,
        }

    # =========================================================
    # 详情
    # =========================================================
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        if isinstance(ids, str):
            ids = [ids]

        out = []
        for vod_id in ids:
            if not vod_id:
                continue

            # vod_id 可能是完整 URL 或纯数字
            if vod_id.startswith("http"):
                detail_url = vod_id
                m = re.search(r'/id/(\d+)\.html', vod_id)
                vod_id = m.group(1) if m else vod_id
            elif vod_id.startswith("/"):
                detail_url = self.siteUrl + vod_id
            else:
                detail_url = f"{self.siteUrl}/index.php/vod/detail/id/{vod_id}.html"

            html = self._get(detail_url)
            if not html:
                continue

            # 标题
            title = ""
            tm = re.search(r'<title>([^<]+)</title>', html)
            if tm:
                title = tm.group(1)
                for sep in ("详情介绍", "在线观看", "-"):
                    if sep in title:
                        title = title.split(sep)[0]
                title = title.strip()

            # 封面（兼容多种写法）
            pic = ""
            for pat in [
                r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
                r'data-original=["\']([^"\']+)["\']',
                r'<img[^>]*src=["\']([^"\']+)["\']',
            ]:
                pm = re.search(pat, html)
                if pm:
                    pic = pm.group(1)
                    break
            if pic and not pic.startswith("http"):
                pic = urljoin(self.siteUrl, pic)

            # 找播放页链接
            play_link = ""
            for pat in [
                r'href=["\'](/index\.php/vod/play/id/\d+/sid/\d+/nid/\d+\.html)["\']',
                r'href=["\'](/vod/play/id/\d+/sid/\d+/nid/\d+\.html)["\']',
            ]:
                pm = re.search(pat, html)
                if pm:
                    play_link = pm.group(1)
                    break

            # 从播放页提取 m3u8
            play_url = ""
            if play_link:
                play_html = self._get(self.siteUrl + play_link)
                if play_html:
                    play_url = self._extract_m3u8(play_html)

            play_from = "谢欲频道"
            play_url_str = "第1集$" + play_url if play_url else ""

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

    # =========================================================
    # 搜索
    # =========================================================
    def searchContent(self, key, quick, pg="1"):
        if not key:
            return {"list": []}
        try:
            page = int(pg)
        except Exception:
            page = 1

        if page <= 1:
            url = f"{self.siteUrl}/index.php/vod/search/wd/{quote(key)}.html"
        else:
            url = f"{self.siteUrl}/index.php/vod/search/wd/{quote(key)}/page/{page}.html"

        html = self._get(url)
        lst = self._parse_list(html)

        pagecount = 1
        m = re.search(r'当前\s*\d+\s*/\s*(\d+)\s*页', html)
        if m:
            pagecount = int(m.group(1))

        return {"page": page, "pagecount": pagecount, "limit": 24, "total": len(lst) * pagecount, "list": lst}

    # =========================================================
    # 播放
    # =========================================================
    def playerContent(self, flag, id, vipFlags):
        url = id or ""
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

    def localProxy(self, param):
        return [404, "text/plain", ""]

    def action(self, action_str):
        return ""

    # =========================================================
    # 辅助方法
    # =========================================================
    def _extract_m3u8(self, html):
        """从播放页提取 m3u8 地址, 优先解析 player_aaaa JSON"""
        # 1) player_aaaa / player_data JSON
        for key in ("player_aaaa", "player_data", "mac_player_data"):
            m = re.search(rf'(?:var\s+)?{key}\s*=\s*(\{{[\s\S]*?\}})\s*[;<]', html)
            if not m:
                continue
            raw = m.group(1)
            url = ""
            encrypt = 0
            try:
                data = json.loads(raw)
                url = str(data.get("url") or "")
                try:
                    encrypt = int(data.get("encrypt") or 0)
                except Exception:
                    encrypt = 0
            except Exception:
                um = re.search(r'"url"\s*:\s*"([^"]*)"', raw)
                if um:
                    url = um.group(1)
                em = re.search(r'"encrypt"\s*:\s*(\d+)', raw)
                if em:
                    encrypt = int(em.group(1))

            if not url:
                continue

            url = url.replace("\\/", "/").replace("\\u0026", "&")

            # encrypt=1: URL 是 base64
            if encrypt == 1:
                try:
                    import base64
                    url = base64.b64decode(url).decode("utf-8", errors="replace")
                except Exception:
                    pass

            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = self.siteUrl + url
            elif not url.startswith("http"):
                url = urljoin(self.siteUrl + "/", url)

            return url

        # 2) 直接抓 m3u8 链接
        m = re.search(r'(https?://[^\s"\'<>]+?\.m3u8[^\s"\'<>]*)', html)
        if m:
            url = m.group(1).replace("\\/", "/")
            if url.startswith("//"):
                url = "https:" + url
            return url

        # 3) base64 形态
        m = re.search(r'"url"\s*:\s*"(aHR0c[^"]+)"', html)
        if m:
            try:
                import base64
                decoded = base64.b64decode(m.group(1)).decode("utf-8", errors="replace")
                if decoded.startswith("http"):
                    return decoded
            except Exception:
                pass

        return ""

    def _parse_list(self, html):
        """解析列表页, 返回 vod 列表"""
        if not html:
            return []

        out = []
        seen = set()

        # 优先匹配 <a> 内部包含标题和图片的块
        a_pat = re.compile(
            r'<a[^>]*href=["\'](?:https?://[^"\']+)?(/index\.php/vod/detail/id/(\d+)\.html)["\'][^>]*>(.*?)</a>',
            re.S
        )
        for m in a_pat.finditer(html):
            href = m.group(1)
            vod_id = m.group(2)
            inner = m.group(3)
            tag = m.group(0)

            if vod_id in seen:
                continue
            seen.add(vod_id)

            # 标题
            title = ""
            tm = re.search(r'title=["\']([^"\']+)["\']', tag)
            if tm:
                title = tm.group(1).strip()
            if not title:
                tm = re.search(r'<h[1-6][^>]*>(.*?)</h[1-6]>', inner, re.S)
                if tm:
                    title = re.sub(r'<[^>]+>', '', tm.group(1)).strip()
            if not title:
                title = f"视频{vod_id}"

            # 封面
            pic = ""
            for pat in [
                r'data-original=["\']([^"\']+)["\']',
                r'<img[^>]*data-src=["\']([^"\']+)["\']',
                r'style=["\'][^"\']*url\(([^)]+)\)',
                r'<img[^>]*src=["\']([^"\']+)["\']',
            ]:
                pm = re.search(pat, inner)
                if pm:
                    pic = pm.group(1).strip("'\" ")
                    break
            if pic and not pic.startswith("http"):
                pic = urljoin(self.siteUrl, pic)

            out.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": "",
            })

        # 兜底: 只用 href+title 匹配
        if not out:
            for m in re.finditer(
                r'<a[^>]*href=["\'](?:https?://[^"\']+)?/index\.php/vod/detail/id/(\d+)\.html["\'][^>]*title=["\']([^"\']+)["\']',
                html
            ):
                vod_id = m.group(1)
                if vod_id in seen:
                    continue
                seen.add(vod_id)
                out.append({
                    "vod_id": vod_id,
                    "vod_name": m.group(2).strip(),
                    "vod_pic": "",
                    "vod_remarks": "",
                })

        print(f"[谢欲频道] parse_list -> {len(out)} 条")
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