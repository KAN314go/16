#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JavDB 四壳通用Python Spider
多域名自动切换（javdb580.com / javdb575.com / javdb574.com / javdb573.com / javdb572.com / javdb571.com / javdb.com）
支持：首页推荐 / 5大分类 / 搜索 / 详情（番号+封面+标题）
注意：详情页播放地址需登录，本爬虫提供列表浏览与搜索，播放地址返回在线源跳转提示
"""

import json
import re
import os
import time
import urllib.parse

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


# 多域名列表（按优先级排序，自动切换）
DOMAINS = [
    "https://javdb580.com",
    "https://javdb575.com",
    "https://javdb574.com",
    "https://javdb573.com",
    "https://javdb572.com",
    "https://javdb571.com",
    "https://javdb.com",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# 分类映射（tid -> vft参数，用首页筛选实现，无需登录）
CATEGORIES = [
    {"type_id": "censored", "type_name": "有码", "vft": 1},
    {"type_id": "uncensored", "type_name": "无码", "vft": 2},
    {"type_id": "western", "type_name": "欧美", "vft": 3},
    {"type_id": "fc2", "type_name": "FC2", "vft": 4},
    {"type_id": "anime", "type_name": "动漫", "vft": 5},
]


class Spider(_Base):
    name = "JavDB"
    profile = {"wd": 1, "ps": 40, "play_url": 1}

    def __init__(self):
        self._sess = None
        self._domain_idx = 0
        self.base_url = DOMAINS[0]

    def init(self, extend=""):
        if extend:
            try:
                d = json.loads(extend) if isinstance(extend, str) else extend
                if d.get("siteUrl"):
                    self.base_url = d["siteUrl"].rstrip("/")
                if d.get("domains"):
                    global DOMAINS
                    DOMAINS = d["domains"]
            except Exception:
                pass
        print(f"[JavDB] 当前域名: {self.base_url}")

    def _session(self):
        if self._sess is None:
            if not HAS_REQUESTS:
                raise RuntimeError("需要安装requests库: pip install requests")
            self._sess = _req.Session()
            self._sess.headers.update({
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8",
            })
        return self._sess

    def _switch_domain(self):
        """切换到下一个域名"""
        self._domain_idx = (self._domain_idx + 1) % len(DOMAINS)
        self.base_url = DOMAINS[self._domain_idx]
        print(f"[JavDB] 切换域名: {self.base_url}")

    def fetch(self, path, retries=3):
        """带多域名自动切换的请求"""
        s = self._session()
        for attempt in range(retries * len(DOMAINS)):
            url = self.base_url + path
            try:
                r = s.get(url, timeout=20, allow_redirects=True)
                if r.status_code == 200 and len(r.text) > 1000:
                    return r.text
                if r.status_code in (403, 429, 503):
                    self._switch_domain()
                    time.sleep(1)
                    continue
            except Exception as e:
                print(f"[JavDB] 请求失败({self.base_url}): {e}")
                self._switch_domain()
                time.sleep(1)
                continue
        return ""

    def _parse_list(self, html):
        """解析作品列表"""
        videos = []
        if not html:
            return videos
        pattern = re.compile(
            r'<a href="/v/([a-zA-Z0-9]+)" class="box" title="([^"]*)">[\s\S]*?'
            r'<img[^>]*src="([^"]+)"[\s\S]*?'
            r'<div class="video-title"><strong>([^<]*)</strong>\s*([^<]*)</div>',
            re.DOTALL
        )
        for m in pattern.finditer(html):
            vid, title, pic, code, name = m.groups()
            full_name = f"{code.strip()} {name.strip()}" if code.strip() else title.strip()
            videos.append({
                "vod_id": vid,
                "vod_name": full_name[:80],
                "vod_pic": pic.strip(),
                "vod_remarks": "",
            })
        return videos

    def homeContent(self, *args):
        try:
            classes = [{"type_id": c["type_id"], "type_name": c["type_name"]} for c in CATEGORIES]
            filters = {}
            for c in CATEGORIES:
                filters[c["type_id"]] = []
            html = self.fetch("/")
            videos = self._parse_list(html)
            return {"class": classes, "filters": filters, "list": videos}
        except Exception as e:
            print(f"[JavDB homeContent错误] {e}")
            classes = [{"type_id": c["type_id"], "type_name": c["type_name"]} for c in CATEGORIES]
            return {"class": classes, "filters": {}, "list": []}

    def homeVideoContent(self, *args):
        try:
            html = self.fetch("/")
            videos = self._parse_list(html)
            return {"page": 1, "pagecount": 999, "limit": 40, "total": len(videos), "list": videos}
        except Exception as e:
            print(f"[JavDB homeVideoContent错误] {e}")
            return {"page": 1, "pagecount": 1, "limit": 40, "total": 0, "list": []}

    def categoryContent(self, tid, pg, *args):
        try:
            try:
                page = int(pg) if pg else 1
            except (ValueError, TypeError):
                page = 1
            cat = next((c for c in CATEGORIES if c["type_id"] == tid), None)
            if not cat:
                return {"page": page, "pagecount": 1, "limit": 40, "total": 0, "list": []}
            path = f"/?vft={cat['vft']}"
            if page > 1:
                path += f"&page={page}"
            html = self.fetch(path)
            videos = self._parse_list(html)
            pagecount = 999 if len(videos) >= 40 else page
            return {"page": page, "pagecount": pagecount, "limit": 40, "total": len(videos), "list": videos}
        except Exception as e:
            print(f"[JavDB categoryContent错误] {e}")
            return {"page": 1, "pagecount": 1, "limit": 40, "total": 0, "list": []}

    def detailContent(self, ids, *args):
        try:
            if not ids:
                return {"list": []}
            if isinstance(ids, str):
                ids = [ids]
            videos = []
            for vod_id in ids:
                html = self.fetch(f"/v/{vod_id}")
                title = ""
                pic = f"https://c0.jdbstatic.com/covers/{vod_id[:2]}/{vod_id}.jpg"
                content = ""
                # 尝试从登录页提取标题
                m = re.search(r'<title>([^<]+)</title>', html)
                if m and "登入" not in m.group(1):
                    title = m.group(1).strip()
                if not title:
                    # 从og:title提取
                    m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
                    if m:
                        title = m.group(1).strip()
                if not title:
                    title = vod_id
                videos.append({
                    "vod_id": str(vod_id),
                    "vod_name": title[:80],
                    "vod_pic": pic,
                    "vod_content": content,
                    "vod_play_from": "JavDB在线",
                    "vod_play_url": f"在线观看${self.base_url}/v/{vod_id}",
                    "vod_remarks": "需登录查看播放源",
                })
            return {"list": videos}
        except Exception as e:
            print(f"[JavDB detailContent错误] {e}")
            return {"list": []}

    def playerContent(self, flag, id, vipFlags=None, *args):
        try:
            # id格式: "在线观看https://javdb580.com/v/xxx"
            url = id.replace("在线观看", "")
            return {
                "parse": 0,
                "jx": 0,
                "url": url,
                "header": {"User-Agent": UA, "Referer": self.base_url + "/"},
            }
        except Exception as e:
            print(f"[JavDB playerContent错误] {e}")
            return {"parse": 0, "jx": 0, "url": "", "header": {}}

    def searchContent(self, wd, pg, *args):
        try:
            try:
                page = int(pg) if pg else 1
            except (ValueError, TypeError):
                page = 1
            path = f"/search?q={urllib.parse.quote(wd)}"
            if page > 1:
                path += f"&page={page}"
            html = self.fetch(path)
            videos = self._parse_list(html)
            return {"page": page, "pagecount": 999, "limit": 40, "total": len(videos), "list": videos}
        except Exception as e:
            print(f"[JavDB searchContent错误] {e}")
            return {"page": 1, "pagecount": 1, "limit": 40, "total": 0, "list": []}

    def localProxy(self, path, *args):
        return [404, "text/plain", ""]

    def getDependence(self, *args):
        return ""


if __name__ == "__main__":
    s = Spider()
    s.init("{}")
    print("=== 首页 ===")
    home = s.homeContent()
    print(f"分类数: {len(home['class'])}, 视频数: {len(home['list'])}")
    for v in home["list"][:3]:
        print(f"  {v['vod_id']}: {v['vod_name'][:40]}")
    print("\n=== 分类(有码) ===")
    cat = s.categoryContent("censored", "1")
    print(f"视频数: {len(cat['list'])}")
    print("\n=== 搜索 ===")
    sch = s.searchContent("test", "1")
    print(f"搜索结果: {len(sch['list'])}")
