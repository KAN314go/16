# coding=utf-8
# ============================================================================
# whos.tv（以图搜片 / AV 识图搜索引擎）四壳 Python Spider
#   站点：https://whos.tv
#   分类体系：8 大帧分类（服装/地点/特写/姿势/行为/表情/道具/其他）
#             + 每类 50 个标签作为二级分类（共 400 个，取自官方 /frames/tags 索引）
#             + 演员库（AV 百科，23894 位 / 1328 页，二级为排序：
#               人气最高/作品最多/评分最高/最新出道）
#   解析路线：列表 /ajax/frames?type_id=&label_id=&page= （HTML 卡片，无盾）
#             详情 /videos/{番号}（免登录，页内下发 m3u8）
#             搜索 /result?search=关键词&page=N（24/页，封面 hex 异或解出）
#             演员索引 /actresses/page-N（18/页，?sort= 可排序，实测 ?page= 无效）
#             演员档案 /actresses/{名字}，作品 /actresses/{名字}/page-N（12/页）
#             另有 影片库 /videos/page-N（?sort= 可排序）、排行榜 /ranking/video
#   播放：/videos/{slug} 内 data-preview-source 的 .m3u8（AES-128，直链无防盗链）
#   广告预检: has_ads=False, score=0
#     （实测 jur-175 全片 m3u8：1825 分片 / 7301 秒，无 /ad/ 类路径、
#      无跨 CDN 贴片、无 0.x 秒空帧，故 has_ads=False；清洗链路仍完整保留）
# ============================================================================
import os
import re
import sys
import ssl
import time
import base64
import threading
from urllib.parse import quote, unquote, urljoin

