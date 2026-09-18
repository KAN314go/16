# -*- coding: utf-8 -*-
# 夜汐 NIGHTTIDE - TVBox FongMi Spider
# 站点: https://nighttide.web.zaka.live

import re
import json

try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    class _BaseSpider:
        def init(self, extend=""):
            pass

try:
    from urllib.parse import quote, urljoin, unquote
    from urllib.request import Request, urlopen
except ImportError:
    from urllib import quote, unquote
    from urlparse import urljoin
    from urllib2 import Request, urlopen

_has_requests = False
try:
    import requests
    _has_requests = True
except ImportError:
    pass


# ★★★ 播放模式开关 ★★★
# "none"  直接返回原始 URL (先试这个)
# "local" local:// 走 localProxy
# "proxy" proxy:// 走 localProxy
PLAY_MODE = "none"

# localProxy 返回格式
# 3 -> [code, ct, body]
# 4 -> [code, ct, body, headers]
PROXY_RETURN = 3


class Spider(_BaseSpider):
    def init(self, extend=""):
        self.host = "https://nighttide.web.zaka.live"
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        if extend:
            try:
                cfg = json.loads(extend) if isinstance(extend, str) else extend
                if isinstance(cfg, dict) and cfg.get("siteUrl"):
                    self.host = cfg["siteUrl"].rstrip("/")
            except Exception:
                pass

        self._ssl_ctx = None
        try:
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self._ssl_ctx = ctx
        except Exception:
            pass

        self.lines = [
            {
                "api": "/api2/",
                "name": "主线路",
                "cats": [
                    {"id": 37, "n": "日本精品"},
                    {"id": 25, "n": "亚洲有码"},
                    {"id": 26, "n": "中文字幕"},
                    {"id": 28, "n": "人妻熟女"},
                    {"id": 51, "n": "女优系列"},
                    {"id": 24, "n": "亚洲无码"},
                ],
            },
            {
                "api": "/api/",
                "name": "备用线路",
                "cats": [
                    {"id": 9, "n": "中文字幕"},
                    {"id": 1, "n": "亚洲情色"},
                ],
            },
        ]

    # =========================================================
    # 网络
    # =========================================================
    def _fetch_json(self, path, params):
        url = self.host + path
        h = {
            "User-Agent": self.ua,
            "Accept": "application/json, text/plain, */*",
            "Referer": self.host + "/",
        }
        try:
            if _has_requests:
                r = requests.get(url, params=params, headers=h, timeout=20, verify=False)
                if r.status_code == 200:
                    return r.json()
        except Exception as e:
            print(f"[夜汐] requests 失败: {e}")

        try:
            qs = "&".join(f"{k}={quote(str(v))}" for k, v in params.items() if v is not None)
            full = f"{url}?{qs}" if qs else url
            req = Request(full, headers=h)
            if self._ssl_ctx:
                resp = urlopen(req, timeout=20, context=self._ssl_ctx)
            else:
                resp = urlopen(req, timeout=20)
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception as e:
            print(f"[夜汐] urllib 失败: {e}")
            return None

    def _api(self, params, line_idx=0):
        for i in range(line_idx, len(self.lines)):
            data = self._fetch_json(self.lines[i]["api"], params)
            if data and isinstance(data, dict):
                return data
        return None

    # =========================================================
    # 首页
    # =========================================================
    def homeContent(self, filter):
        classes = []
        for line in self.lines:
            for c in line["cats"]:
                classes.append({
                    "type_id": f"{line['api']}|{c['id']}",
                    "type_name": c["n"],
                })
        result = {"class": classes, "filters": {}}
        if filter:
            data = self._api({"ac": "videolist", "t": 37, "pg": 1, "pagesize": 12}, 0)
            if data:
                result["list"] = self._parse_vod_list(data.get("list", []))
        return result

    def homeVideoContent(self):
        data = self._api({"ac": "videolist", "t": 37, "pg": 1, "pagesize": 12}, 0)
        if data:
            return {"list": self._parse_vod_list(data.get("list", []))}
        return {"list": []}

    # =========================================================
    # 分类
    # =========================================================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg)
        except Exception:
            page = 1

        line_path = "/api2/"
        cat_id = 37
        if "|" in str(tid):
            parts = str(tid).split("|")
            line_path = parts[0]
            try:
                cat_id = int(parts[1])
            except Exception:
                cat_id = 37

        line_idx = 0
        for i, line in enumerate(self.lines):
            if line["api"] == line_path:
                line_idx = i
                break

        data = self._api({
            "ac": "videolist", "t": cat_id, "pg": page, "pagesize": 24,
        }, line_idx)

        if not data:
            return {"page": page, "pagecount": 1, "limit": 24, "total": 0, "list": []}

        lst = self._parse_vod_list(data.get("list", []))
        total = int(data.get("total") or 0)
        pagecount = int(data.get("pagecount") or 0)
        if not pagecount:
            pagecount = max(1, (total + 23) // 24)

        return {"page": page, "pagecount": pagecount, "limit": 24, "total": total, "list": lst}

    # =========================================================
    # 详情
    # =========================================================
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vid = ids[0] if isinstance(ids, list) else ids

        data = None
        for i in range(len(self.lines)):
            d = self._api({"ac": "detail", "ids": vid}, i)
            if d and d.get("list"):
                data = d
                break

        if not data:
            return {"list": []}

        v = data["list"][0]
        raw_play_url = v.get("vod_play_url") or ""
        play_from, play_url = self._parse_play_url(raw_play_url)

        print(f"[夜汐] detail vod_id={v.get('vod_id')} name={v.get('vod_name')}")
        print(f"[夜汐] play_from={play_from}")
        print(f"[夜汐] play_url (前200字)={play_url[:200]}")

        return {"list": [{
            "vod_id": str(v.get("vod_id") or vid),
            "vod_name": str(v.get("vod_name") or ""),
            "vod_pic": str(v.get("vod_pic") or ""),
            "type_name": str(v.get("type_name") or ""),
            "vod_year": str(v.get("vod_year") or ""),
            "vod_area": str(v.get("vod_area") or ""),
            "vod_remarks": str(v.get("vod_remarks") or ""),
            "vod_actor": str(v.get("vod_actor") or ""),
            "vod_director": str(v.get("vod_director") or ""),
            "vod_content": str(v.get("vod_content") or ""),
            "vod_play_from": play_from,
            "vod_play_url": play_url,
        }]}

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

        data = self._api({"ac": "videolist", "wd": key, "pg": page, "pagesize": 30}, 0)
        if not data:
            return {"page": page, "pagecount": 1, "limit": 30, "total": 0, "list": []}

        lst = self._parse_vod_list(data.get("list", []))
        total = int(data.get("total") or len(lst))
        pagecount = int(data.get("pagecount") or 1)

        return {"page": page, "pagecount": pagecount, "limit": 30, "total": total, "list": lst}

    # =========================================================
    # 播放
    # =========================================================
    def playerContent(self, flag, id, vipFlags):
        url = str(id or "").strip()
        if not url.startswith("http"):
            url = urljoin(self.host, url)

        print(f"[夜汐] playerContent mode={PLAY_MODE} url={url}")

        header = {
            "User-Agent": self.ua,
            "Referer": self.host + "/",
            "Origin": self.host,
        }

        if PLAY_MODE == "none":
            return {"parse": 0, "jx": 0, "url": url, "header": header}
        elif PLAY_MODE == "local":
            return {"parse": 0, "jx": 0, "url": "local://" + url, "header": header}
        elif PLAY_MODE == "proxy":
            return {"parse": 0, "jx": 0, "url": "proxy://" + url, "header": header}
        else:
            return {"parse": 0, "jx": 0, "url": url, "header": header}

    # =========================================================
    # localProxy
    # =========================================================
    def localProxy(self, param):
        if not param:
            return [404, "text/plain", b""] if PROXY_RETURN == 3 else [404, "text/plain", b"", {}]

        if isinstance(param, dict):
            url = param.get("url", "")
        else:
            url = str(param)

        for prefix in ("proxy://", "local://"):
            if url.startswith(prefix):
                url = url[len(prefix):]
                break

        if not url.startswith("http"):
            url = unquote(url)
            for prefix in ("proxy://", "local://"):
                if url.startswith(prefix):
                    url = url[len(prefix):]
                    break

        if not url.startswith("http"):
            print(f"[夜汐 localProxy] 非法 URL: {url[:100]}")
            return [404, "text/plain", b""] if PROXY_RETURN == 3 else [404, "text/plain", b"", {}]

        h = {
            "User-Agent": self.ua,
            "Referer": self.host + "/",
            "Origin": self.host,
            "Accept": "*/*",
        }

        try:
            if _has_requests:
                r = requests.get(url, headers=h, timeout=25, verify=False)
                data = r.content
                ct = r.headers.get("Content-Type", "")
                code = r.status_code
            else:
                req = Request(url, headers=h)
                if self._ssl_ctx:
                    resp = urlopen(req, timeout=25, context=self._ssl_ctx)
                else:
                    resp = urlopen(req, timeout=25)
                data = resp.read()
                ct = resp.headers.get("Content-Type", "")
                code = resp.getcode()

            if code != 200:
                print(f"[夜汐 localProxy] HTTP {code} {url[:80]}")
                return [code, "text/plain", b""] if PROXY_RETURN == 3 else [code, "text/plain", b"", {}]

            is_m3u8 = (
                "mpegurl" in ct.lower()
                or url.split("?")[0].lower().endswith(".m3u8")
                or data[:8] == b"#EXTM3U"
            )

            if is_m3u8:
                text = data.decode("utf-8", "replace")

                prefix_used = "proxy://" if PLAY_MODE == "proxy" else "local://"

                def _to_local(u):
                    if not u:
                        return u
                    if u.startswith("http"):
                        return prefix_used + u
                    return prefix_used + urljoin(url, u)

                out = []
                for line in text.splitlines():
                    s = line.strip()
                    if not s:
                        out.append(line)
                        continue
                    if s.startswith("#"):
                        if s.startswith("#EXT-X-KEY") or s.startswith("#EXT-X-MAP"):
                            def _rep(m):
                                return f'{m.group(1)}"{_to_local(m.group(2))}"'
                            s = re.sub(r'(URI=)"([^"]+)"', _rep, s)
                        out.append(s)
                        continue
                    out.append(_to_local(s))

                body = "\n".join(out).encode("utf-8")
                print(f"[夜汐 localProxy] m3u8 改写 {len(out)} 行")
                if PROXY_RETURN == 3:
                    return [200, "application/vnd.apple.mpegurl", body]
                else:
                    return [200, "application/vnd.apple.mpegurl", body, {"Content-Type": "application/vnd.apple.mpegurl"}]

            print(f"[夜汐 localProxy] {len(data)}B {ct} {url[-50:]}")
            if PROXY_RETURN == 3:
                return [200, ct or "application/octet-stream", data]
            else:
                return [200, ct or "application/octet-stream", data, {"Content-Type": ct or "application/octet-stream"}]

        except Exception as e:
            print(f"[夜汐 localProxy] 异常: {e}")
            return [500, "text/plain", b""] if PROXY_RETURN == 3 else [500, "text/plain", b"", {}]

    def action(self, action_str):
        return ""

    # =========================================================
    # 辅助
    # =========================================================
    def _parse_vod_list(self, lst):
        out = []
        if not lst:
            return out
        for v in lst:
            if not isinstance(v, dict):
                continue
            vod_id = str(v.get("vod_id") or "")
            if not vod_id:
                continue
            pic = str(v.get("vod_pic") or "")
            if pic and not pic.startswith("http"):
                pic = urljoin(self.host, pic)
            out.append({
                "vod_id": vod_id,
                "vod_name": str(v.get("vod_name") or ""),
                "vod_pic": pic,
                "vod_remarks": str(v.get("vod_remarks") or ""),
                "vod_year": str(v.get("vod_year") or ""),
                "type_name": str(v.get("type_name") or ""),
            })
        return out

    def _parse_play_url(self, raw):
        if not raw:
            return "", ""
        groups = raw.split("$$$")
        froms = []
        urls = []
        for gi, group in enumerate(groups):
            eps = group.split("#")
            ep_list = []
            for seg in eps:
                i = seg.rfind("$")
                if i < 0:
                    continue
                name = seg[:i].strip()
                url = seg[i + 1:].strip()
                if not url:
                    continue
                if not name:
                    name = f"第{len(ep_list) + 1}集"
                ep_list.append(f"{name}${url}")
            if ep_list:
                froms.append(f"线路{gi + 1}")
                urls.append("#".join(ep_list))
        if not froms:
            return "", ""
        return "$$$".join(froms), "$$$".join(urls)