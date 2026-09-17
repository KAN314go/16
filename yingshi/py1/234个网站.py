# -*- coding: utf-8 -*-
# ============================================================
# 卓成影视 234 站二级聚合 Spider (www.cczhuocheng.cn)
#
# 结构:
#   一级 : 主站 www.cczhuocheng.cn 作为导航入口
#          homeContent 返回 234 个友情链接子站作为一级分类
#   二级 : 点入任一子站 -> 该子站分类列表(带图) -> 详情 -> 播放(m3u8 直链)
#
# 机制(基于全量实测):
#   - 234 个子站为同源站群, 仅主题皮肤不同 (le/baofeng/pomoho/pptv/fun/
#     sohu/bilibili/netease 等), 数据结构完全一致
#   - 二级列表统一路由: /Video/List/{tid}?page={N}
#     (tid: 1电影 2电视剧 28短剧 3综艺 4动漫 46美女)
#   - 详情页: /{前缀}/{id}.html 或 /vod/{id}
#     播放组 <div class="d-ep-group" data-src="{源}"> 内
#     <a href="/play/{id}?src={源}&ep={集}">集数名</a>
#   - 播放页: /play/{id}?src={源}&ep={集} 内嵌
#     var epData=[{"src":"...","eps":[{"label":"...","url":"m3u8直链"}]}]
#
# 直接放入 TVBox/影视TV/OK影视 等支持 Python 采集的播放器 py 目录即可
# ============================================================

import json
import re
import requests
from urllib.parse import urljoin, quote, urlparse, parse_qs

from base.spider import Spider


