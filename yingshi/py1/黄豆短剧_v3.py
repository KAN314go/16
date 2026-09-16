# -*- coding: utf-8 -*-
# 黄豆短剧 spider v3.0.0
# 下面每条结论都来自实机探站，不是推测：
#   1) 免费集 /api/drama/hls/{id}/{seq}/play.m3u8 的 sig / exp / line / query 服务端一律
#      不校验，去掉全部签名参数直接请求即返回完整 HLS（分片数与 duration 完全吻合），
#      分片与 AES-128 key 均可直下。
#   2) /drama/play 对金币集只下发 is_preview 的 CloudFront 试看片（约 10 秒级）。旧版把它
#      当正片喂给播放器，所以看着像“破解失效”，实际是拿了个试看片。
#   3) 金币集裸请求一律 403；seq 写成 "3.0"/"0x3"/"3e0" 这类变体虽然回 200，但分片指纹与
#      第 1 集完全一致，是服务端回退，不是绕过。付费墙是服务端硬控，金币集完整片没有
#      客户端旁路，只有官方端解锁一条路。
#   4) free_episodes=0 表示整部免费（实测 188 集 / 100 集剧目全集可播）；>0 时前 N 集免费。
# 本次只改「详情标注 + 播放取流 + 错误文案」三层，其余层原样保留。
import gzip
import hashlib
import hmac
import io
import ipaddress
import json
import os
import socket
import threading
import time
import uuid
import requests
from contextlib import contextmanager, nullcontext
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider:
        pass

class _AESCBC:
    @staticmethod
    def encrypt(data, key, iv):
        from Crypto.Cipher import AES
        return AES.new(key, AES.MODE_CBC, iv).encrypt(_AESCBC.pad(data))

    @staticmethod
    def decrypt(data, key, iv):
        from Crypto.Cipher import AES
        plain = AES.new(key, AES.MODE_CBC, iv).decrypt(data)
        return _AESCBC.unpad(plain)

    @staticmethod
    def pad(data):
        n = 16 - len(data) % 16
        return data + bytes([n]) * n

    @staticmethod
    def unpad(data):
        if not data:
            raise ValueError("empty PKCS7 payload")
        n = data[-1]
        if n < 1 or n > 16 or data[-n:] != bytes([n]) * n:
            raise ValueError("invalid PKCS7 padding")
        return data[:-n]


class _ApiError(Exception):
    def __init__(self, code, retryable=False, detail=""):
        super().__init__(code)
        self.code = str(code)
        self.retryable = bool(retryable)
        self.detail = str(detail or "")


_DNS_LOCK = threading.RLock()


@contextmanager
def _pinned_dns(host, ip):
    with _DNS_LOCK:
        original = socket.getaddrinfo

        def resolve(name, *args, **kwargs):
            return original(ip, *args, **kwargs) if name == host else original(name, *args, **kwargs)

        socket.getaddrinfo = resolve
        try:
            yield
        finally:
            socket.getaddrinfo = original