# ---- 依赖兜底（壳内无 requests 时走标准库 urllib） ----
_PYLIBS = os.path.expanduser("~/pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)

try:
    import requests as _requests
    _HAS_REQUESTS = True
except Exception:
    _requests = None
    _HAS_REQUESTS = False

# 通道一：curl_cffi —— 伪装浏览器 TLS 指纹直过 CF 托管挑战（实测 100% 通过）
try:
    from curl_cffi import requests as _curl_requests
    _HAS_CURL_CFFI = True
except Exception:
    _curl_requests = None
    _HAS_CURL_CFFI = False

# ---- requests + Chrome TLS 指纹：本机实测「cipher 序列 + EC 曲线」两项一起设才过 ----
# 实测矩阵（whos.tv/ajax 业务接口，同一出口 IP）：
#   requests 原样            → 403 挑战
#   cipher 序列(8+4 套)       → 403 挑战
#   cipher + set_ecdh_curve   → 200 直过 ✅（命门就是 EC 曲线这一项）
#   cipher + ALPN             → 403
# 也就是说：不必引指纹库，标准库 ssl 就能把这站的盾过掉。
CHROME_CIPHERS = (
    'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:'
    'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:'
    'ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:'
    'ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:AES128-GCM-SHA256:AES256-GCM-SHA384'
)
CHROME_CURVE = 'prime256v1'


def _make_fp_adapter():
    """给 requests 装上 Chrome 的 TLS 指纹（cipher 顺序 + EC 曲线）"""
    from requests.adapters import HTTPAdapter

    class _FP(HTTPAdapter):
        def _ctx(self):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            try:
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            except Exception:
                pass
            ctx.set_ciphers(CHROME_CIPHERS)
            try:
                ctx.set_ecdh_curve(CHROME_CURVE)   # ← 命门：少了这句必被挑战
            except Exception:
                pass
            return ctx

        def init_poolmanager(self, *a, **kw):
            kw['ssl_context'] = self._ctx()
            return super().init_poolmanager(*a, **kw)

        def proxy_manager_for(self, *a, **kw):
            kw['ssl_context'] = self._ctx()
            return super().proxy_manager_for(*a, **kw)

    return _FP()

# 通道二：设备浏览器桥 —— Android 壳内用 WebView 自己把挑战走完，脚本层只取渲染结果
try:
    from java import jclass as _jclass, dynamic_proxy as _dynamic_proxy
    _HAS_JAVA_BRIDGE = True
except Exception:
    _jclass = None
    _dynamic_proxy = None
    _HAS_JAVA_BRIDGE = False

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


# ============================== 站点常量 ==============================
HOST = 'https://whos.tv'
FRAMES_API = '/ajax/frames'
VIDEO_PATH = '/videos/{}'
VIDEO_LIST = '/videos'
RANKING = '/ranking/video'
RESULT = '/result'
IMG_CDN = 'https://f.hersav.me'
STREAM_CDN = 'https://v.hersav.me'

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36')
MOBILE_UA = ('Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36')

PER_PAGE_FRAMES = 8       # /ajax/frames 每页实测 8 张帧卡
PER_PAGE_VIDEOS = 12      # /videos 每页实测 12 张影片卡
PER_PAGE_SEARCH = 24      # /result 每页实测 24 张影片卡
CACHE_TTL = 180

# 8 大帧分类：(type_id, 中文名, 站点 slug, [(label_id, 标签名), ...])
# 数据取自官方标签索引页 /frames/tags（每类 50 个热门标签）
WHOS_CATS = [
    (1, '服装', 'clothes', [
        (49, '全裸'), (255, '裸体'), (168, '白色衬衫'), (248, '白色上衣'), (116, '白衬衫'), (98, '黑色丝袜'),
        (251, '职业装'), (568, '半裸'), (152, '黑色短裙'), (1110, '白色内裤'), (476, '内衣'), (308, '衬衫'),
        (243, '学生制服'), (363, '女仆装'), (547, '水手服'), (125, '短裙'), (509, 'JK制服'), (260, '白色背心'),
        (862, '黑色内衣'), (910, '黑色蕾丝内衣'), (970, '白色T恤'), (2097, '黑色连裤袜'), (447, '高跟鞋'), (1494, '黑色内裤'),
        (750, '格纹短裙'), (2021, '领带'), (103, '蕾丝内衣'), (835, '白色内衣'), (298, '制服'), (2594, '浅色上衣'),
        (4403, '裸露上身'), (587, '西装'), (134, '丝袜'), (153, '黑色高跟鞋'), (139, '丁字裤'), (31, '校服'),
        (1755, '深色短裙'), (430, '内裤'), (1844, '格子短裙'), (1097, '黑色上衣'), (1582, '白色蕾丝内衣'), (107, '吊带袜'),
        (4591, '肉色丝袜'), (71, '比基尼'), (4844, '白色吊带背心'), (909, '白色文胸'), (4709, '上身赤裸'), (39, '护士服'),
        (372, '针织衫'), (190538, '黑色西装外套'),
    ]),
    (2, '地点', 'location', [
        (2, '室内'), (50, '卧室'), (268, '床上'), (161, '客厅'), (57, '办公室'), (72, '浴室'),
        (1169, '室内卧室'), (154, '酒店房间'), (519, '户外'), (32, '教室'), (557, '室内沙发'), (190165, '沙发'),
        (82, '和室'), (360, '厨房'), (370, '酒店'), (190151, '床'), (3007, '酒店卧室'), (505, '餐厅'),
        (603, '摄影棚'), (868, '客厅沙发'), (1117, '室内客厅'), (2838, '日式房间'), (344, '走廊'), (364, '房间'),
        (426, '更衣室'), (1080, '卧室床铺'), (387, '街道'), (2072, '室内走廊'), (682, '榻榻米房间'), (422, '车内'),
        (190530, '榻榻米'), (751, '室内房间'), (6210, '沙发上'), (64, '按摩室'), (1064, '诊室'), (191072, '室外'),
        (2031, '户外街道'), (1237, '电车'), (8076, '休息室'), (851, '窗边'), (9, '病房'), (376, '浴缸'),
        (186, '暗室'), (573, '洗手间'), (11395, '室内工作室'), (708, '公园'), (888, '玄关'), (26292, '卧室床'),
        (195, '室内摄影棚'), (2958, '酒店客房'),
    ]),
    (3, '特写', 'closeup', [
        (45, '脸部特写'), (196, '面部特写'), (51, '胸部特写'), (473, '上半身特写'), (100, '中景'), (178, '臀部特写'),
        (894, '阴部特写'), (1132, '下体特写'), (1845, '乳房特写'), (740, '头部特写'), (190220, '女性面部特写'), (289, '口交特写'),
        (10, '全身'), (18, '胸部'), (3899, '背部特写'), (108, '全景'), (20809, '面部表情特写'), (118, '私处特写'),
        (3053, '口部特写'), (187, '半身'), (2703, '手部特写'), (190265, '女性上半身特写'), (127, '臀部'), (1358, '腿部特写'),
        (200711, '中景镜头'), (25, '面部'), (403, '上半身'), (42202, '脸部表情特写'), (731, '躯干特写'), (3981, '人物面部特写'),
        (191089, '性交部位特写'), (33, '脸部'), (86, '躯干'), (190271, '两人上半身特写'), (1134, '侧脸特写'), (190461, '两人面部特写'),
        (191442, '表情特写'), (1314, '嘴部特写'), (468, '下半身特写'), (190986, '口交部位特写'), (27109, '眼睛特写'), (222, '半身特写'),
        (208274, '女优面部特写'), (3744, '阴茎特写'), (9422, '肩部特写'), (190994, '人物半身特写'), (609, '私处'), (339, '特写'),
        (190698, '女子上半身特写'), (5530, '巨乳特写'),
    ]),
    (4, '姿势', 'pose', [
        (190229, '口交'), (94, '后入式'), (11, '骑乘位'), (4, '坐姿'), (78, '站立'), (352, '后入'),
        (170, '仰卧'), (163, '跪姿'), (208238, '抽插'), (26, '俯身'), (190524, '自慰'), (193241, '性交'),
        (1026, '男上女下'), (190312, '手淫'), (104, '站姿'), (434, '跨坐'), (208229, '舔逼'), (66, '仰卧开腿'),
        (190859, '前戏'), (1024, '正面'), (628, '骑乘'), (564, 'M字开腿'), (137, '传教士式'), (19023, '传教士体位'),
        (190317, '无'), (194061, '多人运动'), (194197, '指交'), (198579, '抚摸'), (190879, '多人混战'), (1067, '正常位'),
        (1158, '开腿'), (192559, '亲密接触'), (193500, '群交'), (194258, '爱抚'), (190752, '深吻'), (128, '弯腰'),
        (194877, '接吻'), (193903, '性交中'), (767, '侧卧'), (208279, '揉胸'), (234360, '性行为'), (659, '躺姿'),
        (209032, '抠逼'), (3581, '站立后入'), (140, '俯卧'), (198578, '亲吻'), (1552, '躺卧'), (190405, '多人性行为'),
        (208532, '撸管'), (765, 'M字腿'),
    ]),
    (5, '行为', 'action', [
        (12, '性交'), (74, '口交'), (87, '性行为'), (5, '交谈'), (334, '注视'), (20, '揉乳'),
        (517, '抚摸'), (366, '凝视'), (119, '自慰'), (79, '展示'), (356, '对视'), (549, '注视镜头'),
        (305, '舔阴'), (485, '群交'), (346, '交流'), (142, '性爱'), (157, '面对镜头'), (374, '接吻'),
        (770, '挑逗'), (532, '手交'), (245, '指交'), (143, '摆拍'), (315, '亲吻'), (634, '互动'),
        (849, '手淫'), (238, '对话'), (559, '呻吟'), (662, '调情'), (1160, '舔舐'), (395, '谈话'),
        (716, '调教'), (565, '插入'), (2774, '三人行'), (927, '俯视'), (165, '多人性交'), (812, '访谈'),
        (936, '脱衣'), (439, '舔乳'), (275, '捆绑'), (584, '性交行为'), (1311, '揉胸'), (361, '聊天'),
        (611, '按摩'), (793, '暴露'), (719, '多人性行为'), (281, '抚摸胸部'), (216, '猥亵'), (1250, '足交'),
        (2314, '凝视镜头'), (1469, '吐舌'),
    ]),
    (6, '表情', 'expression', [
        (42, '专注'), (83, '迷离'), (88, '享受'), (144, '微笑'), (113, '平静'), (13, '投入'),
        (122, '闭眼'), (524, '沉醉'), (350, '诱惑'), (101, '陶醉'), (464, '痛苦'), (53, '愉悦'),
        (2364, '沉浸'), (6, '严肃'), (4498, '顺从'), (5447, '神情迷离'), (1674, '微张嘴'), (703, '张嘴'),
        (158, '自然'), (5976, '张嘴呻吟'), (95, '羞涩'), (612, '温柔'), (5762, '沉迷'), (6735, '神情专注'),
        (3529, '闭眼享受'), (1054, '张嘴喘息'), (1170, '不可见'), (130, '喘息'), (668, '害羞'), (613, '兴奋'),
        (1390, '娇羞'), (192155, '呻吟'), (606, '迷醉'), (12936, '面无表情'), (68, '销魂'), (190266, '注视'),
        (3354, '放松'), (32718, '微张嘴唇'), (28, '忧郁'), (5189, '眼神迷离'), (190454, '沉浸感'), (6419, '迷茫'),
        (4986, '神情恍惚'), (3319, '享受表情'), (530, '期待'), (1302, '开心'), (20088, '交谈中'), (571, '笑容'),
        (994, '大笑'), (4724, '迷乱'),
    ]),
    (7, '道具', 'prop', [
        (145, '床'), (146, '枕头'), (131, '沙发'), (37, '眼镜'), (190247, '无'), (390, '手机'),
        (159, '台灯'), (1181, '震动棒'), (190176, '项链'), (674, '按摩棒'), (797, '项圈'), (1063, '绳索'),
        (1585, '女仆头饰'), (953, '口罩'), (322, '手提包'), (301, '手铐'), (377, '阴茎'), (562, '眼罩'),
        (191809, '护士帽'), (54, '床铺'), (190207, '高跟鞋'), (286, '酒杯'), (190196, '润滑油'), (22, '颈圈'),
        (96, '办公桌'), (650, '床单'), (132, '盆栽'), (442, '椅子'), (4795, '麻绳'), (1186, '假阳具'),
        (660, '被褥'), (713, '毛巾'), (448, '文件夹'), (1367, '听诊器'), (1270, '餐具'), (1625, '黑色头套'),
        (11199, '吸尘器'), (246, '课桌'), (470, '床垫'), (472, '黑板'), (190969, '围裙'), (190770, '领带'),
        (585, '窗帘'), (648, '领结'), (265, '酒瓶'), (1910, '智能手机'), (306, '榻榻米'), (974, '背包'),
        (2409, '单肩包'), (120, '电脑'),
    ]),
    (8, '其他', 'other', [
        (76, '马赛克'), (586, '长发'), (368, '多人'), (14953, '光线明亮'), (1953, '日本AV'), (190318, '无'),
        (5190, '马赛克遮挡'), (582, '有码'), (661, '汗水'), (326, '中文字幕'), (81, '巨乳'), (690, '熟女'),
        (290, '成人内容'), (190548, '马赛克遮挡阴部'), (794, '无码'), (330, '昏暗灯光'), (2873, '出汗'), (975, '光线昏暗'),
        (16078, '阴部打码'), (172, '打码'), (173, '第一人称视角'), (4227, '室内灯光'), (1192, '亚洲女性'), (14251, '私处打码'),
        (357, 'POV视角'), (44, '角色扮演'), (687, '短发'), (3380, '阴部马赛克'), (296, '剧情'), (9108, '光线柔和'),
        (748, '自然光'), (645, '亚洲人'), (48, '第一视角'), (563, '露点'), (727, 'POV'), (12287, '马赛克处理'),
        (23, '露乳'), (90, '字幕'), (208332, '画面有打码'), (239, '居家'), (3421, '亚洲'), (191263, '室内光线明亮'),
        (38909, '下体打码'), (602, '职场'), (208404, '画面有马赛克'), (2407, '成人'), (279, 'BDSM'), (969, '日语字幕'),
        (123, '湿身'), (6107, '无遮挡'),
    ]),
]

# 额外内容板块
EXTRA_CATS = [
    ('videos', '影片库'),
    ('ranking', '排行榜'),
]

# ---- 演员库（AV 百科） ----
ACTRESS_LIST = '/actresses'
ACTRESS_PATH = '/actresses/{}'
PER_PAGE_ACTRESS = 18        # /actresses 每页实测 18 张演员卡
ACTRESS_WORK_PAGE = 12       # 演员档案页作品每页实测 12 部
ACTRESS_WORK_MAX_PAGES = 4   # 演员档案最多抓取的作品页数（4 页 = 48 部）
ACTRESS_WORK_FALLBACK = 3    # 作品总数解析失败时的兜底页数

# 演员二级分类（排序）：站点下拉实测参数
ACTRESS_SORTS = [
    ('popular', '人气最高'),
    ('av_count', '作品最多'),
    ('rating', '评分最高'),
    ('debuted', '最新出道'),
]

# 影片库二级分类（排序）：/videos?sort= 实测参数
VIDEO_SORTS = [
    ('', '最新更新'),
    ('popular', '最多观看'),
    ('rating', '评分最高'),
    ('views', '播放最多'),
]

_TOTAL_RE = re.compile(r'\((\d{4,})\)')


# ============================== 站点解析工具 ==============================

def _xor_url(hexstr):
    """封面地址解密：末两位 hex 为 XOR key，前段每字节异或 key（原生 lazy-cover.js 算法）"""
    if not hexstr or len(hexstr) < 6:
        return ''
    try:
        key = int(hexstr[-2:], 16)
        body = hexstr[:-2]
        return ''.join(chr(int(body[i:i + 2], 16) ^ key) for i in range(0, len(body), 2))
    except Exception:
        return ''


def _strip_tags(s):
    return re.sub(r'<[^>]+>', '', s or '').replace('&amp;', '&').replace('&quot;', '"').strip()


def _fmt_time(sec):
    try:
        sec = int(float(sec))
    except Exception:
        return ''
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return ('%d:%02d:%02d' % (h, m, s)) if h else ('%02d:%02d' % (m, s))


def _slug_of(title):
    """从帧标题里取番号 slug：'jur-175 女优[...]在 0:56:00 ...' -> 'jur-175'"""
    t = (title or '').strip()
    m = re.match(r'([A-Za-z0-9][A-Za-z0-9\-_]{2,40})', t)
    return m.group(1).lower() if m else ''


def _time_of(text):
    m = re.search(r'(\d{1,2}:\d{2}:\d{2})', text or '')
    return m.group(1) if m else ''


def _sec_of(text):
    t = _time_of(text)
    if not t:
        return ''
    p = [int(x) for x in t.split(':')]
    while len(p) < 3:
        p.insert(0, 0)
    return str(p[0] * 3600 + p[1] * 60 + p[2])

# ==================== 合规模块（脱敏/未成年剔除/反代配置） ====================
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


_MINOR_KEYWORDS = (
    "豆蔻", "玉蕊", "碧玉", "稚子", "未成年", "teen", "loli",
    "schoolgirl", "萝莉", "幼女", "少女", "童",
)


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


# ==================== CF 挑战判定 + 设备浏览器桥 ====================
# 本站在全站 Cloudflare 托管挑战后面：requests / curl CLI / 第三方反代 全部被挑战页挡回。
# 两条能过的路（实测）：
#   ① curl_cffi —— 伪装 Chrome 的 TLS(Ja3) 指纹，纯脚本直连 100% 通过；
#   ② 设备浏览器桥 —— 请求交给设备自带 WebView 发出，真实浏览器环境自己把挑战走完，
#      脚本层只把渲染后的 HTML 取回来解析，不存在指纹问题。
CHALLENGE_MARKERS = ('_cf_chl_opt', 'cf_chl', 'challenge-platform', 'just a moment',
                     'cf-mitigated', '__cf_chl', 'cdn-cgi/challenge', 'cf-chl-')


def _looks_like_challenge(text):
    """空页 / 太短 / 命中挑战特征 → 视为没过盾"""
    t = str(text or '')
    if not t or len(t) < 1500:
        return True
    low = t.lower()
    for mk in CHALLENGE_MARKERS:
        if mk in low:
            return True
    return False


class BrowserBridge(object):
    """用设备 WebView 取页；不可用时 available() 为 False，调用方自动降级。"""

    GRAB_JS = "(function(){try{return document.documentElement.outerHTML}catch(e){return ''}})()"
    READY_JS = "(function(){try{return document.readyState}catch(e){return ''}})()"

    def __init__(self, ua=''):
        self.ua = ua or ''
        self._view = None
        self._activity = None
        self._refs = []
        self._proxies = {}
        self.state = 'idle'

    def available(self):
        return bool(_HAS_JAVA_BRIDGE and _jclass is not None and _dynamic_proxy is not None)

    def _cls(self, name):
        try:
            return _jclass(name)
        except Exception:
            return None

    def _keep(self, obj):
        if obj is None:
            return
        self._refs.append(obj)
        if len(self._refs) > 40:
            self._refs = self._refs[-40:]

    def _ctx(self):
        if self._activity is not None:
            return self._activity
        try:
            at = self._cls('android.app.ActivityThread')
            app = at.currentApplication()
            if app is not None:
                self._activity = app
                return app
        except Exception:
            pass
        try:
            at = self._cls('android.app.ActivityThread')
            cur = at.getMethod('currentActivityThread').invoke(None)
            f = at.getDeclaredField('mActivities')
            f.setAccessible(True)
            acts = f.get(cur)
            vals = acts.values()
            vals = vals.toArray() if hasattr(vals, 'toArray') else vals
            for rec in vals:
                rc = rec.getClass()
                pf = rc.getDeclaredField('paused')
                pf.setAccessible(True)
                if pf.getBoolean(rec):
                    continue
                af = rc.getDeclaredField('activity')
                af.setAccessible(True)
                act = af.get(rec)
                if act is not None:
                    self._activity = act
                    return act
        except Exception:
            pass
        try:
            at = self._cls('android.app.ActivityThread')
            app = at.getMethod('currentApplication').invoke(None)
            if app is not None:
                self._activity = app
                return app
        except Exception:
            pass
        return None

    def _proxy_class(self, kind):
        cached = self._proxies.get(kind)
        if cached is not None:
            return cached
        if kind == 'runnable':
            class _R(dynamic_proxy(self._cls('java.lang.Runnable'))):
                def run(self):
                    fn = getattr(self, '_job', None)
                    if fn is not None:
                        try:
                            fn()
                        except Exception:
                            pass
            built = _R
        else:
            class _C(dynamic_proxy(self._cls('android.webkit.ValueCallback'))):
                def onReceiveValue(self, value):
                    sink = getattr(self, '_sink', None)
                    if sink is not None:
                        sink['v'] = value
            built = _C
        self._proxies[kind] = built
        return built

    def _ui(self, job):
        ctx = self._ctx()
        if ctx is None:
            return False
        try:
            r = self._proxy_class('runnable')()
            r._job = job
            self._keep(r)
        except Exception:
            return False
        try:
            ctx.runOnUiThread(r)
            return True
        except Exception:
            pass
        try:
            looper = self._cls('android.os.Looper').getMainLooper()
            h = self._cls('android.os.Handler')(looper)
            self._keep(h)
            h.post(r)
            return True
        except Exception:
            pass
        try:
            job()
            return True
        except Exception:
            return False

    def _ensure_view(self):
        if self._view is not None:
            return self._view
        if not self.available():
            self.state = 'bridge-unavailable'
            return None
        box = {}

        def _build():
            act = self._ctx()
            if act is None:
                box['err'] = 'no-context'
                return
            try:
                wv = self._cls('android.webkit.WebView')(act)
                st = wv.getSettings()
                # 图片必须放行：挑战页要渲染完资源才放行，屏蔽图片会卡在验证中
                st.setJavaScriptEnabled(True)
                st.setDomStorageEnabled(True)
                st.setDatabaseEnabled(True)
                st.setLoadsImagesAutomatically(True)
                st.setBlockNetworkImage(False)
                st.setJavaScriptCanOpenWindowsAutomatically(True)
                st.setSupportMultipleWindows(False)
                if self.ua:
                    st.setUserAgentString(self.ua)
                try:
                    wv.setVisibility(8)
                except Exception:
                    pass
                box['v'] = wv
            except Exception as e:
                box['err'] = str(e)[:60]

        if not self._ui(_build):
            self.state = 'ui-fail'
            return None
        for _ in range(40):
            if box.get('v') is not None or box.get('err'):
                break
            time.sleep(0.1)
        self._view = box.get('v')
        if self._view is None:
            self.state = 'no-view:%s' % box.get('err', '')
        return self._view

    def _eval(self, script):
        view = self._view
        if view is None:
            return ''
        sink = {}
        try:
            cb = self._proxy_class('callback')()
            cb._sink = sink
            self._keep(cb)
            view.evaluateJavascript(script, cb)
        except Exception:
            return ''
        for _ in range(40):
            if 'v' in sink:
                break
            time.sleep(0.05)
        raw = sink.get('v') or ''
        if not raw or raw == 'null':
            return ''
        try:
            import json as _json
            return _json.loads(raw)
        except Exception:
            return raw

    def fetch(self, url, timeout=28, settle=1.2):
        """加载 url 并回传渲染后的 HTML；过不了盾返回空串"""
        view = self._ensure_view()
        if view is None:
            return ''
        deadline = time.time() + max(int(timeout), 12)
        best = ''
        for _round in range(2):
            if time.time() >= deadline:
                break
            try:
                view.loadUrl(url)
            except Exception:
                return ''
            time.sleep(max(settle, 0.4))
            while time.time() < deadline:
                html = self._eval(self.GRAB_JS)
                if html and len(str(html)) > len(best):
                    best = str(html)
                if html and not _looks_like_challenge(html):
                    ready = str(self._eval(self.READY_JS) or '').lower()
                    if (not ready) or ('complete' in ready):
                        self.state = 'ok'
                        return str(html)
                time.sleep(0.6)
            try:
                view.stopLoading()
            except Exception:
                pass
        self.state = 'challenge'
        if best and not _looks_like_challenge(best):
            return best
        return ''

    def destroy(self):
        view, self._view = self._view, None
        if view is None:
            return
        try:
            self._ui(lambda: (view.stopLoading(), view.destroy()))
        except Exception:
            pass


class Spider(_BaseSpider):
    """whos.tv 四壳 Spider：8 大帧分类 + 每类 50 个标签子分类（共 400）"""

    def __init__(self):
        self.session = _requests.Session() if _HAS_REQUESTS else None
        if self.session is not None:
            self.session.headers.update({'User-Agent': UA})
            try:
                _fp = _make_fp_adapter()
                self.session.mount('https://', _fp)
                self.session.mount('http://', _fp)
            except Exception:
                pass
        self._cache = {}
        self._bridge_obj = None
        # 铁律15：原始站点 + 反代
        self.rawSite = HOST
        self.siteUrl = HOST
        self.HOST = HOST
        self._use_proxy = False
        self._default_proxy = _load_default_proxy()
        self._lock = threading.Lock()

    def getName(self):
        return 'whos.tv'

    def init(self, extend=''):
        config = {}
        if isinstance(extend, dict):
            config = extend
        elif extend:
            try:
                import json as _json
                config = _json.loads(extend)
            except Exception:
                try:
                    import ast as _ast
                    config = _ast.literal_eval(extend)
                except Exception:
                    config = {}
        if not isinstance(config, dict):
            config = {}
        # 铁律15：原始站点（防盗链 Referer/Origin 一律用 rawSite）
        raw = str(config.get('host') or config.get('rawSite') or HOST).strip()
        if not raw.startswith('http'):
            raw = 'https://' + raw
        self.rawSite = raw.rstrip('/')
        # 铁律15：反代开关。默认直连（whos.tv 的业务接口与影片页实测免盾直连可用），
        # 若壳侧网络到不了源站，传 proxy=反代地址 或 direct=false 走反代。
        ext_proxy = str(config.get('proxy') or config.get('siteUrl') or '').strip()
        direct = config.get('direct')
        if ext_proxy:
            self._use_proxy = True
            self.siteUrl = ext_proxy.rstrip('/')
        elif direct is None:
            self._use_proxy = False
            self.siteUrl = self.rawSite
        else:
            self._use_proxy = str(direct).lower() not in ('1', 'true', 'yes', 'on')
            self.siteUrl = self._default_proxy if self._use_proxy else self.rawSite
        self.HOST = self.siteUrl
        return None

    # ============================== HTTP 层（自适应） ==============================

    def _headers(self, referer='', extra=None):
        h = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': referer or (self.rawSite + '/'),
        }
        if extra:
            h.update(extra)
        return h

    def _fetch_once(self, url, headers, timeout=15):
        """三级通道：requests(Chrome TLS 指纹) → curl_cffi → 设备浏览器桥"""
        out = ''
        # 通道一：requests + Chrome cipher/EC 曲线指纹（零额外依赖，壳里首选）
        if self.session is not None:
            try:
                r = self.session.get(url, headers=headers, timeout=timeout, verify=False,
                                     allow_redirects=True)
                if r.status_code == 200:
                    r.encoding = 'utf-8'
                    out = r.text
            except Exception:
                out = ''
        if out and not _looks_like_challenge(out):
            return out
        # 通道二：curl_cffi（有则用，伪装完整 Chrome Ja3）
        if _HAS_CURL_CFFI:
            try:
                r = _curl_requests.get(url, headers=headers, impersonate='chrome',
                                       timeout=timeout, verify=False, allow_redirects=True)
                if r.status_code == 200 and not _looks_like_challenge(r.text):
                    return r.text
            except Exception:
                pass
        if not out:
            try:
                import urllib.request
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = resp.read()
                try:
                    import gzip as _gzip
                    if data[:2] == b'\x1f\x8b':
                        data = _gzip.decompress(data)
                except Exception:
                    pass
                out = data.decode('utf-8', errors='ignore')
            except Exception:
                out = ''
        if out and not _looks_like_challenge(out):
            return out
        # 通道三：设备浏览器桥（Android 壳内真实浏览器走挑战，脚本层只取 HTML）
        bridge = self._get_bridge()
        if bridge is not None:
            try:
                html = bridge.fetch(url, timeout=max(14, min(30, timeout + 8)))
                if html and not _looks_like_challenge(html):
                    return html
            except Exception:
                pass
        return out

    def _get_bridge(self):
        if self._bridge_obj is None:
            try:
                self._bridge_obj = BrowserBridge('') if _HAS_JAVA_BRIDGE else False
            except Exception:
                self._bridge_obj = False
        return self._bridge_obj or None

    def _http(self, path, referer='', retry=3, cache=True):
        """站点请求：直连优先；若启用反代则走 siteUrl。命中 CF 挑战页会重试/切反代。"""
        key = path
        if cache:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < CACHE_TTL:
                return hit[1]
        bases = [self.HOST]
        if self._use_proxy is False and self._default_proxy:
            bases.append(self._default_proxy)
        txt = ''
        for base in bases:
            url = base + path if path.startswith('/') else path
            for _ in range(max(1, retry)):
                out = self._fetch_once(url, self._headers(referer))
                if out and 'Just a moment' not in out[:3000] and '_cf_chl_opt' not in out[:8000]:
                    txt = out
                    break
                time.sleep(0.45)
            if txt:
                break
        if cache and txt:
            with self._lock:
                self._cache[key] = (time.time(), txt)
        return txt

    # ============================== 编解码 ==============================

    @staticmethod
    def _enc(*parts):
        clean = [str(p or '').replace('|', ' ').replace('\x1f', ' ') for p in parts]
        return _b64e('\x1f'.join(clean))

    @staticmethod
    def _dec(s):
        raw = _b64d(s or '')
        return raw.split('\x1f') if raw else []

    # ============================== 页面解析 ==============================

    _RE_FRAME = re.compile(
        r'<a href="/frames/(\d+)"[\s\S]{0,1600}?<img\s+src="([^"]+)"[\s\S]{0,2200}?'
        r'data-frame-title="([^"]*)"[\s\S]{0,2600}?<span class="font-medium">([^<]*)</span>', re.S)

    _RE_VIDEO_HEX = re.compile(
        r'href="/videos/([a-zA-Z0-9\-_]+)"[\s\S]{0,1400}?data-cover-src="([0-9a-fA-F]{20,})"'
        r'[\s\S]{0,1200}?alt="([^"]*)"[\s\S]{0,1200}?<h3[^>]*>([\s\S]{0,300}?)</h3>', re.S)

    _RE_VIDEO_IMG = re.compile(
        r'href="/videos/([a-zA-Z0-9\-_]+)"[\s\S]{0,1400}?<img[^>]+src="(https?://[^"]+)"'
        r'[\s\S]{0,1200}?alt="([^"]*)"[\s\S]{0,1200}?<h3[^>]*>([\s\S]{0,300}?)</h3>', re.S)

    def _frames(self, html):
        out = []
        seen = set()
        for fid, img, title, code in self._RE_FRAME.findall(html or ''):
            if fid in seen:
                continue
            seen.add(fid)
            slug = _slug_of(title) or code.lower()
            t = _time_of(title) or _time_of(code)
            sec = _sec_of(title) or _sec_of(code)
            desc = re.sub(r'\d{1,2}:\d{2}:\d{2}', ' ', title or '').strip()
            desc = re.sub(r'\s+', ' ', desc)
            if slug and desc.lower().startswith(slug.lower()):
                desc = desc[len(slug):].strip()
            desc = desc.lstrip('·-|,， ').strip()
            name = (code or slug).upper().strip()
            if t:
                name = '%s · %s' % (name, t)
            if desc:
                name = '%s %s' % (name, desc[:60])
            pic = img if img.startswith('http') else (IMG_CDN + img)
            out.append({
                'vod_id': self._enc('f', fid, slug, sec, title, pic),
                'vod_name': name,
                'vod_pic': pic,
                'vod_remarks': t or '帧',
                '_slug': slug,
                '_sec': sec,
            })
        return out

    def _videos(self, html):
        """影片卡片解析：以 <a href="/videos/xxx"> 分块，兼容 搜索结果 / 影片库 / 排行榜 三种版式"""
        out = []
        seen = set()
        for seg in re.split(r'(?=<a[^>]+href="/videos/)', html or ''):
            m = re.match(r'<a[^>]+href="/videos/([a-zA-Z0-9\-_]+)"', seg)
            if not m:
                continue
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            chunk = seg[:6000]
            pic = ''
            mc = re.search(r'data-cover-src="([0-9a-fA-F]{20,})"', chunk)
            if mc:
                pic = _xor_url(mc.group(1))
            if not pic or not pic.startswith('http'):
                mi = re.search(r'<img[^>]+src="(https?://[^"]+)"', chunk)
                pic = mi.group(1) if mi else ''
            title = ''
            mh = re.search(r'<h3[^>]*>([\s\S]{0,300}?)</h3>', chunk)
            if mh:
                title = _strip_tags(mh.group(1))
            if not title:
                ma = re.search(r'alt="([^"]{2,200})"', chunk)
                if ma:
                    title = _strip_tags(ma.group(1))
            if not title:
                mt = re.search(r'<p[^>]*>([\s\S]{0,200}?)</p>', chunk)
                title = _strip_tags(mt.group(1)) if mt else ''
            title = (title or slug.upper())[:120]
            out.append({
                'vod_id': self._enc('v', slug, title, pic, ''),
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': slug.upper(),
            })
        return out

    def _actresses(self, html):
        """演员卡解析：名字 / 头像 / 评分 / 作品数 / 点赞数（以 <a href="/actresses/x"> 分块）"""
        out = []
        seen = set()
        for seg in re.split(r'(?=<a[^>]+href="/actresses/)', html or ''):
            m = re.match(r'<a[^>]+href="/actresses/([^"?#]+)"', seg)
            if not m:
                continue
            name = unquote(m.group(1)).strip()
            if not name or name.startswith('page-') or name in seen:
                continue
            seen.add(name)
            chunk = seg[:5200]
            pic = ''
            mi = re.search(r'<img[^>]+src="(https?://[^"]+)"', chunk)
            if mi:
                pic = mi.group(1)
            rating = ''
            mr = re.search(r'star\]\s*text-amber-400[\s\S]{0,180}?</span>\s*'
                           r'<span[^>]*>\s*([\d.]+)\s*</span>', chunk)
            if mr:
                rating = mr.group(1)
            works = ''
            mw = re.search(r'lucide--film[\s\S]{0,200}?</span>\s*([\d,]+)', chunk)
            if mw:
                works = mw.group(1).replace(',', '')
            likes = ''
            ml = re.search(r'lucide--heart[\s\S]{0,200}?</span>\s*([\d,]+)', chunk)
            if ml:
                likes = ml.group(1).replace(',', '')
            remarks = ('%s 部作品' % works) if works else '演员档案'
            if rating:
                remarks = '%s · %s 分' % (remarks, rating)
            out.append({
                'vod_id': self._enc('a', name, pic),
                'vod_name': name,
                'vod_pic': pic,
                'vod_remarks': remarks,
                '_works': works,
                '_likes': likes,
            })
        return out

    def _actress_profile(self, html):
        """演员档案：名字 / 头像 / 评分 / 作品数 / 浏览量 / 身高 / 出道年"""
        info = {}
        if not html:
            return info
        m = re.search(r'<h1[^>]*>([\s\S]{0,120}?)</h1>', html)
        if m:
            info['name'] = _strip_tags(m.group(1))
        m = re.search(r'<img[^>]+src="(https?://[^"]+/actress/avatar/[^"]+)"', html)
        if m:
            info['pic'] = m.group(1)
        m = re.search(r'id="actress-avg-rate"[^>]*>\s*([\d.]+)\s*<', html)
        if m:
            info['rating'] = m.group(1)
        m = re.search(r'id="actress-rating-count"[^>]*>\s*([\d,]+)\s*人', html)
        if m:
            info['rating_count'] = m.group(1).replace(',', '')
        m = re.search(r'>\s*([\d,]+)\s*</p>\s*<p[^>]*>\s*作品数', html)
        if m:
            info['works'] = m.group(1).replace(',', '')
        m = re.search(r'>\s*([\d,]+)\s*</p>\s*<p[^>]*>\s*浏览量', html)
        if m:
            info['views'] = m.group(1).replace(',', '')
        m = re.search(r'>\s*(\d{3})\s*cm\s*<', html)
        if m:
            info['height'] = m.group(1) + 'cm'
        m = re.search(r'出道[:：]\s*([^<\s]{4,20})', html)
        if m:
            info['debut'] = m.group(1).strip()
        m = re.search(r'>\s*(\d{4}年\d{1,2}月\d{1,2}日)\s*<', html)
        if m:
            info['birthday'] = m.group(1)
        return info

    @staticmethod
    def _actress_work_pages(works):
        """按作品总数决定抓几页（封顶 ACTRESS_WORK_MAX_PAGES）"""
        try:
            n = int(str(works or '').replace(',', '') or 0)
        except Exception:
            n = 0
        if n <= 0:
            return ACTRESS_WORK_FALLBACK
        pages = (n + ACTRESS_WORK_PAGE - 1) // ACTRESS_WORK_PAGE
        return max(1, min(ACTRESS_WORK_MAX_PAGES, pages))

    @staticmethod
    def _extend_get(extend, key):
        """从 extend 里取二级分类值（兼容 dict 与 JSON 串两种下发形态）"""
        if isinstance(extend, dict):
            return str(extend.get(key) or '')
        if isinstance(extend, str) and extend:
            m = re.search(r'["\']?%s["\']?\s*[:=]\s*["\']?([A-Za-z0-9_\-]*)' % re.escape(key),
                          extend)
            return m.group(1) if m else ''
        return ''

    def _video_info(self, html):
        """从影片页提取：标题 / 封面 / 时长 / 日期 / 简介 / m3u8"""
        info = {}
        if not html:
            return info
        m = re.search(r'<h1[^>]*>([\s\S]{0,300}?)</h1>', html, re.S)
        if m:
            info['title'] = _strip_tags(m.group(1))[:150]
        m = re.search(r'<meta name="description" content="([^"]{0,400})"', html)
        if m:
            info['content'] = m.group(1).strip()
        m = re.search(r'(https://v\.hersav\.me/images/av/[a-f0-9]+\.jpg)', html)
        if m:
            info['cover'] = m.group(1)
        m = re.search(r'data-preview-source="(https?://[^"]+\.m3u8[^"]*)"', html)
        if not m:
            m = re.search(r'(https://v\.hersav\.me/[a-f0-9]+/[a-f0-9]+\.m3u8)', html)
        if m:
            info['m3u8'] = m.group(1)
        m = re.search(r'时长[：:]?</span>\s*<span[^>]*>([^<]{1,24})</span>', html)
        if m:
            info['minutes'] = m.group(1).strip()
        m = re.search(r'发行日期</span>\s*<span[^>]*>([^<]{4,24})</span>', html)
        if m:
            info['date'] = m.group(1).strip()
        elif re.search(r'(\d{4}-\d{2}-\d{2})', html):
            info['date'] = re.search(r'(\d{4}-\d{2}-\d{2})', html).group(1)
        acts = []
        for a in re.findall(r'href="/actresses/([^"]{1,60})"', html):
            nm = unquote(a).strip()
            if nm and nm not in acts:
                acts.append(nm)
        if acts:
            info['actors'] = '/'.join(acts[:6])
        return info

    # ============================== 13 接口 ==============================

    def homeContent(self, filter):
        classes = []
        for tid, cn, _slug, _labels in WHOS_CATS:
            classes.append({'type_id': 'c%d' % tid, 'type_name': cn})
        classes.append({'type_id': 'actors', 'type_name': '演员'})
        for tid, cn in EXTRA_CATS:
            classes.append({'type_id': tid, 'type_name': cn})
        # 铁律11+13：分类脱敏
        classes = _sanitize_classes(classes)
        # 二级分类走 filters：帧分类 = 标签（站点 label_id）、演员 = 排序、影片库 = 排序
        filters = {}
        for tid, _cn, _slug, labels in WHOS_CATS:
            opts = [{'n': '全部', 'v': ''}]
            for lid, lname in labels:
                opts.append({'n': desensitize(lname), 'v': str(lid)})
            filters['c%d' % tid] = [{'key': 'label', 'name': '标签', 'value': opts}]
        filters['actors'] = [{'key': 'sort', 'name': '排序',
                              'value': [{'n': n, 'v': v} for v, n in ACTRESS_SORTS]}]
        filters['videos'] = [{'key': 'sort', 'name': '排序',
                              'value': [{'n': n, 'v': v} for v, n in VIDEO_SORTS]}]
        return {'class': classes, 'filters': filters}

    def homeVideoContent(self):
        html = self._http(VIDEO_LIST)
        # 铁律11+13：列表脱敏
        return {'list': _sanitize_list(self._videos(html))[:PER_PAGE_VIDEOS]}

    def categoryContent(self, tid, pg=1, filter=False, extend=''):
        tid = str(tid or '')
        try:
            p = max(1, int(pg or 1))
        except Exception:
            p = 1
        label = ''
        if isinstance(extend, dict):
            label = str(extend.get('label') or '')
        elif isinstance(extend, str) and extend:
            m = re.search(r'label["\']?\s*[:=]\s*["\']?(\d+)', extend)
            if m:
                label = m.group(1)
        items = []
        if tid == 'actors':
            sort = self._extend_get(extend, 'sort')
            if sort not in [v for v, _n in ACTRESS_SORTS]:
                sort = 'popular'
            path = ACTRESS_LIST if p <= 1 else '%s/page-%d' % (ACTRESS_LIST, p)
            html = self._http('%s?sort=%s' % (path, quote(sort)))
            items = self._actresses(html)
            pagecount = p + 1 if len(items) >= PER_PAGE_ACTRESS else p
        elif tid == 'videos':
            sort = self._extend_get(extend, 'sort')
            path = VIDEO_LIST if p <= 1 else '%s/page-%d' % (VIDEO_LIST, p)
            if sort:
                path = '%s?sort=%s' % (path, quote(sort))
            html = self._http(path)
            items = self._videos(html)
            pagecount = p + 1 if len(items) >= PER_PAGE_VIDEOS else p
        elif tid == 'ranking':
            html = self._http(RANKING)
            items = self._videos(html)
            pagecount = 1
        else:
            num = tid[1:] if tid.startswith('c') else tid
            if not num.isdigit():
                num = '1'
            html = self._http('%s?type_id=%s&label_id=%s&page=%d' % (FRAMES_API, num, label, p))
            items = self._frames(html)
            pagecount = p + 1 if len(items) >= PER_PAGE_FRAMES else p
        # 铁律11+13：列表脱敏
        vods = _sanitize_list(items)
        if tid == 'actors':
            limit = PER_PAGE_ACTRESS
        elif tid == 'videos':
            limit = PER_PAGE_VIDEOS
        else:
            limit = len(vods) or PER_PAGE_FRAMES
        return {'page': p, 'pagecount': pagecount, 'limit': limit,
                'total': len(vods), 'list': vods}

    def _actress_detail(self, source_id, name, pic=''):
        """演员档案：资料 + 她的作品（按作品总数抓 1~4 页，每部一个剧集，点开直接播）"""
        base = ACTRESS_PATH.format(quote(name))
        html = self._http(base)
        prof = self._actress_profile(html)
        works = self._videos(html)
        pages = self._actress_work_pages(prof.get('works'))
        for extra in range(2, pages + 1):
            more = self._http('%s/page-%d' % (base, extra))
            if not more:
                break
            batch = self._videos(more)
            if not batch:
                break
            works.extend(batch)
        eps = []
        seen = set()
        for w in works:
            wp = self._dec(w.get('vod_id') or '')
            if len(wp) < 3:
                continue
            slug = wp[1]
            if slug in seen:
                continue
            seen.add(slug)
            title = (w.get('vod_name') or slug.upper())[:80]
            eps.append('%s$%s' % (title, w.get('vod_id')))
        if not eps:
            return None
        bits = []
        if prof.get('rating'):
            bits.append('评分 %s' % prof['rating'])
        if prof.get('works'):
            bits.append('作品 %s 部' % prof['works'])
        if prof.get('views'):
            bits.append('浏览 %s' % prof['views'])
        if prof.get('height'):
            bits.append(prof['height'])
        if prof.get('debut'):
            bits.append('出道 %s' % prof['debut'])
        content = ('%s（%s）' % (name, ' · '.join(bits))) if bits else name
        content = '%s。共收录 %d 部作品，点集数直接播放。' % (content, len(eps))
        return {
            'vod_id': source_id,
            'vod_name': name,
            'vod_pic': prof.get('pic') or pic,
            'vod_remarks': '%d 部作品' % len(eps),
            'vod_content': content,
            'vod_actor': name,
            'vod_play_from': 'whos',
            'vod_play_url': '#'.join(eps),
        }

    def detailContent(self, ids):
        # 铁律8：ids 为 list/tuple 必须遍历
        id_list = list(ids) if isinstance(ids, (list, tuple)) else [ids]
        result_list = []
        for source_id in id_list:
            parts = self._dec(source_id)
            if not parts:
                continue
            kind = parts[0]
            if kind == 'a':
                aname = parts[1] if len(parts) > 1 else ''
                apic = parts[2] if len(parts) > 2 else ''
                if not aname:
                    continue
                avod = self._actress_detail(source_id, aname, apic)
                if avod:
                    cleaned = _sanitize_vod(avod)
                    if cleaned is not None:
                        result_list.append(cleaned)
                continue
            if kind == 'v':
                slug = parts[1] if len(parts) > 1 else ''
                title = parts[2] if len(parts) > 2 else ''
                pic = parts[3] if len(parts) > 3 else ''
                sec = ''
            else:
                slug = parts[2] if len(parts) > 2 else ''
                sec = parts[3] if len(parts) > 3 else ''
                title = parts[4] if len(parts) > 4 else ''
                pic = parts[5] if len(parts) > 5 else ''
            if not slug:
                continue
            html = self._http(VIDEO_PATH.format(slug))
            info = self._video_info(html)
            name = info.get('title') or title or slug.upper()
            cover = info.get('cover') or pic
            content = info.get('content') or title or name
            remarks = ' · '.join([x for x in (info.get('date'), info.get('minutes')) if x])
            actors = info.get('actors') or ''
            play_id = self._enc('p', slug, sec, name)
            vod = {
                'vod_id': source_id,
                'vod_name': name,
                'vod_pic': cover,
                'vod_remarks': remarks or slug.upper(),
                'vod_content': content,
                'vod_actor': actors,
                'vod_play_from': 'whos',
                'vod_play_url': '正片$' + play_id,
            }
            # 铁律11+13：详情脱敏
            cleaned = _sanitize_vod(vod)
            if cleaned is not None:
                result_list.append(cleaned)
        return {'list': result_list}

    def searchContent(self, key, quick=False, pg=1):
        try:
            p = max(1, int(pg or 1))
        except Exception:
            p = 1
        path = '%s?search=%s&page=%d' % (RESULT, quote(str(key or '')), p)
        html = self._http(path)
        items = _sanitize_list(self._videos(html))
        total = 0
        m = _TOTAL_RE.search(html or '')
        if m:
            try:
                total = int(m.group(1))
            except Exception:
                total = 0
        if total:
            pagecount = max(1, (total + PER_PAGE_SEARCH - 1) // PER_PAGE_SEARCH)
        else:
            pagecount = p + 1 if len(items) >= PER_PAGE_SEARCH else p
        if not total:
            total = len(items)
        return {'list': items, 'page': p, 'pagecount': pagecount,
                'limit': PER_PAGE_SEARCH, 'total': total}

    def playerContent(self, flag, id, vipFlags=None):
        """按 slug 现取 m3u8（站点签名为实时下发，避免隔天失效）"""
        parts = self._dec(id)
        slug = parts[1] if len(parts) > 1 else ''
        sec = parts[2] if len(parts) > 2 else ''
        url = ''
        if slug:
            path = VIDEO_PATH.format(slug)
            if sec:
                path = '%s?t=%s' % (path, sec)
            html = self._http(path, cache=False)
            info = self._video_info(html)
            m3u8 = info.get('m3u8') or ''
            if m3u8:
                url = self._proxy_m3u8_url(self._sanitize_m3u8_url(m3u8), self.rawSite + '/')
        # 铁律15：防盗链三件套，Referer/Origin 用原始站点
        return {'parse': 0, 'url': url,
                'header': {'User-Agent': UA, 'Referer': self.rawSite + '/',
                           'Origin': self.rawSite}}

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|ts)(\?|$)', url or '', re.I))

    def manualVideoCheck(self):
        return False

    def getDependence(self):
        return ''

    def action(self, action):
        return ''

    def destroy(self):
        try:
            if self.session is not None:
                self.session.close()
        except Exception:
            pass
        try:
            if self._bridge_obj not in (None, False):
                self._bridge_obj.destroy()
        except Exception:
            pass
        return ''

    # ==================== m3u8 解析 / 广告清洗 ====================
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

    # ==================== m3u8 广告清洗（清洗链路完整保留） ====================

    def localProxy(self, param):
        """本地代理：m3u8 下载 + 广告清洗"""
        if not isinstance(param, dict):
            param = {}
        do = param.get('type') or param.get('action') or param.get('do')
        url = param.get('url', '') or param.get('path', '')
        if isinstance(url, list):
            url = url[0] if url else ''
        if do == 'm3u8' or (isinstance(url, str) and '.m3u8' in url):
            try:
                referer = param.get('referer', '') or self.rawSite
                if isinstance(referer, list):
                    referer = referer[0] if referer else self.rawSite
                url = unquote(url)
                referer = unquote(referer)
                text = self._get_m3u8_content(url, referer)
                if not text:
                    return [502, 'text/plain', 'm3u8 download failed']
                try:
                    from m3u8_cleaner import M3U8Cleaner
                    cleaned = M3U8Cleaner(raw_site=referer or self.rawSite).clean(text, url, referer)
                except Exception:
                    cleaned = self._clean_m3u8(text, url, referer)
                return [200, 'application/vnd.apple.mpegurl', cleaned]
            except Exception as e:
                return [500, 'text/plain', 'proxy error: %s' % e]
        return [404, 'text/plain', '']