class Spider(Spider):

    name = '卓成234站'
    host = 'https://www.cczhuocheng.cn'

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36'
        ),
        'Accept-Language': 'zh-CN,zh;q=0.9',
    }

    # 一级入口: 主站 234 个友情链接子站 (站名, 地址)
    SITES = [
    ("观看电视剧百度", "https://www.333lao.com"),
    ("菠萝蜜在线", "https://www.toumiyr.cn"),
    ("gogogo高清在线观看+视频", "https://w.lwns.cn"),
    ("小小水蜜桃", "https://w.yuyijiaoyu.cn"),
    ("免费高清观看电视剧百度云", "https://www.yzqtsg.cn"),
    ("天狼网", "https://18kankan.com"),
    ("秋霞网", "https://www.bjmeisida.com"),
    ("电影理论", "https://www.wandcreativemedia.com"),
    ("神马影院", "https://www.ys117.com"),
    ("B站大片网", "https://wxjhotel.com"),
    ("免费观看电视剧大全", "https://w.gzzswy.cn"),
    ("黑人电影", "https://w.jlsysyjy.cn"),
    ("草莓社区", "https://www.qqheppmu.com"),
    ("三年在线高清", "https://daxiai.com"),
    ("免费高清视频", "https://w.ofsys.cn"),
    ("西瓜影院", "https://www.yuecolor.com"),
    ("yy影院在线观看", "https://www.kjyjk.com"),
    ("波兰电影", "https://zmwd.cn"),
    ("yy影院免费观看电视剧百度", "https://www.tjzrjy.cn"),
    ("亲密电影", "https://hangting.com.cn"),
    ("韩剧网", "https://www.wpcckoe.cn"),
    ("波兰电影", "https://tjhaojia.com"),
    ("人人美剧官网", "https://w.shanghaimingkun.com"),
    ("达达兔", "https://www.156169.com"),
    ("免费yy影院在线观看", "https://www.yasibrandy.com"),
    ("人人看", "https://fingertip.net.cn"),
    ("韩剧网", "https://www.yysstt.cn"),
    ("新上映的电影", "https://zszt05.cn"),
    ("大叔电影", "https://gzwdzs.cn"),
    ("电影法国", "https://didaoys.com"),
    ("电影大片", "https://hyjk.cloud"),
    ("日本电视剧网", "https://w.junyao2018.cn"),
    ("日本高清电视剧百度云下载电影", "https://www.156972.com"),
    ("大师兄影视", "https://www.xinwangmai.com"),
    ("免费大片视频网站", "https://www.369875.cn"),
    ("蜜桃网", "https://www.xiaozhiorg.cn"),
    ("1688私人影院", "https://qqshuka.cn"),
    ("欧美电影网", "https://www.jsxindali.cn"),
    ("菠萝蜜在线", "https://yanzhaocs.com"),
    ("秋霞网", "https://w.156972.com"),
    ("中文在线百度", "https://w.wfdczy.cn"),
    ("国产日本高清", "https://www.lnwfw.com"),
    ("新视觉影视", "https://日本免费高清观"),
    ("桃传媒", "https://www.henfen.cn"),
    ("电影大全2026", "https://www.fjroe.com.cn"),
    ("无人区电影", "https://csxhschool.cn"),
    ("秋霞电影网", "https://www.fuhuaji1.com"),
    ("八哥电影网", "https://fuhuaji1.com"),
    ("在线免费观看", "https://w.congcongai.com"),
    ("红杏直播", "https://w.geniuskid.cn"),
    ("大师兄影视", "https://www.ulqjpaw.cn"),
    ("DVD电影网", "https://m.yanzhaocs.com"),
    ("高清影视大全", "https://www.tourguide.net.cn"),
    ("8090电影网", "https://www.hongzhixuexiao.cn"),
    ("影院在线", "https://www.szcrdc.com"),
    ("秋霞影视", "https://www.yanzhaocs.com"),
    ("电影在线", "https://www.tubaoshi.com"),
    ("疯狂的老师", "https://w.tysgple.cn"),
    ("免费网站", "https://w.pubc.cn"),
    ("日本高清电视剧百度云下载", "https://www.utnygbt.cn"),
    ("4480影视网", "https://nengcuo.com"),
    ("日本高清电视剧百度云", "https://hebeitvet.com"),
    ("蘑菇视频", "https://www.jishujun.cn"),
    ("日本高清电视剧百度云", "https://www.cctvyzyp.com"),
    ("yy影院观看免费百度", "https://www.didaoys.com"),
    ("美国大片", "https://www.kflyhg.com.cn"),
    ("日韩小电影", "https://w.szpgaji.cn"),
    ("看电影网", "https://w.cczhuocheng.cn"),
    ("日本高清电视剧百度云下载", "https://www.lmynizp.cn"),
    ("出轨2", "https://sdzlfz.com"),
    ("日本高清观看电视剧百度云", "https://bjmeisida.com"),
    ("西瓜视频", "https://www.zyysxx.net"),
    ("YY6090电视剧电影网", "https://www.kuagejing.cn"),
    ("飞鸟藏爱泰剧", "https://www.tjhaojia.com"),
    ("奇优影院", "https://www.truling.cn"),
    ("免费高清大全在线观看完整版电影", "https://w.2-35.cn"),
    ("西瓜影院", "https://w.szbiotech.com.cn"),
    ("万达电影院", "https://www.lhnt.cn"),
    ("YY4480影视", "https://t8brands.com"),
    ("日本高清电视剧百度云下载", "https://www.hebeitvet.com"),
    ("电影大片", "https://www.matlabtutor.cn"),
    ("免费观看电视剧", "https://www.youxuanba.net"),
    ("三年在线高清", "https://funnycoding.cn"),
    ("风驰影院", "https://w.yzqtsg.cn"),
    ("韩剧日剧观看", "https://w.ahchudi.cn"),
    ("8090电影网", "https://www.yixiguan.cn"),
    ("6080新视觉电影网", "https://youkuyingyuan.com"),
    ("日本高清电视剧百度云", "https://www.hyjk.cloud"),
    ("片看片网日本高清观看电视剧", "https://www.fishcs.cn"),
    ("电影网yy影院在线观看", "https://www.youkuyingyuan.com"),
    ("西瓜视频在线", "https://jyqqzx.com.cn"),
    ("九门免费观看", "https://www.szbiotech.com.cn"),
    ("神马达达兔影院", "https://w.jianoujiaju.cn"),
    ("电影", "https://www.002110.cn"),
    ("小小影院", "https://333lao.com"),
    ("金桔影院", "https://w.zyysxx.net"),
    ("亲密电影", "https://www.2-35.cn"),
    ("yy影院在线百度", "https://www.t8brands.com"),
    ("外国动作电影大片", "https://vobao0731.cn"),
    ("高清视频免费观看", "https://www.cczhuocheng.cn"),
    ("光棍电影", "https://hbrttx.com.cn"),
    ("秋霜电视剧", "https://www.002234.cn"),
    ("好看视频", "https://qixco.com"),
    ("原来神马影院", "https://w.jishujun.cn"),
    ("小小影院", "https://www.166291.com"),
    ("yy影院高清电视剧百度", "https://www.sdzlfz.com"),
    ("80电影天堂网", "https://jsccxf.cn"),
    ("电视剧2026", "https://www.pubc.cn"),
    ("中天影院", "https://loadcellword.com"),
    ("yy影院在线观看免费观看电视剧百度", "https://www.zzzh3.cn"),
    ("人人影视", "https://zhotudou.com"),
    ("丝瓜视频在线观看", "https://w.syjlmy.cn"),
    ("神马影院", "https://w.hongzhixuexiao.cn"),
    ("小小水蜜桃", "https://www.166857.com"),
    ("神马影院", "https://www.nengcuo.com"),
    ("yy影院在线百度", "https://www.wxjhotel.com"),
    ("最新电影", "https://www.geniuskid.cn"),
    ("韩国电影片", "https://apsar2019.org.cn"),
    ("大地电影", "https://www.huiminshucai.cn"),
    ("国产日本高清", "https://whatchr.com"),
    ("在线观看网站", "https://w.166857.com"),
    ("优蜜传媒", "https://w.fjroe.com.cn"),
    ("日本免费高清电视剧百度云", "https://www.gsnrrk.com"),
    ("私人影院", "https://m.uumob.com"),
    ("真人直播视频影视", "https://www.zmwd.cn"),
    ("金桔影院", "https://www.wfdczy.cn"),
    ("日本免费高清百度云", "https://www.hangting.com.cn"),
    ("yy影院在线", "https://www.uumob.com"),
    ("飞鸟藏爱泰剧", "https://jysanlong.com"),
    ("韩国电影片", "https://w.ulqjpaw.cn"),
    ("韩国大片", "https://w.xiaozhiorg.cn"),
    ("成全影视", "https://www.vmtud.cn"),
    ("成全影视", "https://m.buyuqi.net"),
    ("神马网站", "https://www.fingertip.net.cn"),
    ("日本高清电视剧百度云", "https://www.junyao2018.cn"),
    ("成全观看", "https://www.zszt05.cn"),
    ("神马影院", "https://www.buyuqi.net"),
    ("被窝电影", "https://www.zhizhenjy.cn"),
    ("中文版字幕在线观看电视剧百度云", "https://w.utnygbt.cn"),
    ("爱情电影网", "https://w.yysstt.cn"),
    ("野马电影高清日本免费电视剧百度云", "https://www.nynlhnd.cn"),
    ("免费看片网", "https://xinwangmai.com"),
    ("日本免费电视剧百度云下载", "https://crc14086.com"),
    ("韩国电影片", "https://www.shanghaimingkun.com"),
    ("片_日本高清电视剧百度云下载", "https://www.qqshuka.cn"),
    ("yy影院观看百度", "https://www.ecabes.com"),
    ("青苹果影院", "https://www.xyqsmz.cn"),
    ("红桃视频", "https://w.lmynizp.cn"),
    ("日剧大全", "https://w.tjzrjy.cn"),
    ("温柔的诱惑电视剧", "https://www.weich520.com"),
    ("日本免费高清观看电视剧", "https://yasibrandy.com"),
    ("日本高清电视剧百度云", "https://m.hebeitvet.com"),
    ("神马影院", "https://www.ofsys.cn"),
    ("80电影天堂网", "https://www.csxhschool.cn"),
    ("yy影院在线观看", "https://www.iehao.com"),
    ("成全视频", "https://www.8023v.cn"),
    ("YY影院在线观看免费观看电视剧百度", "https://w.lhnt.cn"),
    ("高清影视", "https://w.fushengmuju.com"),
    ("九七电影", "https://www.lwns.cn"),
    ("秋霜电视剧", "https://kjyjk.com"),
    ("日韩在线观看", "https://www.dhsfe.com"),
    ("电影看片", "https://www.ynlxd.cn"),
    ("西瓜影院", "https://www.daxiai.com"),
    ("日本免费高清观看电视剧", "https://369875.cn"),
    ("神马视频", "https://w.yixiguan.cn"),
    ("丁香花网", "https://w.sdboning.cn"),
    ("日本免费高清百度云下载", "https://www.gzzswy.cn"),
    ("星火电视海外版", "https://ys117.com"),
    ("贝乐影视", "https://w.jkhbzs.cn"),
    ("西瓜视频", "https://www.ibo100.com"),
    ("yy影院在线免费", "https://www.18kankan.com"),
    ("6080新觉伦电影", "https://henfen.cn"),
    ("人鱼免费观看", "https://www.lvyidamen.com.cn"),
    ("DVD电影网", "https://w.huanqiukj.cn"),
    ("日本高清观看电视剧百度云下载", "https://www.f8220.cn"),
    ("人人剧场", "https://iehao.com"),
    ("如意事", "https://w.hnszsj.com"),
    ("日本免费高清观看电视剧百度云下载", "https://www.hblinsheng.cn"),
    ("yy影院在线电视剧", "https://www.mayun5.com"),
    ("如意事", "https://tourguide.net.cn"),
    ("电影免费观看平台", "https://www.csweib.cn"),
    ("秋霞理论", "https://szcrdc.com"),
    ("QQLIVE在线", "https://www.gzwdzs.cn"),
    ("优蜜传媒", "https://ecabes.com"),
    ("免费看片网", "https://w.genrit.cn"),
    ("小小影院", "https://www.167276.com"),
    ("免费视频网", "https://www.nmghytd.com"),
    ("无人区电影", "https://www.funnycoding.cn"),
    ("免费高清视频", "https://www.dmlyfood.cn"),
    ("秋霞在线", "https://cctvyzyp.com"),
    ("yy影院在线百度", "https://www.bsly.com.cn"),
    ("6080新视觉电影", "https://buyuqi.net"),
    ("九九电视剧", "https://w.167276.com"),
    ("海鸥影视大全", "https://w.yexiaoyou.cn"),
    ("樱桃网", "https://www.167368.com"),
    ("yy影院在线", "https://www.macosmao.com"),
    ("电影在线观看", "https://www.jyqqzx.com.cn"),
    ("在线播放电影", "https://www.ycfxsy.cn"),
    ("糖心视频", "https://kuagejing.cn"),
    ("美播私密影院", "https://www.jysanlong.com"),
    ("免费大片视频网站", "https://uumob.com"),
    ("电视剧2026", "https://w.gsnrrk.com"),
    ("三年在线观看", "https://w.ycfxsy.cn"),
    ("日本免费电视剧百度云下载", "https://www.congcongai.com"),
    ("百度云电视剧在线", "https://m.whatchr.com"),
    ("秋霜电视剧", "https://www.vobao0731.cn"),
    ("小黄人大电影", "https://www.yexiaoyou.cn"),
    ("福利电影", "https://www.hbrttx.com.cn"),
    ("电影法国", "https://www.whatchr.com"),
    ("日本免费高清观看电视剧百度云下载", "https://tubaoshi.com"),
    ("免费观看高清完整版大全", "https://w.vmtud.cn"),
    ("花生电影院", "https://w.dmlyfood.cn"),
    ("日本免费高清观看电视剧百度云下载", "https://www.tysgple.cn"),
    ("最新电影网", "https://m.zhotudou.com"),
    ("免费看欧美片", "https://www.jsccxf.cn"),
    ("茶杯狐", "https://www.genrit.cn"),
    ("6900理论", "https://www.loadcellword.com"),
    ("西瓜视频", "https://www.zhotudou.com"),
    ("好看视频", "https://www.xingcheyi.cn"),
    ("短剧免费观看", "https://w.nynlhnd.cn"),
    ("在线播放电影", "https://w.csweib.cn"),
    ("小狐狸视频网", "https://www.szpgaji.cn"),
    ("日本电影", "https://nmghytd.com"),
    ("琪琪影视", "https://dhsfe.com"),
    ("秋霞网日本电视剧百度云", "https://www.hnszsj.com"),
    ("神马影院", "https://www.apsar2019.org.cn"),
    ("yy影院免费电视剧", "https://www.qixco.com"),
    ("日本免费电视剧百度云", "https://www.aachati.cn"),
    ("动漫免费观看大全", "https://w.nscws.cn"),
    ("八度电影院", "https://w.lvyidamen.com.cn"),
    ("大叔电影", "https://www.nscws.cn"),
    ("韩剧在线", "https://mayun5.com"),
    ("yy影院在线观看", "https://www.crc14086.com"),
    ("gogogo高清在线观看", "https://www.jkhbzs.cn"),
]

    # 每个子站的分类筛选 (tid)
    CATE_VALUE = [
        {'n': '电影', 'v': '1'},
        {'n': '电视剧', 'v': '2'},
        {'n': '短剧', 'v': '28'},
        {'n': '综艺', 'v': '3'},
        {'n': '动漫', 'v': '4'},
        {'n': '美女', 'v': '46'},
    ]

    # 视频详情前缀白名单 (站群各主题使用的详情路径)
    DETAIL_RE = re.compile(
        r'^/(vod|meinv|kehuan|yingshi|aiqing|hanju|juqing|dianying|zongyi|'
        r'dongman|jingji|xuanyi|dianshi|xiju|shipin|yingyuan|level|tv|movie|'
        r'video|detail|look|watch|yp|dt|yl)/(\d+)(\.html)?$')

    # 非视频链接前缀(过滤)
    SKIP_PREFIX = (
        'w', 'news', 'artlist', 'Video', 'List', 'actors', 'actor',
        'sitemap', 'random', 'latest', 'all-special-pages', 'css', 'js',
    )

    def init(self, extend=""):
        self._origins = {}
        for i, (_, u) in enumerate(self.SITES):
            self._origins[i + 1] = self._origin_of(u)
        self._origins[0] = self.host  # 0 号 = 主站

    def getName(self):
        return self.name

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def close(self):
        self.destroy()

    # ==================== 公共请求 ====================
    def fetch(self, url, timeout=12, referer=None):
        try:
            h = dict(self.headers)
            if referer:
                h['Referer'] = referer
            return requests.get(url, headers=h, timeout=timeout, verify=False)
        except Exception:
            return None

    def get_text(self, url, timeout=12, referer=None, origin=None):
        r = self.fetch(url, timeout=timeout, referer=referer or origin)
        if r is None:
            return ''
        return r.text

    # ==================== 通用工具 ====================
    @staticmethod
    def _origin_of(url):
        try:
            p = urlparse(url)
            return '%s://%s' % (p.scheme or 'https', p.netloc)
        except Exception:
            return ''

    def abs_url(self, u, origin):
        u = (u or '').strip()
        if not u:
            return ''
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('http://') or u.startswith('https://'):
            return u
        if u.startswith('/'):
            return origin + u
        return origin + '/' + u

    @staticmethod
    def strip_tags(s):
        if not s:
            return ''
        s = re.sub(r'<script.*?</script>', '', s, flags=re.S)
        s = re.sub(r'<style.*?</style>', '', s, flags=re.S)
        s = re.sub(r'<[^>]+>', '', s)
        for a, b in (('&nbsp;', ' '), ('\xa0', ' '), ('&amp;', '&'),
                     ('&gt;', '>'), ('&lt;', '<'), ('&quot;', '"'),
                     ('&#x3000;', ' '), ('&hellip;', '...')):
            s = s.replace(a, b)
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    @staticmethod
    def parse_pagecount(html, default=1):
        pages = re.findall(r'[?&]page=(\d+)', html)
        nums = [int(p) for p in pages if p.isdigit()]
        if nums:
            return max(nums)
        return default

    # ==================== 列表卡片解析 ====================
    def parse_list_items(self, html, site_key, origin):
        """解析二级子站列表页/搜索页/首页的卡片

        返回 [{vod_id:'SI{key}__{详情路径}', vod_name, vod_pic, vod_remarks}]
        详情路径由该站的实际详情前缀自动匹配, 兼容 30+ 种主题
        """
        items = re.findall(r'<a href="([^"]*)"[^>]*>(.*?)</a>', html, re.S)
        result = []
        seen = set()
        auto_re = self._discover_detail_re(html)
        for href, body in items:
            href = href.strip()
            # 卡片特征: 含图片或标题元素; 纯文字导航链接(分类/页脚)不算视频卡
            has_card = bool(re.search(r'<img[^>]+>', body, re.I)) or \
                bool(re.search(r'<h[34][^>]*>', body, re.I)) or \
                bool(re.search(r'class="[^"]*(?:name|poster|pic|thumb)[^"]*"', body, re.I))
            if not has_card:
                continue
            m = self.DETAIL_RE.match(href)
            if not m and auto_re:
                m = auto_re.match(href)
            if not m:
                continue
            if m.group(1) in self.SKIP_PREFIX:
                continue
            path = href
            vod_id = 'SI%d__%s' % (site_key, path)
            if vod_id in seen:
                continue
            seen.add(vod_id)

            pic = ''
            for attr in ('data-original', 'data-src', 'src'):
                mm = re.search(r'<img[^>]+%s="([^"]+)"' % attr, body)
                if mm:
                    pic = self.abs_url(mm.group(1), origin)
                    break

            name = ''
            mm = re.search(r'<h[34][^>]*>(.*?)</h[34]>', body, re.S)
            if mm:
                name = self.strip_tags(mm.group(1))
            if not name:
                mm = re.search(r'class="([^"]*name[^"]*)"[^>]*>(.*?)</div>', body, re.S)
                if mm:
                    name = self.strip_tags(mm.group(2))
            if not name:
                mm = re.search(r'<img[^>]+alt="([^"]+)"', body)
                if mm:
                    name = mm.group(1).strip()

            remarks = ''
            mm = re.search(r'class="meta"[^>]*>\s*<span[^>]*>(.*?)</span>', body, re.S)
            if mm:
                remarks = self.strip_tags(mm.group(1))[:40]

            result.append({
                'vod_id': vod_id,
                'vod_name': (name or '影片%s' % m.group(2))[:80],
                'vod_pic': pic,
                'vod_remarks': remarks,
            })
        return result

    def _discover_detail_re(self, html):
        """自动发现该站详情前缀: 统计带卡片特征的 href 中最高频 /前缀/{N}(.html)? 模式

        用于白名单未覆盖的站, 返回 compiled regex 或 None
        """
        counter = {}
        for href, body in re.findall(r'<a href="([^"]*)"[^>]*>(.*?)</a>', html, re.S):
            href = href.strip()
            if not re.search(r'<img[^>]+>', body, re.I):
                continue
            m = re.match(r'^/([a-z]+)/(\d+)(\.html)?$', href)
            if not m:
                continue
            if m.group(1) in self.SKIP_PREFIX:
                continue
            counter[m.group(1)] = counter.get(m.group(1), 0) + 1
        if not counter:
            return None
        prefix = max(counter, key=counter.get)
        return re.compile(r'^/%s/(\d+)(\.html)?$' % re.escape(prefix))

    # ==================== 一级: 首页 ====================
    def homeContent(self, filter):
        classes = []
        filters = {}
        for i, (site_name, _) in enumerate(self.SITES, 1):
            classes.append({'type_id': str(i), 'type_name': '%03d.%s' % (i, site_name)})
            filters[str(i)] = [{
                'key': 'cate',
                'name': '分类',
                'value': self.CATE_VALUE,
            }]

        vlist = []
        html = self.get_text(self.host, timeout=10, origin=self.host)
        if html:
            vlist = self.parse_list_items(html, 0, self.host)
        if not vlist:
            html = self.get_text(self.host + '/Video/List/1', timeout=10, origin=self.host)
            vlist = self.parse_list_items(html, 0, self.host)

        return {
            'class': classes,
            'filters': filters,
            'list': vlist[:60],
        }

    def homeVideoContent(self):
        html = self.get_text(self.host + '/Video/List/1', timeout=10, origin=self.host)
        return {'list': self.parse_list_items(html, 0, self.host)[:40]}

    # ==================== 二级: 子站分类列表 ====================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            site_key = int(str(tid).strip())
            page = max(1, int(pg))
        except (TypeError, ValueError):
            return {'list': [], 'page': 1, 'pagecount': 1}

        origin = self._origins.get(site_key, '')
        if not origin:
            return {'list': [], 'page': page, 'pagecount': 1}

        cate = '1'
        if isinstance(extend, dict):
            cate = str(extend.get('cate') or '1')
        elif isinstance(extend, str) and extend.strip():
            cate = extend.strip()

        url = '%s/Video/List/%s?page=%d' % (origin, cate, page)
        html = self.get_text(url, timeout=12, origin=origin)
        vlist = self.parse_list_items(html, site_key, origin)

        if not vlist:
            # 该分类无效/失败 -> 回退子站首页
            html = self.get_text(origin, timeout=12, origin=origin)
            vlist = self.parse_list_items(html, site_key, origin)

        pagecount = self.parse_pagecount(html, page) if html else page

        return {
            'list': vlist,
            'page': page,
            'pagecount': pagecount,
            'limit': 36,
            'total': pagecount * 36,
        }

    # ==================== 详情 ====================
    def detailContent(self, ids):
        if isinstance(ids, list):
            ids = ids[0]
        ids = str(ids or '').strip()
        if not ids:
            return {'list': []}

        site_key, path = self._split_vid(ids)
        origin = self._origins.get(site_key, '')
        if not origin:
            return {'list': []}

        url = self.abs_url(path, origin)
        html = self.get_text(url, timeout=12, origin=origin)
        if not html:
            return {'list': []}

        vod = self.parse_detail(html, site_key, origin, path)
        if vod:
            return {'list': [vod]}
        return {'list': []}

    @staticmethod
    def _split_vid(vid):
        """'SI{key}__{path}' -> (key, path); 裸路径 -> (0, path)"""
        if vid.startswith('SI') and '__' in vid:
            head, _, path = vid.partition('__')
            try:
                return int(head[2:]), path
            except ValueError:
                pass
        return 0, vid

    def parse_detail(self, html, site_key, origin, path):
        title = ''
        m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
        if m:
            title = self.strip_tags(m.group(1))

        pic = ''
        m = re.search(r'class="d-detail-poster".*?<img[^>]+src="([^"]+)"', html, re.S)
        if not m:
            m = re.search(r'<img[^>]+src="([^"]+)"', html)
        if m:
            pic = self.abs_url(m.group(1), origin)

        info = {}
        for m in re.finditer(r'<p><b[^>]*>([^<：:]+)[：:]?</b>(.*?)</p>', html, re.S):
            label = self.strip_tags(m.group(1))
            value = self.strip_tags(m.group(2))
            if label:
                info[label] = value

        type_name = info.get('类型', '')
        director = info.get('导演', '')
        actor = info.get('主演', '')
        area = info.get('地区', '')
        year = info.get('年份', '')
        remarks = info.get('状态', '') or info.get('总集数', '')
        if remarks == '暂无':
            remarks = ''

        content = ''
        m = re.search(r'剧情介绍</h2>(.*?)</div>\s*</div>', html, re.S)
        if m:
            content = self.strip_tags(m.group(1))

        play_from = []
        play_url = []
        groups = re.findall(
            r'class="d-ep-group"[^>]*data-src="([^"]+)"(.*?)'
            r'(?=class="d-ep-group"|<!--|<div class="bl-section"|<div class="fn-section"|<div class="le-section"|$)', html, re.S)
        if not groups:
            m = re.search(r'class="d-ep-group"[^>]*>(.*?)(?=<!--|<div class="[a-z]+-section"|$)', html, re.S)
            if m:
                groups = [('', m.group(1))]

        for src_name, body in groups:
            src_name = src_name.strip()
            eps = []
            for m in re.finditer(
                    r'<a[^>]+href="(/play/\d+\?src=[^"&]+&ep=\d+)"[^>]*>(.*?)</a>',
                    body, re.S):
                eps.append('%s$SI%d__%s' % (
                    self.strip_tags(m.group(2)) or '播放', site_key, m.group(1)))
            if eps:
                play_from.append(src_name or '线路%d' % (len(play_from) + 1))
                play_url.append('#'.join(eps))

        if not play_from:
            seen = set()
            eps = []
            for m in re.finditer(
                    r'href="(/play/\d+\?src=[^"&]+&ep=\d+)"[^>]*>(.*?)</a>',
                    html, re.S):
                if m.group(1) in seen:
                    continue
                seen.add(m.group(1))
                eps.append('%s$SI%d__%s' % (
                    self.strip_tags(m.group(2)) or '播放', site_key, m.group(1)))
            if eps:
                play_from.append('默认线路')
                play_url.append('#'.join(eps))

        vod_id = 'SI%d__%s' % (site_key, path)
        return {
            'vod_id': 'SI%d__%s' % (site_key, ''),
            'vod_name': title or '',
            'vod_pic': pic,
            'type_name': type_name,
            'vod_year': year,
            'vod_area': area,
            'vod_remarks': remarks[:20],
            'vod_actor': actor,
            'vod_director': director,
            'vod_content': content[:800],
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }

    # ==================== 搜索 ====================
    def searchContent(self, key, quick=False, pg=1):
        try:
            page = max(1, int(pg))
        except (TypeError, ValueError):
            page = 1
        url = '%s/search?wd=%s&page=%d' % (self.host, quote(key, safe=''), page)
        html = self.get_text(url, timeout=12, origin=self.host)
        vlist = self.parse_list_items(html, 0, self.host)
        pagecount = self.parse_pagecount(html, page) if html else page
        return {
            'list': vlist,
            'page': page,
            'pagecount': pagecount,
            'limit': 24,
            'total': pagecount * 24,
        }

    # ==================== 播放 ====================
    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {'parse': 1, 'playUrl': '', 'url': ''}

        site_key, path = self._split_vid(id)
        origin = self._origins.get(site_key, '')
        if not origin:
            return {'parse': 1, 'playUrl': '', 'url': ''}

        play_page = self.abs_url(path, origin)
        src = ''
        ep = 0
        try:
            q = parse_qs(urlparse(play_page).query)
            src = (q.get('src') or [''])[0]
            ep = (q.get('ep') or [0])[0]
        except Exception:
            pass

        html = self.get_text(play_page, timeout=12, origin=origin)
        real = ''
        if html:
            m = re.search(r'var\s+epData\s*=\s*(\[.*?\])\s*;', html, re.S)
            if not m:
                m = re.search(r'var\s+epData\s*=\s*(\[.*?\])', html, re.S)
            if m:
                try:
                    data = json.loads(m.group(1))
                    real = self.pick_ep_url(data, src, ep)
                except Exception:
                    real = ''

        if real:
            real = real.replace('\\/', '/')
            if real.startswith('//'):
                real = 'https:' + real
            if '.m3u8' in real.lower():
                real = self.expand_master(real, origin)
            return {
                'parse': 0,
                'playUrl': '',
                'url': real,
                'header': {'User-Agent': self.headers['User-Agent'],
                           'Referer': origin + '/'},
            }

        return {'parse': 1, 'playUrl': '', 'url': play_page}

    @staticmethod
    def pick_ep_url(data, src, ep):
        try:
            ep = int(ep)
        except (TypeError, ValueError):
            ep = 0
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get('src') == src:
                    eps = item.get('eps') or []
                    if 0 <= ep < len(eps):
                        u = eps[ep].get('url') if isinstance(eps[ep], dict) else eps[ep]
                        if u:
                            return str(u)
            for item in data:
                if isinstance(item, dict):
                    eps = item.get('eps') or []
                    if eps and 0 <= ep < len(eps):
                        u = eps[ep].get('url') if isinstance(eps[ep], dict) else eps[ep]
                        if u:
                            return str(u)
        return ''

    def expand_master(self, m3u8_url, origin):
        """master 级联 m3u8 (含 #EXT-X-STREAM-INF) 取第一条子流; 失败回落"""
        try:
            r = self.fetch(m3u8_url, timeout=10, referer=origin + '/')
            if r is None:
                return m3u8_url
            text = r.text or ''
            if '#EXT-X-STREAM-INF' not in text:
                return m3u8_url
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    return urljoin(m3u8_url.strip(), line)
        except Exception:
            pass
        return m3u8_url

    def localProxy(self, param):
        return [200, 'text/plain', 'ok']


if __name__ == '__main__':
    Spider().run()