class Spider(BaseSpider):
    def __init__(self):
        self.backend_parse = False
        self.category_mode = False
        self.host = "https://xqjzvcvt.top"
        self.canonical_host = "xqjzvcvt.top"
        self.public_host_ips = ("91.110.232.197", "91.110.232.206")
        self.host_needs_pin = None
        self.api = self.host + "/api"
        self.name = "黄豆短剧"
        self.platform_key = "7961beb44246e3012ce228d6b5ced05a"
        self.version = "3.0.0"
        self.device_type = "web"
        self.session_id = uuid.uuid4().hex
        self.device_id = self.session_id
        self.token = ""
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Accept": "*/*", "Origin": self.host, "Referer": self.host + "/", "Content-Type": "application/octet-stream"}
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(self.headers)
        self.class_cache = None
        self.filter_cache = {}
        self.access_cache = {}
        self.detail_cache = {}
        self.last_error = ""
        self.last_hls_error = ""
        self.max_response_bytes = 2 * 1024 * 1024
        self.max_playlist_bytes = 512 * 1024
        self.api_attempts = 2

    def init(self, extend=""):
        cfg = self._config(extend)
        candidate = str(cfg.get("site") or cfg.get("base_url") or self.host).strip().rstrip("/")
        parsed = urlsplit(candidate)
        if parsed.scheme in ("http", "https") and parsed.netloc and not parsed.username and not parsed.query and not parsed.fragment:
            if parsed.path.rstrip("/").endswith("/api"):
                candidate = candidate[:-4].rstrip("/")
            self.host = candidate
            self.api = self.host + "/api"
            self.host_needs_pin = None
        token = None
        for key in ("token", "access_token", "accessToken", "auth_token"):
            if cfg.get(key) is not None:
                token = cfg.get(key)
                break
        if token is not None:
            self.token = str(token or "").strip()
        device_id = cfg.get("deviceId") or cfg.get("device_id") or cfg.get("device")
        session_id = cfg.get("sessionId") or cfg.get("session_id") or cfg.get("session")
        if device_id:
            self.device_id = str(device_id).strip()
        if session_id:
            self.session_id = str(session_id).strip()
        self.headers["Origin"] = self.host
        self.headers["Referer"] = self.host + "/"
        self.session.headers.update(self.headers)
        self.class_cache = None
        self.filter_cache = {}
        self.access_cache = {}
        self.detail_cache = {}
        self.last_error = ""
        self.last_hls_error = ""

    def getName(self):
        return self.name

    def homeContent(self, filter):
        data = self._api("/drama/list", {"page": "1", "page_size": "18"})
        classes = self._classes()
        return {"class": classes, "filters": self._filters(classes), "list": [self._vod(x) for x in self._list(data)], "parse": 0, "jx": 0}

    def categoryContent(self, tid, pg, filter, extend):
        extend = self._dict(extend)
        tid = str(tid or "all")
        pg = max(1, self._int(pg, 1))
        if tid == "yuandou":
            data = self._api("/drama/navBlock", {"code": "yuandou", "tab": "recommend", "page": str(pg)})
            items = self._nav_items(data)
        else:
            req = {"page": str(pg), "page_size": "18"}
            if tid and tid not in ("all", "recommend"):
                tabs = self._nav_filter(tid)
                idx = self._int(extend.get("sub"), 0)
                sub = tabs[idx] if tabs and 0 <= idx < len(tabs) else {}
                flt = sub.get("filter", {}) if isinstance(sub, dict) else {}
                req["cat_id"] = flt.get("cat_id", "")
                if flt.get("tag_id"):
                    req["tag_id"] = flt.get("tag_id", "")
                req["order"] = flt.get("order", "") or extend.get("order", "")
            elif extend.get("order"):
                req["order"] = extend.get("order")
            if extend.get("update_status"):
                req["update_status"] = extend.get("update_status")
            data = self._api("/drama/list", req)
            items = self._list(data)
        return {"page": int(pg), "pagecount": int(pg) if len(items) < 18 else int(pg) + 1, "limit": 18, "total": 99999, "list": [self._vod(x) for x in items], "parse": 0, "jx": 0}

    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = self._sid(raw_id)
        obj = self._api("/drama/detail", {"id": vid})
        data = obj.get("data", obj) if isinstance(obj, dict) else {}
        if not isinstance(data, dict):
            return {"list": []}
        vod_id = self._sid(data.get("id") or data.get("drama_id") or vid)
        name = data.get("name") or data.get("title") or data.get("t") or vod_id
        eps = data.get("episodes") if isinstance(data.get("episodes"), list) else []
        count = self._int(data.get("episode_count") or data.get("free_episodes"), len(eps) or 1)
        free_seqs, all_free, price_of = self._episode_access(data)
        self.detail_cache[vod_id] = {"access": (free_seqs, all_free, price_of), "expires": time.time() + 21600}
        play = []
        if eps:
            for i, ep in enumerate(eps, 1):
                seq = str(ep.get("seq") or ep.get("episode") or ep.get("ep") or i)
                label = ep.get("name") or ep.get("title") or "第%s集" % seq
                price = price_of.get(seq)
                tag = "" if (all_free or seq in free_seqs) else (" [金币%s]" % price if price else " [需解锁]")
                play.append("%s%s$%s|%s" % (label, tag, vod_id, seq))
        else:
            play = ["第%s集%s$%s|%s" % (i, "" if (all_free or str(i) in free_seqs) else " [需解锁]", vod_id, i) for i in range(1, count + 1)]
        vod = {"vod_id": vod_id, "vod_name": name, "vod_pic": self._pic(data), "type_name": data.get("category") or data.get("type") or "", "vod_year": "", "vod_area": "", "vod_remarks": data.get("update_label") or "全%s集" % count, "vod_actor": "", "vod_director": "", "vod_content": data.get("description") or data.get("summary") or name, "vod_play_from": self.name, "vod_play_url": "#".join(play)}
        return {"list": [vod], "parse": 0, "jx": 0}

    def searchContent(self, key, quick, pg="1"):
        data = self._api("/drama/list", {"page": str(pg), "page_size": "18", "keywords": str(key)})
        items = self._list(data)
        return {"page": int(pg), "pagecount": int(pg) if len(items) < 18 else int(pg) + 1, "limit": 18, "total": 99999, "list": [self._vod(x) for x in items], "parse": 0, "jx": 0}

    def playerContent(self, flag, id, vipFlags):
        vid, seq = self._split(id)
        cache_key = "%s|%s" % (vid, seq)
        cached = self.access_cache.get(cache_key)
        now = time.time()
        if isinstance(cached, dict) and cached.get("expires", 0) > now:
            if cached.get("url"):
                return self._player(cached.get("url"), cached.get("msg"))

        access = self._access_of(vid)
        if access is not None:
            free_seqs, all_free, price_of = access
            if all_free or seq in free_seqs:
                # 免费集：签名参数服务端根本不校验，直接走无签名 HLS，绕开
                # /drama/play 对金币集的试看降级（旧版就是被这一步顶掉的）。
                url = self._hls(vid, seq)
                self.access_cache[cache_key] = {"url": url, "expires": now + 1800}
                self.last_error = ""
                return self._player(url)
            # 金币/VIP 集：服务端硬控，官方端只下发试看片段。不假装是正片，如实交试看 + 人话提示。
            obj = self._api("/drama/play", {"id": vid, "seq": str(seq)}, True)
            preview = self._play_candidates(obj)
            price = price_of.get(seq)
            notice = "本集需金币解锁%s，当前只能看试看片段" % ("（%s金币）" % price if price else "")
            if preview:
                url = preview[0]
                self.access_cache[cache_key] = {"url": url, "expires": now + 300, "msg": notice}
                self.last_error = notice
                return self._player(url, notice)
            self.last_error = notice
            return self._player_error(notice)

        return self._signed_play(vid, seq, cache_key, now)

    def _signed_play(self, vid, seq, cache_key, now):
        # 详情拿不到时的兜底：沿用原来的签名线路 + 裸线路重建逻辑，保证不炸。
        obj = self._api("/drama/play", {"id": vid, "seq": str(seq)}, True)
        signed_candidates = self._play_candidates(obj)
        candidates = signed_candidates + self._legacy_hls_candidates(vid, seq, signed_candidates)
        ordered = []
        seen = set()
        for url in candidates:
            if url in seen:
                continue
            seen.add(url)
            ordered.append(url)

        # Keep the original FM handoff contract: a probe failure must not block
        # the player from attempting an otherwise valid signed or legacy URL.
        if ordered:
            url = ordered[0]
            self.access_cache[cache_key] = {"url": url, "expires": self._url_expiry(url)}
            self.last_error = "" if signed_candidates else self._play_error(obj)
            return self._player(url)

        error = self._play_error(obj)
        self.last_error = error
        return self._player_error(error)

    def localProxy(self, param):
        return [404, "text/plain", None, "not found"]

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    def _api(self, path, data=None, silent=False):
        path = "/" + path.lstrip("/")
        last_error = None
        for attempt in range(self.api_attempts):
            rid = str(uuid.uuid4())
            key = self._key(rid)
            iv = os.urandom(16)
            raw = json.dumps({"token": self.token or "", "deviceId": self.device_id, "data": data or {}}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            body = iv + _AESCBC.encrypt(gzip.compress(raw), key, iv)
            ts = int(time.time())
            sign = hashlib.sha256(("Dart|%s|%s|%s|%s" % (self.session_id, rid, ts, path)).encode("utf-8")).hexdigest() + "-" + str(ts)
            h = dict(self.headers)
            h.update({"version": self.version, "deviceType": self.device_type, "time": str(ts), "sign": sign, "requestId": rid, "sessionId": self.session_id, "deviceBrand": "", "deviceModel": "", "systemName": "", "systemVersion": ""})
            try:
                with self._host_route(attempt):
                    with self.session.post(self.api + path, data=body, headers=h, timeout=(8, 25), stream=True) as response:
                        status = response.status_code
                        if status in (408, 425, 429) or 500 <= status <= 599:
                            raise _ApiError("http_%s" % status, True)
                        if status < 200 or status >= 300:
                            raise _ApiError("http_%s" % status)
                        obj = self._decode(self._read_limited(response, self.max_response_bytes), rid)
                if not isinstance(obj, dict):
                    raise _ApiError("invalid_api_object", True)
                if not self._api_ok(obj):
                    code, detail = self._api_failure(obj)
                    self.last_error = "%s:%s" % (code, detail) if detail else code
                    return obj if silent else {}
                self.last_error = ""
                return obj
            except _ApiError as exc:
                last_error = exc
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = _ApiError(type(exc).__name__, True)
            except requests.RequestException as exc:
                last_error = _ApiError(type(exc).__name__)
            except (ValueError, TypeError, OSError, EOFError) as exc:
                last_error = _ApiError(type(exc).__name__, True)
            if attempt + 1 < self.api_attempts and last_error.retryable:
                time.sleep(0.25 * (attempt + 1))
                continue
            break
        self.last_error = last_error.code if last_error else "api_request_failed"
        return {}

    def _host_route(self, attempt=0):
        host = urlsplit(self.host).hostname or ""
        if host != self.canonical_host or not self.public_host_ips:
            return nullcontext()
        if self.host_needs_pin is None:
            self.host_needs_pin = self._public_ipv4_missing(host)
        if self.host_needs_pin or attempt > 0:
            return _pinned_dns(host, self.public_host_ips[attempt % len(self.public_host_ips)])
        return nullcontext()

    def _public_ipv4_missing(self, host):
        try:
            infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
            for info in infos:
                if ipaddress.ip_address(info[4][0]).is_global:
                    return False
        except (OSError, ValueError):
            pass
        return True

    def _key(self, rid):
        return hmac.new(self.platform_key.encode("utf-8"), bytes.fromhex(str(rid).replace("-", "")), hashlib.sha256).digest()

    def _decode(self, blob, rid):
        if not blob or len(blob) < 32 or (len(blob) - 16) % 16 != 0:
            if not blob:
                raise ValueError("empty response")
            return json.loads(blob.decode("utf-8"))
        plain = _AESCBC.decrypt(blob[16:], self._key(rid), blob[:16])
        if plain[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=io.BytesIO(plain)) as zipped:
                plain = zipped.read(self.max_response_bytes + 1)
            if len(plain) > self.max_response_bytes:
                raise ValueError("decoded response too large")
        return json.loads(plain.decode("utf-8"))

    def _read_limited(self, response, limit):
        declared = self._int(response.headers.get("Content-Length"), 0)
        if declared > limit:
            raise _ApiError("response_too_large")
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            size += len(chunk)
            if size > limit:
                raise _ApiError("response_too_large")
            chunks.append(chunk)
        return b"".join(chunks)

    def _api_ok(self, obj):
        if not isinstance(obj, dict) or not obj:
            return False
        status = str(obj.get("status") or "").strip().lower()
        return not status or status in ("y", "yes", "ok", "success", "1", "true")

    def _api_failure(self, obj):
        code = str(obj.get("errorCode") or obj.get("code") or obj.get("status") or "api_rejected")
        detail = obj.get("error") or obj.get("message") or obj.get("msg") or ""
        return code, str(detail or "")

    def _config(self, value):
        cfg = self._dict(value)
        for key in ("ext", "data", "config", "auth", "credential", "credentials"):
            inner = self._dict(cfg.get(key))
            if not inner:
                continue
            merged = dict(inner)
            for name, item in cfg.items():
                if name != key:
                    merged[name] = item
            cfg = merged
        return cfg

    def _dict(self, value):
        if isinstance(value, dict):
            return dict(value)
        if not isinstance(value, str) or not value.strip():
            return {}
        try:
            obj = json.loads(value)
            return dict(obj) if isinstance(obj, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _play_candidates(self, obj):
        data = obj.get("data", obj) if isinstance(obj, dict) else {}
        if not isinstance(data, dict):
            return []
        result = []

        def add(value):
            value = str(value or "").strip()
            if not value:
                return
            value = urljoin(self.host + "/", value)
            if self._http_url(value) and value not in result:
                result.append(value)

        for key in ("m3u8", "url", "play_url", "playUrl"):
            add(data.get(key))
        lines = data.get("lines") if isinstance(data.get("lines"), list) else []
        for line in lines:
            if not isinstance(line, dict):
                continue
            for key in ("m3u8", "url", "play_url", "playUrl"):
                add(line.get(key))
        return result

    def _legacy_hls_candidates(self, vid, seq, signed_candidates):
        result = []
        expected = urlsplit(self._hls(vid, seq))

        def add(value):
            if self._http_url(value) and value not in result:
                result.append(value)

        for value in signed_candidates:
            try:
                parsed = urlsplit(value)
                if parsed.netloc != expected.netloc or parsed.path != expected.path:
                    continue
                for line in parse_qs(parsed.query).get("line") or []:
                    query = urlencode({"line": str(line)})
                    add(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, "")))
            except (TypeError, ValueError):
                continue
        add(self._hls(vid, seq))
        return result

    def _valid_hls(self, url):
        if not self._http_url(url):
            self.last_hls_error = "invalid_url"
            return False
        headers = self._media_headers()
        headers["Range"] = "bytes=0-%s" % (self.max_playlist_bytes - 1)
        headers["Content-Type"] = None
        for attempt in range(2):
            try:
                with self._host_route(attempt):
                    with self.session.get(url, headers=headers, timeout=(8, 20), stream=True) as response:
                        status = response.status_code
                        if status in (408, 425, 429) or 500 <= status <= 599:
                            raise _ApiError("hls_http_%s" % status, True)
                        if status not in (200, 206):
                            self.last_hls_error = "hls_http_%s" % status
                            return False
                        body = self._read_limited(response, self.max_playlist_bytes)
                if body.lstrip(b"\xef\xbb\xbf\x00\t\r\n ").startswith(b"#EXTM3U"):
                    self.last_hls_error = ""
                    return True
                self.last_hls_error = "invalid_hls_body"
                return False
            except _ApiError as exc:
                retryable = exc.retryable
                self.last_hls_error = exc.code
            except (requests.Timeout, requests.ConnectionError):
                retryable = True
                self.last_hls_error = "hls_connection_error"
            except (requests.RequestException, ValueError, TypeError, OSError):
                retryable = False
                self.last_hls_error = "hls_request_error"
            if attempt == 0 and retryable:
                time.sleep(0.2)
                continue
            break
        return False

    def _http_url(self, url):
        try:
            parsed = urlsplit(str(url or ""))
            return parsed.scheme in ("http", "https") and bool(parsed.netloc) and not parsed.username
        except (TypeError, ValueError):
            return False

    def _url_expiry(self, url):
        now = int(time.time())
        try:
            values = parse_qs(urlsplit(url).query).get("exp") or []
            expiry = int(values[0]) if values else 0
            if expiry > now + 15:
                return min(expiry - 10, now + 300)
        except (TypeError, ValueError, IndexError):
            pass
        return now + 60

    def _media_headers(self):
        return {"User-Agent": self.headers["User-Agent"], "Referer": self.host + "/", "Origin": self.host}

    def _player(self, url, msg=None):
        result = {"parse": 0, "playUrl": "", "url": url, "jx": 0, "header": self._media_headers()}
        if msg:
            result["msg"] = str(msg)
        return result

    def _player_error(self, error):
        return {"parse": 0, "playUrl": "", "url": "", "jx": 0, "header": self._media_headers(), "msg": str(error or "播放线路不可用")}

    def _play_error(self, obj):
        if isinstance(obj, dict) and not self._api_ok(obj):
            code, detail = self._api_failure(obj)
            if code == "813005":
                return "本集需要金币解锁，当前账号看不了完整片"
            if code in ("2002", "2001"):
                return "这集要官方账号登录后才能播，本源只能放免费集"
            return "这集暂时播不了（%s%s）" % (code, "：" + detail if detail else "")
        return "这集暂时播不了，换一集试试"

    def _classes(self):
        if self.class_cache:
            return self.class_cache
        arr = [{"type_id": "all", "type_name": "全部短剧"}]
        data = self._api("/drama/navList", {})
        for item in self._list(data.get("data", data) if isinstance(data, dict) else data):
            tid = str(item.get("code") or item.get("id") or item.get("cat_id") or "")
            name = item.get("name") or item.get("title") or tid
            if tid and name:
                arr.append({"type_id": tid, "type_name": name})
        self.class_cache = arr
        return arr

    def _filters(self, classes):
        common = [{"key": "order", "name": "排序", "value": [{"n": "默认", "v": ""}, {"n": "最新", "v": "new"}, {"n": "最热", "v": "hot"}]}, {"key": "update_status", "name": "状态", "value": [{"n": "全部", "v": ""}, {"n": "连载", "v": "0"}, {"n": "完结", "v": "1"}]}]
        fs = {}
        for c in classes:
            tid = c["type_id"]
            tabs = self._nav_filter(tid) if tid not in ("all", "yuandou") else []
            fs[tid] = ([{"key": "sub", "name": "子分类", "value": [{"n": t.get("name", "默认"), "v": str(i)} for i, t in enumerate(tabs)]}] if tabs else []) + common
        return fs

    def _nav_filter(self, code):
        if code not in self.filter_cache:
            data = self._api("/drama/navFilter", {"code": str(code)})
            self.filter_cache[code] = self._list(data.get("data", data) if isinstance(data, dict) else data)
        return self.filter_cache.get(code, [])

    def _list(self, data):
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        if isinstance(data.get("list"), list):
            return data["list"]
        if isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data.get("data"), list):
            return data["data"]
        if isinstance(data.get("data"), dict):
            return self._list(data["data"])
        return []

    def _nav_items(self, data):
        blocks = self._list(data.get("data", data) if isinstance(data, dict) else data)
        items = []
        for b in blocks:
            if isinstance(b, dict) and isinstance(b.get("items"), list):
                items += b.get("items")
            elif isinstance(b, dict) and (b.get("id") or b.get("drama_id")):
                items.append(b)
        return items

    def _vod(self, item):
        item = item or {}
        vid = self._sid(item.get("id") or item.get("drama_id") or "")
        remarks = item.get("update_label") or item.get("corner") or ("全%s集" % item.get("episode_count") if item.get("episode_count") else "")
        return {"vod_id": vid, "vod_name": item.get("name") or item.get("title") or item.get("t") or vid, "vod_pic": self._pic(item), "vod_remarks": remarks}

    def _pic(self, item):
        value = item.get("img_y") or item.get("img_x") or item.get("img") or item.get("cover") or item.get("pic") or ""
        return urljoin(self.host + "/", str(value)) if value else ""

    def _episode_access(self, d):
        # 返回 (免费集 seq 集合, 是否整部免费, 各集价格)
        eps = d.get("episodes") if isinstance(d.get("episodes"), list) else []
        free_seqs = set()
        price_of = {}
        free_count = self._int(d.get("free_episodes"), -1)
        for i, ep in enumerate(eps, 1):
            if not isinstance(ep, dict):
                continue
            seq = str(ep.get("seq") or ep.get("episode") or ep.get("ep") or i)
            price = self._int(ep.get("price"), 0)
            if price:
                price_of[seq] = price
            for method in ep.get("methods") or []:
                if isinstance(method, dict) and self._int(method.get("price"), 0):
                    price_of.setdefault(seq, self._int(method.get("price"), 0))
            if not price and str(ep.get("type") or "").strip().lower() == "free":
                free_seqs.add(seq)
        if not eps:
            if free_count <= 0:
                return set(), False, {}
            return set(str(x) for x in range(1, free_count + 1)), False, {}
        if free_count < 0:
            return free_seqs, bool(eps) and len(free_seqs) >= len(eps), price_of
        if free_count == 0:
            # 实测 free_episodes=0 的剧目是整部免费（188 集/100 集实测全集可播）；
            # 但分集里若出现明确付费类型的集，以分集为准，不误判成免费。
            paid_like = [str(ep.get("seq") or i) for i, ep in enumerate(eps, 1)
                         if isinstance(ep, dict) and (self._int(ep.get("price"), 0) > 0 or str(ep.get("type") or "").strip().lower() in ("coin", "vip", "pay"))]
            if paid_like:
                return free_seqs, False, price_of
            return free_seqs, True, price_of
        return set(str(x) for x in range(1, free_count + 1)), False, price_of

    def _access_of(self, vid):
        cached = self.detail_cache.get(vid)
        if isinstance(cached, dict) and cached.get("expires", 0) > time.time():
            return cached.get("access")
        obj = self._api("/drama/detail", {"id": vid})
        data = obj.get("data", obj) if isinstance(obj, dict) else {}
        if not isinstance(data, dict) or not data:
            return None
        access = self._episode_access(data)
        self.detail_cache[vid] = {"access": access, "expires": time.time() + 21600}
        return access

    def _sid(self, x):
        value = str(x or "")
        return value[3:] if value.startswith("rp_") else value

    def _split(self, x):
        p = str(x).split("|", 1)
        seq = max(1, self._int(p[1], 1)) if len(p) > 1 else 1
        return self._sid(p[0]), str(seq)

    def _hls(self, vid, seq):
        return "%s/api/drama/hls/%s/%s/play.m3u8?line=free" % (self.host, self._sid(vid), seq)

    def _int(self, x, d=0):
        try:
            return int(x)
        except Exception:
            return d
