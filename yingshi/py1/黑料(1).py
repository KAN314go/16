# -*- coding: utf-8 -*-
"""
黑料网 TVBox 四壳通用 Spider
站点: https://gvtb8.eyhvcvbt.cc/ (heiliao.com 镜像)
协议: TVBox / 影视仓 / OK影视 / PickTV 四壳通用
特性: 纯正则解析零依赖 / 敏感词古典映射脱敏 / 未成年内容跳过 / 广告过滤 / m3u8多线路
"""

import re
import json
import urllib.parse

# ============================================================
# HTTP 层: requests 优先, urllib 降级, 忽略 SSL 证书
# ============================================================
try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

import ssl
import urllib.request
import urllib.error

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/131.0.0.0 Safari/537.36")


def _http_get(url, referer=None, timeout=15):
    """统一 GET 请求, 返回 (status_code, html_text)"""
    headers = {"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if referer:
        headers["Referer"] = referer
    if _HAS_REQUESTS:
        try:
            r = requests.get(url, headers=headers, timeout=timeout,
                             verify=False, allow_redirects=True)
            return r.status_code, r.text
        except Exception:
            pass
    # urllib 降级
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)
        data = resp.read()
        # 尝试 utf-8, 失败用 gbk
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("gbk", errors="replace")
        return resp.status, text
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


# ============================================================
# 敏感词古典映射脱敏 (铁律11)
# ============================================================
CLASSICAL_MAP = {
    # 网站类型
    "成人": "风月", "色情": "春宫", "淫秽": "猥亵", "黄色": "春宫",
    "激情": "云雨", "做爱": "云雨", "性交": "交欢", "性爱": "云雨",
    "欲": "情思", "高潮": "云端",
    # 行为
    "偷拍": "窥帘", "偷窥": "窥帘", "乱伦": "禁脔", "强奸": "强占",
    "轮奸": "群辱", "迷奸": "迷占", "群交": "合卺", "自慰": "弄玉",
    "口交": "含朱", "口活": "含朱", "肛交": "后庭", "车震": "车行",
    "野战": "郊合", "出轨": "翻墙", "偷情": "私会", "通奸": "私通",
    "嫖娼": "寻花", "卖淫": "卖身", "性骚扰": "轻薄", "猥亵": "猥亵",
    "露阴": "曝玉", "走光": "泄春", "露点": "泄玉",
    # 身体
    "巨乳": "丰盈", "爆乳": "丰盈", "美乳": "玉兔", "乳": "玉兔",
    "胸": "酥胸", "臀": "玉臀", "屁股": "玉臀", "玉足": "莲步",
    "脚": "莲步", "腿": "玉腿", "裸体": "玉体", "全裸": "玉体",
    "半裸": "半褪", "裸露": "玉体", "精液": "元阳", "精子": "元阳",
    "阴道": "幽处", "阴户": "幽处", "阴茎": "玉茎", "阳具": "玉茎",
    # 身份
    "熟女": "徐娘", "人妻": "罗敷", "少妇": "艳妇", "御姐": "玉人",
    "护士": "药女", "教师": "先生", "老师": "先生", "医生": "郎中",
    "警察": "捕快", "军人": "军爷", "秘书": "掌印", "老板": "东家",
    "丈夫": "夫君", "妻子": "拙荆", "情人": "相好", "小三": "外遇",
    "二奶": "外室", "妓女": "花娘", "处女": "处子", "初夜": "破瓜",
    "学生": "书生", "大学生": "书生", "高中生": "书生",
    # 服饰
    "丝袜": "丝履", "网袜": "网履", "内衣": "亵衣", "内裤": "亵裤",
    "情趣": "风月", "春药": "催情", "制服": "官衣", "SM": "调教",
    # 画质
    "无码": "素纱", "有码": "遮面", "高清": "高清",
    # 地域
    "国产": "华夏", "日韩": "东瀛", "欧美": "西洋", "港台": "香江",
    # 内容类型
    "黑料": "秘闻", "爆料": "趣闻", "吃瓜": "趣闻", "丑闻": "秘闻",
    "塌房": "陨落", "网红": "红人", "明星": "名流",
    "短剧": "短剧", "综艺": "百戏", "影视": "光影",
    # 其他
    "赌博": "孤注", "毒品": "药石", "暴力": "杀伐", "恐怖": "幽冥",
    "广告": "告示", "约炮": "相约", "交友": "相识",
    # 补充露骨词
    "操": "云雨", "狂操": "云雨", "猛操": "云雨", "连操": "云雨",
    "喷水": "泄津", "潮吹": "泄津", "酮体": "玉体", "胴体": "玉体",
    "啪啪": "云雨", "打炮": "云雨", "上床": "同榻", "开房": "投宿",
    "口爆": "含朱", "颜射": "敷面", "内射": "中出", "中出": "中出",
    "吞精": "吞津", "喝精": "饮津", "乳交": "玉兔", "足交": "莲步",
    "调教": "调教", "奴": "仆", "母狗": "雌仆", "骚": "娇",
    "浪": "娇", "荡": "娇", "贱": "庸", "婊子": "花娘",
    "妓女": "花娘", "小姐": "娘子", "外围": "交际", "小三": "外遇",
    "出轨": "翻墙", "偷情": "私会", "通奸": "私通",
}

