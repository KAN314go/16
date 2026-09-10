# -*- coding: utf-8 -*-
# 搜B研究所 四壳通用Python Spider
# 苹果CMS架构, WAF 403需safari17_2_ios指纹, 播放地址player_data.url未加密
# 双协议兼容继承(base.spider / 本地最小基类兜底)

import json
import re
import os
import sys

# 清除代理环境变量
for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
    os.environ.pop(k, None)

# 尝试导入curl_cffi, 失败则用requests
try:
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

try:
    import requests as req_requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def __init__(self):
            self.extend = {}
        def init(self, extend):
            self.extend = extend

# 未成年关键词过滤(铁律13)
MINOR_KEYWORDS = ['萝莉', '幼女', '少女', '童', 'teen', 'loli', 'schoolgirl', '豆蔻', '玉蕊', '碧玉', '稚子']


def is_minor_content(text):
    """检查文本是否包含未成年相关关键词"""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in MINOR_KEYWORDS)


class Spider(Spider):
    # 站点配置
    site_name = '搜B研究所'
    base_url = 'https://www.sbjys5.top'
    site_path = '/cn/home/web'
    ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1'

    # 分类列表(12个, 无未成年分类)
    categories = [
        {'type_id': '1', 'type_name': '人妻熟女'},
        {'type_id': '2', 'type_name': '强奸乱伦'},
        {'type_id': '3', 'type_name': '制服师生'},
        {'type_id': '4', 'type_name': '网红主播'},
        {'type_id': '20', 'type_name': '偷拍自拍'},
        {'type_id': '21', 'type_name': '自慰自淫'},
        {'type_id': '22', 'type_name': '国产专区'},
        {'type_id': '23', 'type_name': '虐待同性'},
        {'type_id': '24', 'type_name': '日韩精品'},
        {'type_id': '25', 'type_name': '欧美性爱'},
        {'type_id': '26', 'type_name': '卡通动漫'},
        {'type_id': '27', 'type_name': '三级伦理'},
    ]

    def init(self, extend):
        self.extend = extend
        if isinstance(extend, dict):
            if extend.get('siteUrl'):
                self.base_url = extend['siteUrl'].rstrip('/')
            if extend.get('direct'):
                pass

    def get_url(self, path):
        """构造完整URL"""
        if path.startswith('http'):
            return path
        if path.startswith('/'):
            return self.base_url + path
        return self.base_url + '/' + path

    def fetch(self, url, timeout=15):
        """HTTP请求, 优先curl_cffi safari17_2_ios指纹, 降级requests"""
        headers = {
            'User-Agent': self.ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        if HAS_CFFI:
            try:
                r = cffi_requests.get(url, impersonate='safari17_2_ios', headers=headers, timeout=timeout, verify=False)
                if r.status_code == 200:
                    return r.text
            except Exception:
                pass
        if HAS_REQUESTS:
            try:
                import urllib3
                urllib3.disable_warnings()
                r = req_requests.get(url, headers=headers, timeout=timeout, verify=False)
                if r.status_code == 200:
                    return r.text
            except Exception:
                pass
        # 最后降级urllib
        try:
            import ssl
            import urllib.request
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
            return resp.read().decode('utf-8', errors='replace')
        except Exception:
            return ''

    def homeContent(self, *args):
        """首页: 分类 + 推荐列表"""
        classes = [{'type_id': c['type_id'], 'type_name': c['type_name']} for c in self.categories]

        # 首页推荐列表
        filter_list = {}
        for cat in self.categories:
            filter_list[cat['type_id']] = []

        # 抓取首页最新视频
        html = self.fetch(self.base_url + self.site_path + '/')
        videos = self.parse_video_list(html)

        return {
            'class': classes,
            'list': videos,
            'filters': filter_list,
        }

    def categoryContent(self, tid, pg, *args):
        """分类页"""
        try:
            page = int(pg) if pg else 1
        except (ValueError, TypeError):
            page = 1

        url = f'{self.base_url}{self.site_path}/index.php/vod/type/id/{tid}.html?page={page}'
        html = self.fetch(url)
        videos = self.parse_video_list(html)

        # 解析分页信息
        pagecount = 1
        total = len(videos)
        limit = 20
        pg_match = re.search(r'共(\d+)页', html)
        if pg_match:
            pagecount = int(pg_match.group(1))
        total_match = re.search(r'共(\d+)条', html)
        if total_match:
            total = int(total_match.group(1))

        return {
            'page': page,
            'pagecount': pagecount,
            'limit': limit,
            'total': total,
            'list': videos,
        }

    def detailContent(self, ids, *args):
        """详情页: 本站点直接用play页, 从play页提取信息"""
        if not ids:
            return {'list': []}
        if isinstance(ids, str):
            ids = [ids]

        videos = []
        for vod_id in ids:
            # 构造play页URL
            play_url = f'{self.base_url}{self.site_path}/index.php/vod/play/id/{vod_id}/sid/1/nid/1.html'
            html = self.fetch(play_url)
            if not html:
                continue

            # 提取标题
            title = ''
            title_match = re.search(r'<title>([^<]+)</title>', html)
            if title_match:
                title = title_match.group(1).split('-')[0].strip()

            # 提取player_data
            vod_play_url = ''
            pd_match = re.search(r'player_data\s*=\s*(\{[^{}]*\})', html)
            if pd_match:
                try:
                    pd = json.loads(pd_match.group(1))
                    vod_play_url = pd.get('url', '')
                except (json.JSONDecodeError, KeyError):
                    pass

            # 提取分类/年份/地区等信息
            vod_year = ''
            vod_area = ''
            vod_remarks = ''
            info_text = re.sub(r'<[^>]+>', ' ', html)
            year_match = re.search(r'(\d{4})', info_text[:500])
            if year_match:
                vod_year = year_match.group(1)

            # 未成年过滤
            if is_minor_content(title):
                continue

            videos.append({
                'vod_id': str(vod_id),
                'vod_name': title,
                'vod_pic': '',
                'vod_year': vod_year,
                'vod_area': vod_area,
                'vod_remarks': vod_remarks,
                'vod_play_from': 'ckplayer',
                'vod_play_url': f'第1集${vod_play_url}',
            })

        return {'list': videos}

    def playerContent(self, flag, id, vipFlags=None, *args):
        """播放页: 直接返回m3u8地址"""
        play_url = f'{self.base_url}{self.site_path}/index.php/vod/play/id/{id}/sid/1/nid/1.html'
        html = self.fetch(play_url)

        play_url_final = ''
        if html:
            pd_match = re.search(r'player_data\s*=\s*(\{[^{}]*\})', html)
            if pd_match:
                try:
                    pd = json.loads(pd_match.group(1))
                    play_url_final = pd.get('url', '')
                except (json.JSONDecodeError, KeyError):
                    pass

        return {
            'parse': 0,
            'jx': 0,
            'url': play_url_final,
            'header': {
                'User-Agent': self.ua,
                'Referer': self.base_url + '/',
                'Origin': self.base_url,
            },
        }

    def searchContent(self, wd, pg, *args):
        """搜索页"""
        try:
            page = int(pg) if pg else 1
        except (ValueError, TypeError):
            page = 1

        # 未成年搜索词过滤
        if is_minor_content(wd):
            return {'page': page, 'pagecount': 0, 'limit': 20, 'total': 0, 'list': []}

        import urllib.parse
        search_url = f'{self.base_url}{self.site_path}/index.php/vod/search.html?wd={urllib.parse.quote(wd)}&page={page}'
        html = self.fetch(search_url)
        videos = self.parse_video_list(html)

        return {
            'page': page,
            'pagecount': 1,
            'limit': 20,
            'total': len(videos),
            'list': videos,
        }

    def parse_video_list(self, html):
        """解析视频列表: ul.list.g-clear > li.item > a.js-tongjic"""
        if not html:
            return []

        videos = []
        # 匹配li.item中的a标签
        items = re.findall(
            r"<li[^>]*class=['\"]item['\"][^>]*>\s*<a[^>]*href=['\"]([^'\"]+)['\"][^>]*title=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
            html, re.S
        )

        for href, title, content in items:
            # 未成年过滤
            if is_minor_content(title):
                continue

            # 提取vod_id
            vod_id = ''
            id_match = re.search(r'/vod/play/id/(\d+)', href)
            if id_match:
                vod_id = id_match.group(1)

            # 提取封面
            vod_pic = ''
            img_match = re.search(r"<img[^>]*src=['\"]([^'\"]+)['\"]", content) or re.search(r"<img[^>]*data-src=['\"]([^'\"]+)['\"]", content)
            if img_match:
                vod_pic = img_match.group(1)
                if vod_pic.startswith('//'):
                    vod_pic = 'https:' + vod_pic

            # 提取备注/清晰度
            vod_remarks = ''
            remark_match = re.search(r"class=['\"][^'\"]*(?:title|name|remarks)[^'\"]*['\"][^>]*>([^<]+)<", content)
            if remark_match:
                vod_remarks = remark_match.group(1).strip()

            videos.append({
                'vod_id': vod_id,
                'vod_name': title.strip(),
                'vod_pic': vod_pic,
                'vod_remarks': vod_remarks,
            })

        return videos

    def getDependence(self, *args):
        return ''

    def localProxy(self, path, *args):
        return [404, 'text/plain', '']