# 未成年关键词 (铁律13, 命中即跳过, "学生"不纳入)
_MINOR_KEYWORDS = [
    "萝莉", "幼女", "少女", "童", "未成年", "teen", "loli",
    "schoolgirl", "小女", "孩童", "幼齿", "豆蔻", "玉蕊", "碧玉",
]


def desensitize(text):
    """敏感词古典映射脱敏, 未成年内容返回空字符串"""
    if not text:
        return ""
    # 先检测未成年
    lower = text.lower()
    for kw in _MINOR_KEYWORDS:
        if kw.lower() in lower:
            return ""
    # 古典映射替换 (长词优先)
    result = text
    for k in sorted(CLASSICAL_MAP.keys(), key=len, reverse=True):
        if k in result:
            result = result.replace(k, CLASSICAL_MAP[k])
    return result


def _is_minor(text):
    """判断是否含未成年关键词"""
    if not text:
        return False
    lower = text.lower()
    for kw in _MINOR_KEYWORDS:
        if kw.lower() in lower:
            return True
    return False


# ============================================================
# Spider 主类 (独立类, 不继承 base.spider)
# ============================================================
class Spider:
    # 站点配置
    rawSite = "https://gvtb8.eyhvcvbt.cc"
    siteUrl = "https://gvtb8.eyhvcvbt.cc"
    HOST = "https://gvtb8.eyhvcvbt.cc"

    # 分类定义: tid 必须纯数字/英文 (TVBox兼容性)
    # 分类名已预脱敏, 不再二次替换
    # (tid, 分类名, 路径)
    CATEGORIES = [
        ("home", "首页推荐", "/"),
        ("ysdj", "光影短剧", "/ysdj/"),
        ("ycsq", "原创影像", "/ycsq/"),
        ("whhl", "红人秘闻", "/whhl/"),
        ("fczq", "反差社区", "/fczq/"),
        ("mxcw", "名流秘闻", "/mxcw/"),
        ("xycg", "书生趣闻", "/xycg/"),
        ("lsdg", "历史旧闻", "/lsdg/"),
        ("jqrm", "近期热门", "/jqrm/"),
        ("jrrs", "今日热点", "/jrrs/"),
        ("hlcg", "秘闻趣闻", "/hlcg/"),
        ("djbl", "独家秘闻", "/djbl/"),
        ("gchl", "华夏秘闻", "/gchl/"),
        ("sjb", "事件簿", "/sjb/"),
        ("mrds", "每日大事", "/mrds/"),
        ("shxw", "社会新闻", "/shxw/"),
        ("zbjx", "直播精选", "/zbjx/"),
    ]

    def __init__(self, extend=None):
        self.extend = extend or {}
        # 支持 ext.proxy / ext.siteUrl 覆盖
        if isinstance(self.extend, dict):
            if self.extend.get("proxy"):
                self.siteUrl = self.extend["proxy"]
                self.HOST = self.extend["proxy"]
            elif self.extend.get("siteUrl"):
                self.siteUrl = self.extend["siteUrl"]
                self.HOST = self.extend["siteUrl"]
            if self.extend.get("direct"):
                self.siteUrl = self.rawSite
                self.HOST = self.rawSite

    # ----------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------
    def _full_url(self, path):
        """拼接完整 URL"""
        if path.startswith("http"):
            return path
        if path.startswith("//"):
            return "https:" + path
        return self.HOST + path

    def _parse_list(self, html):
        """
        解析视频列表页, 返回 [{vod_id, vod_name, vod_pic}]
        过滤广告项 (tjtagmanager class) 和未成年内容
        """
        results = []
        # 匹配 video-item 块
        # 结构: <div class="video-item"> ... <a href="/archives/ID/" ...> ... <img z-image-loader-url="PIC" alt="TITLE">
        pattern = re.compile(
            r'<div class="video-item">(.*?)</div>\s*</div>\s*</div>',
            re.DOTALL
        )
        # 更宽松的匹配: 找所有 archives 链接 + 对应图片
        item_pattern = re.compile(
            r'<a[^>]*href="(/archives/(\d+)/)"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        # 检查是否是广告 (tjtagmanager)
        ad_pattern = re.compile(r'class="[^"]*tjtagmanager[^"]*"')

        for m in item_pattern.finditer(html):
            link = m.group(1)
            vid = m.group(2)
            block = m.group(0)
            # 跳过广告
            if ad_pattern.search(block):
                continue
            # 提取封面图
            pic_m = re.search(r'z-image-loader-url="([^"]+)"', block)
            pic = pic_m.group(1) if pic_m else ""
            # 提取标题: 优先 h3.title, 其次 alt
            title_m = re.search(r'<h3[^>]*class="title"[^>]*>(.*?)</h3>', block, re.DOTALL)
            if title_m:
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
            else:
                alt_m = re.search(r'alt="([^"]+)"', block)
                title = alt_m.group(1) if alt_m else vid
            # 未成年跳过
            if _is_minor(title):
                continue
            # 脱敏
            title = desensitize(title)
            if not title:
                continue
            # 封面图处理
            if pic and not pic.startswith("http"):
                pic = self._full_url(pic)
            results.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
            })
        return results

    def _get_page_url(self, tid, page):
        """根据分类 tid 和页码生成 URL"""
        cat = None
        for c in self.CATEGORIES:
            if c[0] == tid:
                cat = c
                break
        if not cat:
            cat = self.CATEGORIES[0]
        path = cat[2]
        if page <= 1:
            return self._full_url(path)
        # 分页: 首页 /page/N/, 分类页 /category/page/N/
        if path == "/":
            return self._full_url(f"/page/{page}/")
        return self._full_url(f"{path}page/{page}/")

    # ----------------------------------------------------------
    # 四壳协议 13 接口
    # ----------------------------------------------------------

    def init(self, extend=None):
        """初始化, 返回空 (Spider 不需要特殊初始化)"""
        if extend:
            self.__init__(extend)
        return ""

    def homeContent(self, filter=False):
        """首页内容: 返回分类 + 筛选 + 首页视频"""
        classes = []
        for tid, name, path in self.CATEGORIES:
            # 分类名已预脱敏, 直接使用
            classes.append({"type_id": tid, "type_name": name})

        # 筛选 (dict, 铁律8)
        filters = {}
        # 该站无额外筛选, 给一个空结构
        for c in classes:
            filters[c["type_id"]] = []

        # 首页视频列表
        _, html = _http_get(self._full_url("/"))
        video_list = self._parse_list(html)

        return {
            "class": classes,
            "filters": filters,
            "list": video_list,
        }

    def homeVideoContent(self):
        """首页推荐视频 (部分壳单独调用)"""
        _, html = _http_get(self._full_url("/"))
        return {"list": self._parse_list(html)}

    def categoryContent(self, tid, page=1, filter=None, extend=None):
        """分类内容"""
        # 兼容 v 值和名称两种传参
        cat = None
        for c in self.CATEGORIES:
            if c[0] == tid or c[1] == tid:
                cat = c
                break
        if not cat:
            cat = self.CATEGORIES[0]

        url = self._get_page_url(cat[0], int(page))
        _, html = _http_get(url, referer=self._full_url("/"))
        video_list = self._parse_list(html)

        # 判断是否有下一页 (简单判断: 有 page 链接)
        has_next = bool(re.search(rf'/page/{int(page) + 1}/', html))
        page_count = int(page) + 1 if has_next else int(page)

        return {
            "page": int(page),
            "pagecount": page_count,
            "limit": 20,
            "total": len(video_list) * page_count,
            "list": video_list,
        }

    def detailContent(self, ids):
        """
        详情内容: ids 是 list/tuple, 必须遍历 (铁律8)
        从 DPlayer config 提取 m3u8 播放地址
        """
        if not ids:
            return {"list": []}
        if isinstance(ids, str):
            ids = [ids]

        detail_list = []
        for vid in ids:
            url = self._full_url(f"/archives/{vid}/")
            _, html = _http_get(url, referer=self._full_url("/"))
            if not html:
                continue

            # 标题
            title_m = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
            title = title_m.group(1).strip() if title_m else vid
            title = re.sub(r'[-_|].*$', '', title).strip()
            title = desensitize(title) or vid

            # 封面图
            pic_m = re.search(r'z-image-loader-url="([^"]+)"', html)
            pic = pic_m.group(1) if pic_m else ""
            if pic and not pic.startswith("http"):
                pic = self._full_url(pic)

            # 从 DPlayer config 提取视频地址
            play_urls = []  # [(线路名, m3u8_url)]
            config_m = re.search(r"config='(\{.*?\})'", html, re.DOTALL)
            if config_m:
                try:
                    config_str = config_m.group(1)
                    # 处理 HTML 实体
                    config_str = config_str.replace("&quot;", '"').replace("&amp;", "&")
                    config = json.loads(config_str)
                    video_cfg = config.get("video", {})
                    # 多线路
                    urls = video_cfg.get("urls", [])
                    if urls and isinstance(urls, list):
                        for u in urls:
                            line_name = u.get("name", "线路")
                            line_url = u.get("url", "")
                            if line_url:
                                play_urls.append((line_name, line_url))
                    # 主地址
                    main_url = video_cfg.get("url", "")
                    if main_url and not any(u[1] == main_url for u in play_urls):
                        play_urls.insert(0, ("主线", main_url))
                except (json.JSONDecodeError, Exception):
                    # JSON 解析失败, 尝试正则提取 m3u8
                    m3u8_m = re.findall(r'"url":"(https?://[^"]+\.m3u8[^"]*)"', config_m.group(1))
                    for i, u in enumerate(m3u8_m):
                        u = u.replace("\\/", "/")
                        play_urls.append((f"线路{i+1}", u))

            # 如果 config 没找到, 尝试全局正则提取 m3u8
            if not play_urls:
                m3u8_all = re.findall(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', html)
                for i, u in enumerate(m3u8_all):
                    u = u.replace("\\/", "/")
                    if u not in [p[1] for p in play_urls]:
                        play_urls.append((f"线路{i+1}", u))

            # 未成年跳过
            if _is_minor(title):
                continue

            # 构建播放源
            # TVBox标准格式: vod_play_from 用 $$$ 分隔线路
            # vod_play_url 每条线路用 $$$ 分隔, 线路内部 集数名$URL 用 # 分隔多集
            if play_urls:
                vod_play_from = "$$$".join([p[0] for p in play_urls])
                vod_play_url = "$$$".join([f"第1集${p[1]}" for p in play_urls])
            else:
                vod_play_from = "暂无"
                vod_play_url = ""

            # 描述 (从 meta description 提取)
            desc_m = re.search(r'<meta name="description" content="([^"]*)"', html)
            desc = desc_m.group(1) if desc_m else ""
            desc = desensitize(desc)

            # 发布时间
            date_m = re.search(r'datePublished["\s:]+([0-9T:+-]+)', html)
            pub_date = date_m.group(1)[:10] if date_m else ""

            detail_list.append({
                "vod_id": str(vid),
                "vod_name": title,
                "vod_pic": pic,
                "type_name": "视频",
                "vod_year": pub_date[:4] if pub_date else "",
                "vod_area": "",
                "vod_remarks": pub_date,
                "vod_actor": "",
                "vod_director": "",
                "vod_content": desc,
                "vod_play_from": vod_play_from,
                "vod_play_url": vod_play_url,
            })

        return {"list": detail_list}

    def playerContent(self, flag, id, vipFlags=None):
        """
        播放内容: 返回 m3u8 直链 + 防盗链 header
        flag 是播放源名, id 是播放地址 (TVBox已从 第1集$URL 中解析出URL)
        """
        url = id or ""
        # 兼容: 有些壳传入 "第1集$URL" 格式, 需要提取URL
        if "$" in url and not url.startswith("http"):
            parts = url.split("$", 1)
            if len(parts) == 2:
                url = parts[1]
        # 如果 id 不是 http 开头, 说明传的是 vod_id, 需要重新取详情
        if not url.startswith("http"):
            detail = self.detailContent([url])
            if detail.get("list"):
                play_url = detail["list"][0].get("vod_play_url", "")
                if play_url:
                    # 取第一条线路的播放地址: 第1集$URL
                    first_line = play_url.split("$$$")[0]
                    if "$" in first_line:
                        url = first_line.split("$", 1)[1]
                    else:
                        url = first_line.replace("第1集", "")

        header = {
            "User-Agent": _UA,
            "Referer": self.rawSite + "/",
            "Origin": self.rawSite,
        }

        return {
            "parse": 0,
            "jx": 0,
            "url": url,
            "header": header,
        }

    def searchContent(self, wd, page=1):
        """搜索内容: 搜索页为Vue动态渲染, 从热门搜索静态链接提取"""
        if not wd:
            return {"page": 1, "pagecount": 1, "limit": 20, "total": 0, "list": []}
        keyword = urllib.parse.quote(wd)
        url = self._full_url(f"/index/search?keyword={keyword}")
        _, html = _http_get(url, referer=self._full_url("/"))

        video_list = []
        # 搜索页 result-item 是Vue模板({ {item.title} }), 标题需从热门搜索静态链接提取
        # 热门搜索项结构: <li class="tag-item"><a href="/archives/ID/">标题</a></li>
        hot_pattern = re.compile(
            r'<a[^>]*href="/archives/(\d+)/"[^>]*>(.*?)</a>', re.DOTALL
        )
        seen = set()
        for m in hot_pattern.finditer(html):
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if not title or _is_minor(title):
                continue
            title = desensitize(title)
            if title:
                video_list.append({
                    "vod_id": vid,
                    "vod_name": title,
                    "vod_pic": "",
                })

        return {
            "page": int(page),
            "pagecount": int(page),
            "limit": 20,
            "total": len(video_list),
            "list": video_list,
        }

    # ----------------------------------------------------------
    # 本地图片代理 (封面图 CDN 防盗链)
    # ----------------------------------------------------------
    def localProxy(self, params):
        """
        本地代理: 接收壳的图片代理请求, 返回 [code, content_type, content]
        params 是 dict, 含 url 参数
        """
        if not params or "url" not in params:
            return [404, "text/plain", ""]
        target_url = params["url"]
        headers = {
            "User-Agent": _UA,
            "Referer": self.rawSite + "/",
        }
        try:
            if _HAS_REQUESTS:
                r = requests.get(target_url, headers=headers, timeout=10,
                                 verify=False, allow_redirects=True)
                content_type = r.headers.get("Content-Type", "image/jpeg")
                return [r.status_code, content_type, r.content]
            else:
                req = urllib.request.Request(target_url, headers=headers)
                resp = urllib.request.urlopen(req, timeout=10, context=_SSL_CTX)
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                return [resp.status, content_type, resp.read()]
        except Exception:
            return [404, "text/plain", ""]

    # ----------------------------------------------------------
    # 其他接口 (四壳协议要求)
    # ----------------------------------------------------------
    def getDependence(self):
        """依赖声明, 返回字符串不为 None"""
        return "re,json,urllib.parse,urllib.request,ssl"

    def getName(self):
        """Spider 名称"""
        return "黑料网"

    def getApp(self):
        """App 标识"""
        return "heiliao"

    def check(self, flags):
        """检查播放源, 返回 True 表示支持"""
        return True

    def destroy(self):
        """销毁, 释放资源"""
        pass


# ============================================================
# 独立爬虫 API (命令行调试用)
# ============================================================
if __name__ == "__main__":
    import sys
    sp = Spider()

    def _print_list(title, data):
        print(f"\n{'='*50}")
        print(f"  {title}")
        print(f"{'='*50}")
        if isinstance(data, dict):
            for k, v in data.items():
                if k == "list":
                    print(f"  list 数量: {len(v)}")
                    for i, item in enumerate(v[:5]):
                        print(f"  [{i+1}] {item.get('vod_name','')[:40]} | id={item.get('vod_id','')}")
                    if len(v) > 5:
                        print(f"  ... 共 {len(v)} 条")
                elif k == "class":
                    print(f"  class 数量: {len(v)}")
                    for c in v:
                        print(f"    - {c.get('type_id')}: {c.get('type_name')}")
                elif k == "filters":
                    print(f"  filters: dict (keys={len(v)})")
                else:
                    print(f"  {k}: {v}")
        else:
            print(data)

    print("黑料网 TVBox Spider 自测")
    print(f"站点: {sp.HOST}")

    # 1. init
    print("\n[1/6] init ...")
    sp.init({})
    print("  OK")

    # 2. homeContent
    print("\n[2/6] homeContent ...")
    home = sp.homeContent()
    _print_list("homeContent", home)

    # 3. categoryContent
    print("\n[3/6] categoryContent (ysdj, page=1) ...")
    cat = sp.categoryContent("ysdj", 1)
    _print_list("categoryContent", cat)

    # 4. detailContent
    if home.get("list"):
        first_id = home["list"][0]["vod_id"]
        print(f"\n[4/6] detailContent (id={first_id}) ...")
        detail = sp.detailContent([first_id])
        if detail.get("list"):
            d = detail["list"][0]
            print(f"  标题: {d.get('vod_name','')}")
            print(f"  封面: {d.get('vod_pic','')[:80]}")
            print(f"  播放源: {d.get('vod_play_from','')}")
            play_url = d.get("vod_play_url", "")
            if play_url:
                first_line = play_url.split("#")[0]
                print(f"  首地址: {first_line[:100]}")
            print(f"  描述: {d.get('vod_content','')[:60]}")
        else:
            print("  无详情数据")

    # 5. searchContent
    print("\n[5/6] searchContent (wd=短剧) ...")
    search = sp.searchContent("短剧")
    _print_list("searchContent", search)

    # 6. playerContent
    if detail.get("list") and detail["list"][0].get("vod_play_url"):
        first_url = detail["list"][0]["vod_play_url"].split("$$$")[0]
        if "$" in first_url:
            first_url = first_url.split("$", 1)[1]
        print(f"\n[6/6] playerContent ...")
        player = sp.playerContent("主线", first_url)
        print(f"  parse: {player.get('parse')}")
        print(f"  url: {player.get('url','')[:100]}")
        print(f"  header: {player.get('header')}")

    print("\n" + "="*50)
    print("  自测完成")
    print("="*50)