import asyncio
import hashlib
import json
import os
import random
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.config import AstrBotConfig
from astrbot.core.star.filter import HandlerFilter
from astrbot.core.star.register.star_handler import get_handler_or_create
from astrbot.core.star.star_handler import EventType


TENCENT_MAP_API_BASE = "https://apis.map.qq.com"
TENCENT_MAP_PLACE_SEARCH_PATH = "/ws/place/v1/search"
TENCENT_MAP_STATIC_PATH = "/ws/staticmap/v2/"
DEFAULT_PLACE_KEYWORDS = ["公园", "商场", "酒店", "学校", "医院", "地铁站", "景点", "美食"]


@dataclass(frozen=True)
class GeneratedLocation:
    """一次虚构地址生成的结果。"""

    address: str
    map_url: str | None = None


class DecreaseTypeFilter(HandlerFilter):
    """检查活跃的群成员减少通知事件"""
    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        raw_message = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw_message, dict):
            return False
        return (
            raw_message.get("post_type") == "notice"
            and raw_message.get("notice_type") == "group_decrease"
            and raw_message.get("sub_type") == "leave"
        )

def register_decrease_type(**kwargs):
    """注册一个用于群成员离开事件的自定义过滤器"""
    def decorator(awaitable):
        handler_md = get_handler_or_create(awaitable, EventType.AdapterMessageEvent)
        handler_md.event_filters.append(DecreaseTypeFilter())
        return awaitable
    return decorator

@register(
    "NullDox",
    "lishining",
    "生成虚假用户信息，仅供娱乐。",
    "1.0.4",
)
class NullDoxPlugin(Star):
    """开盒插件：生成虚假的用户信息"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self.location_data: dict = {}
        self.location_pool: list[str] = []
        self.search_region_pool: list[dict[str, str]] = []
        self._load_location_data()

    @filter.command("盒")
    async def use_dox(self, event: AstrMessageEvent, qq: str = ""):
        """使用 /盒 [QQ号] 生成虚假开盒信息"""
        sender_id = event.get_sender_id()
        if sender_id and not self._is_user_allowed(str(sender_id)):
            yield event.plain_result("当前账号未启用该功能")
            return

        target_id = None
        for component in event.message_obj.message:
            if isinstance(component, Comp.At):
                target_id = str(component.qq)
        
        if target_id is None:
            qq = str(qq)
            if not self._validate_qq(qq):
                yield event.plain_result("QQ号格式错误，请使用纯数字")
                return
        else:
            qq = target_id
        yield event.plain_result(f"🚨 开始对 {qq} 进行盒打击")
        output_text, map_url = await self.generate_fake_dox(qq)
        avatar = f"https://q4.qlogo.cn/headimg_dl?dst_uin={qq}&spec=640"
        chain = [
            Comp.Plain(output_text),
            Comp.Image.fromURL(avatar),
        ]
        if map_url:
            chain.append(Comp.Image.fromURL(map_url))
        yield event.chain_result(chain)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @register_decrease_type()
    async def decrease_dox(self, event: AstrMessageEvent):
        """监听群成员离开事件，生成虚假开盒信息"""
        group_id = event.get_group_id()
        sender_id = str(event.get_sender_id())
        if group_id is None:
            return

        if not self._is_group_allowed(
            group_id, getattr(event, "unified_msg_origin", None)
        ):
            return

        yield event.plain_result(f"🚨 检测到 {sender_id} 退出群聊，正在进行开盒")
        output_text, map_url = await self.generate_fake_dox(sender_id, str(group_id))
        avatar = f"https://q4.qlogo.cn/headimg_dl?dst_uin={sender_id}&spec=640"
        chain = [
            Comp.Plain(output_text),
            Comp.Image.fromURL(avatar),
        ]
        if map_url:
            chain.append(Comp.Image.fromURL(map_url))
        yield event.chain_result(chain)

    # 生成假数据
    async def generate_fake_dox(
        self, sender_id: str, group_id: str | None = None
    ) -> tuple[str, str | None]:
        """
        生成完整的假开盒信息
        sender_id: 发送者账号
        group_id: 群号（可选）
        """
        location = await self._generate_location()
        output = f"🔍 身份检索完毕\n"
        output += f"🆔 账号：{sender_id}\n"

        if group_id:
            output += f"🚪 退出群聊：{group_id}\n"

        output += f"📱 手机：{self._generate_phone()}\n"
        output += f"🌐 IP地址：{self._generate_ip()}\n"
        output += f"📍 物理地址：{location.address}"
        if location.map_url:
            output += "\n🗺️ 已生成位置静态图"

        return output.strip(), location.map_url

    # 加载地理位置JSON数据
    def _load_location_data(self) -> None:
        """加载地理位置JSON数据，并展开为扁平列表"""
        data_path = Path(__file__).resolve().parent / "china_clean_v2.json"
        try:
            if not data_path.exists():
                logger.warning(f"[NullDox] 未找到地理位置文件：{data_path}")
                return

            with data_path.open("r", encoding="utf-8") as file:
                self.location_data = json.load(file)

            if not isinstance(self.location_data, dict):
                logger.warning("[NullDox] 地理位置数据格式无效，应为字典类型")
                self.location_data = {}
                return

            self.location_pool = self._flatten_locations(self.location_data)
            self.search_region_pool = self._flatten_search_regions(self.location_data)
            logger.info(
                f"[NullDox] 已加载 {len(self.location_pool)} 条地理位置数据"
            )
        except json.JSONDecodeError as exc:
            logger.error(f"[NullDox] 解析地理位置JSON失败：{exc}")
            self.location_data = {}
            self.location_pool = []
            self.search_region_pool = []
        except Exception as exc:
            logger.error(f"[NullDox] 加载地理位置数据失败：{exc}")
            self.location_data = {}
            self.location_pool = []
            self.search_region_pool = []

    # 将嵌套的地理位置JSON展开为可读地址列表
    def _flatten_locations(self, data: dict) -> list[str]:
        """将嵌套的地理位置JSON展开为可读地址列表"""
        locations: list[str] = []
        for provinces in data.values():
            if not isinstance(provinces, dict):
                continue

            for province_name, cities in provinces.items():
                if not isinstance(cities, dict):
                    locations.append(str(province_name))
                    continue

                for city_name, districts in cities.items():
                    if not isinstance(districts, dict) or not districts:
                        locations.append(f"{province_name}{city_name}")
                        continue

                    for district_name, streets in districts.items():
                        if not isinstance(streets, dict) or not streets:
                            locations.append(
                                f"{province_name}{city_name}{district_name}"
                            )
                            continue

                        for street_name in streets.keys():
                            locations.append(
                                f"{province_name}{city_name}{district_name}{street_name}"
                            )

        return locations

    def _flatten_search_regions(self, data: dict) -> list[dict[str, str]]:
        """展开地区数据，保留适合腾讯地点搜索的城市/区县边界。"""
        regions: list[dict[str, str]] = []
        for provinces in data.values():
            if not isinstance(provinces, dict):
                continue

            for province_name, cities in provinces.items():
                if not isinstance(cities, dict):
                    continue

                for city_name, districts in cities.items():
                    if not isinstance(districts, dict) or not districts:
                        regions.append(
                            {
                                "region": str(city_name),
                                "prefix": f"{province_name}{city_name}",
                            }
                        )
                        continue

                    for district_name, streets in districts.items():
                        street_name = self._pick_street_name(streets)
                        prefix = f"{province_name}{city_name}{district_name}"
                        if street_name:
                            prefix += street_name
                        regions.append(
                            {
                                "region": str(city_name),
                                "prefix": prefix,
                            }
                        )

        return regions

    def _pick_street_name(self, streets: object) -> str:
        """从街道字典中随机取一个街道名，用于拼出更完整的虚构地址。"""
        if not isinstance(streets, dict) or not streets:
            return ""
        return str(random.choice(list(streets.keys())))

    # 验证QQ号格式是否正确
    def _validate_qq(self, qq: str) -> bool:
        """验证QQ号格式是否正确"""
        if not qq or not isinstance(qq, str):
            return False
        if not qq.isdigit():
            logger.warning(f"检测到无效的QQ格式：{qq}")
            return False
        return True

    # 检查当前用户是否有权限使用该命令
    def _is_user_allowed(self, user_id: str | None) -> bool:
        """检查当前用户是否有权限使用该命令"""
        if not user_id:
            return True

        mode = str(self.config.get("user_list_mode", "none")).lower()
        if mode not in {"whitelist", "blacklist", "none"}:
            mode = "none"
        if mode == "none":
            return True

        user_list = {str(item) for item in self.config.get("user_list", [])}
        is_in_list = str(user_id) in user_list
        if mode == "whitelist":
            return is_in_list
        if mode == "blacklist":
            return not is_in_list
        return True

    # 检查是否允许在该群组中监听成员离开事件
    def _is_group_allowed(
        self, group_id: int | str | None, unified_msg_origin: str | None = None
    ) -> bool:
        """检查是否允许在该群组中监听成员离开事件"""
        if not group_id:
            return True

        mode = str(self.config.get("group_list_mode", "none")).lower()
        if mode not in {"whitelist", "blacklist", "none"}:
            mode = "none"
        if mode == "none":
            return True

        group_list = [str(item) for item in self.config.get("group_list", [])]
        target = str(unified_msg_origin or group_id)
        target_simple_id = target.split(":")[-1] if ":" in target else target
        target_parent_id = (
            target_simple_id.split("#", 1)[0]
            if "#" in target_simple_id
            else target_simple_id
        )

        def _is_match(item: str) -> bool:
            if ":" in item:
                if item == target:
                    return True
                if ":" not in target or "#" not in target_simple_id:
                    return False

                item_prefix, item_tail = item.rsplit(":", 1)
                target_prefix, _ = target.rsplit(":", 1)
                return item_prefix == target_prefix and item_tail == target_parent_id

            if item == target_simple_id:
                return True
            return "#" in target_simple_id and item == target_parent_id

        is_in_list = any(_is_match(item) for item in group_list)
        if mode == "whitelist":
            return is_in_list
        if mode == "blacklist":
            return not is_in_list
        return True

    # 生成一个虚假的手机号码
    def _generate_phone(self) -> str:
        """生成一个虚假的手机号码"""
        prefixes = [
            "130", "131", "132", "133", "135", "136", "137", "138", "139",
            "150", "151", "152", "155", "156", "157", "158", "159",
            "166", "177", "180", "181", "182", "183", "184", "185",
            "186", "187", "188", "189", "198", "199"
        ]
        prefix = random.choice(prefixes)
        suffix = "".join(str(random.randint(0, 9)) for _ in range(8))
        return f"{prefix}{suffix}"

    # 生成一个虚假的IP地址
    def _generate_ip(self) -> str:
        """生成一个虚假的IP地址"""
        first = random.choice([
            58, 61, 110, 112, 113, 114, 115, 116, 117, 118, 119,
            120, 121, 122, 123, 124, 125, 126, 127, 172, 192
        ])
        second = random.randint(1, 255)
        third = random.randint(0, 255)
        fourth = random.randint(1, 254)
        return f"{first}.{second}.{third}.{fourth}"

    # 生成一个随机的虚假地理位置
    async def _generate_location(self) -> GeneratedLocation:
        """生成一个随机的虚假地理位置，可选叠加真实POI和静态地图。"""
        fallback_address = self._generate_fallback_location()
        if not self._is_map_enrichment_enabled():
            logger.info("[NullDox] 地图增强未启用，使用本地随机地址")
            return GeneratedLocation(fallback_address)

        api_key = self._get_tencent_map_key()
        secret_key = self._get_tencent_map_sk()
        logger.info(
            "[NullDox] 地图增强已启用，"
            f"key={self._mask_secret(api_key)}, sk_configured={bool(secret_key)}"
        )
        if not api_key:
            logger.warning("[NullDox] 已启用地图增强，但未配置 tencent_map_key")
            return GeneratedLocation(fallback_address)

        region = self._pick_search_region()
        if not region:
            logger.warning("[NullDox] 地图增强回退：未加载到可搜索地区")
            return GeneratedLocation(fallback_address)
        logger.info(
            f"[NullDox] 地图增强选择地区：search_region={region['region']}, "
            f"fallback_prefix={region['prefix']}"
        )

        poi = await self._search_random_poi(api_key, region["region"])
        if not poi:
            logger.warning(
                f"[NullDox] 地图增强回退：地区 {region['region']} 未搜索到有效POI"
            )
            return GeneratedLocation(region["prefix"])

        address = self._format_poi_address(region["prefix"], poi)
        map_url = self._build_static_map_url(api_key, poi)
        logger.info(
            "[NullDox] 地图增强生成成功："
            f"poi_id={poi.get('id')}, title={poi.get('title')}, "
            f"address={address}, map_url_generated={bool(map_url)}"
        )
        return GeneratedLocation(address, map_url)

    def _generate_fallback_location(self) -> str:
        """使用本地行政区数据生成离线虚构地址。"""
        if self.location_pool:
            location = random.choice(self.location_pool)
            logger.info(f"[NullDox] 本地随机地址：{location}")
            return location
        logger.warning("[NullDox] 本地地址池为空，使用默认地址")
        return "四川省成都市金牛区"  # 默认地址

    def _is_map_enrichment_enabled(self) -> bool:
        """是否启用腾讯地图地点搜索与静态图增强。"""
        return bool(self._get_map_config("enable_static_map", False))

    def _get_tencent_map_key(self) -> str:
        """优先读取插件配置，其次读取环境变量，避免把密钥写进代码。"""
        return str(
            self._get_map_config("tencent_map_key", "")
            or os.getenv("TENCENT_MAP_KEY")
            or ""
        ).strip()

    def _get_tencent_map_sk(self) -> str:
        """读取腾讯位置服务 SecretKey；为空时不启用 SN 签名。"""
        return str(
            self._get_map_config("tencent_map_sk", "")
            or os.getenv("TENCENT_MAP_SK")
            or ""
        ).strip()

    def _pick_search_region(self) -> dict[str, str] | None:
        """随机选择一个用于地点搜索的城市/区县。"""
        if not self.search_region_pool:
            logger.warning("[NullDox] 搜索地区池为空")
            return None
        return random.choice(self.search_region_pool)

    async def _search_random_poi(
        self, api_key: str, region_name: str
    ) -> dict | None:
        """在随机地区内搜索一个POI。"""
        keyword = self._pick_place_keyword()
        page_size = self._get_int_config("place_search_page_size", 10, 1, 20)
        logger.info(
            f"[NullDox] 开始腾讯地点搜索：region={region_name}, "
            f"keyword={keyword}, page_size={page_size}"
        )
        params = {
            "key": api_key,
            "keyword": keyword,
            "boundary": f"region({region_name},1)",
            "page_size": str(page_size),
            "page_index": "1",
            "output": "json",
        }
        url = self._build_tencent_get_url(TENCENT_MAP_PLACE_SEARCH_PATH, params)
        logger.info(f"[NullDox] 腾讯地点搜索URL：{self._redact_url(url)}")

        try:
            payload = await self._http_get_json(url)
        except Exception as exc:
            logger.warning(f"[NullDox] 腾讯地点搜索失败：{exc}")
            return None

        if not isinstance(payload, dict) or payload.get("status") != 0:
            logger.warning(
                "[NullDox] 腾讯地点搜索返回异常："
                f"payload={self._summarize_api_payload(payload)}"
            )
            return None

        pois = payload.get("data")
        if not isinstance(pois, list) or not pois:
            logger.warning(
                "[NullDox] 腾讯地点搜索无结果："
                f"count={payload.get('count')}, request_id={payload.get('request_id')}"
            )
            return None
        valid_pois = [poi for poi in pois if isinstance(poi, dict)]
        if not valid_pois:
            logger.warning("[NullDox] 腾讯地点搜索结果格式异常：data中没有有效POI对象")
            return None
        selected = random.choice(valid_pois)
        logger.info(
            "[NullDox] 腾讯地点搜索命中："
            f"request_id={payload.get('request_id')}, count={payload.get('count')}, "
            f"valid_pois={len(valid_pois)}, selected_id={selected.get('id')}, "
            f"selected_title={selected.get('title')}"
        )
        return selected

    def _pick_place_keyword(self) -> str:
        """从配置中选择搜索关键词。"""
        keywords = self._get_map_config("place_search_keywords", DEFAULT_PLACE_KEYWORDS)
        if not isinstance(keywords, list):
            logger.warning("[NullDox] place_search_keywords 配置不是列表，使用默认关键词")
            keywords = DEFAULT_PLACE_KEYWORDS
        normalized = [str(item).strip() for item in keywords if str(item).strip()]
        if not normalized:
            logger.warning("[NullDox] place_search_keywords 为空，使用默认关键词")
            normalized = DEFAULT_PLACE_KEYWORDS
        return random.choice(normalized)

    async def _http_get_json(self, url: str) -> dict:
        """在线程中执行阻塞HTTP请求，避免卡住AstrBot事件循环。"""
        timeout = self._get_int_config("tencent_api_timeout", 5, 1, 30)
        logger.info(f"[NullDox] 发起HTTP请求：timeout={timeout}, url={self._redact_url(url)}")

        def _request() -> dict:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "astrbot-plugin-nulldox/1.0"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read().decode(charset)
                logger.info(
                    f"[NullDox] HTTP响应：status={response.getcode()}, "
                    f"charset={charset}, bytes={len(body.encode(charset, errors='ignore'))}"
                )
            return json.loads(body)

        return await asyncio.to_thread(_request)

    def _format_poi_address(self, region_prefix: str, poi: dict) -> str:
        """把POI结果格式化为更像真实地点的虚构地址。"""
        title = str(poi.get("title") or "").strip()
        address = str(poi.get("address") or "").strip()
        if address and title:
            return f"{address}（{title}）"
        if title:
            return f"{region_prefix}{title}"
        return address or region_prefix

    def _build_static_map_url(self, api_key: str, poi: dict) -> str | None:
        """根据POI坐标构造腾讯静态地图URL。"""
        location = poi.get("location")
        if not isinstance(location, dict):
            logger.warning("[NullDox] 静态地图生成失败：POI缺少location对象")
            return None
        lat = location.get("lat")
        lng = location.get("lng")
        if lat is None or lng is None:
            logger.warning("[NullDox] 静态地图生成失败：POI坐标缺少lat或lng")
            return None

        zoom = self._get_int_config("static_map_zoom", 17, 4, 18)
        size = str(self._get_map_config("static_map_size", "500x400")).strip() or "500x400"
        logger.info(
            f"[NullDox] 构造静态地图：lat={lat}, lng={lng}, zoom={zoom}, size={size}"
        )
        params = {
            "key": api_key,
            "center": f"{lat},{lng}",
            "zoom": str(zoom),
            "size": size,
        }
        return self._build_tencent_get_url(TENCENT_MAP_STATIC_PATH, params)

    def _build_tencent_get_url(self, path: str, params: dict[str, str]) -> str:
        """构造腾讯 WebService GET URL；配置了 SK 时自动追加 sig。"""
        request_params = dict(params)
        secret_key = self._get_tencent_map_sk()
        if secret_key:
            request_params["sig"] = self._sign_tencent_get(path, params, secret_key)
            logger.info(f"[NullDox] 腾讯URL启用SN签名：path={path}")
        else:
            logger.info(f"[NullDox] 腾讯URL未启用SN签名：path={path}")
        query = urllib.parse.urlencode(request_params)
        return f"{TENCENT_MAP_API_BASE}{path}?{query}"

    def _sign_tencent_get(
        self, path: str, params: dict[str, str], secret_key: str
    ) -> str:
        """按腾讯 SN 校验规则计算 GET 请求签名。"""
        raw_query = "&".join(
            f"{key}={params[key]}" for key in sorted(params.keys())
        )
        source = f"{path}?{raw_query}{secret_key}"
        signature = hashlib.md5(source.encode("utf-8")).hexdigest()
        logger.info(
            f"[NullDox] 腾讯SN签名完成：path={path}, params={sorted(params.keys())}, "
            f"sig={self._mask_secret(signature)}"
        )
        return signature

    def _get_map_config(self, key: str, default=None):
        """读取地图增强配置，优先使用 tencent_map 对象，兼容旧扁平字段。"""
        tencent_map = self.config.get("tencent_map", {})
        if hasattr(tencent_map, "get"):
            value = tencent_map.get(key, None)
            if value is not None:
                return value
        value = self.config.get(key, default)
        if key in self.config:
            logger.info(f"[NullDox] 使用旧版扁平地图配置：{key}")
        return value

    def _mask_secret(self, value: str) -> str:
        """遮蔽敏感配置，仅保留少量排查信息。"""
        if not value:
            return "<empty>"
        if len(value) <= 8:
            return f"{value[:2]}***"
        return f"{value[:4]}***{value[-4:]}"

    def _redact_url(self, url: str) -> str:
        """遮蔽URL中的key和sig，便于安全打印日志。"""
        parsed = urllib.parse.urlsplit(url)
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        redacted_pairs = []
        for key, value in pairs:
            if key in {"key", "sig"}:
                value = self._mask_secret(value)
            redacted_pairs.append((key, value))
        query = urllib.parse.urlencode(redacted_pairs)
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment)
        )

    def _summarize_api_payload(self, payload) -> str:
        """压缩腾讯API返回内容，避免日志过长。"""
        if not isinstance(payload, dict):
            return repr(payload)[:300]
        summary = {
            "status": payload.get("status"),
            "message": payload.get("message"),
            "count": payload.get("count"),
            "request_id": payload.get("request_id"),
        }
        return json.dumps(summary, ensure_ascii=False)

    def _get_int_config(
        self, key: str, default: int, minimum: int, maximum: int
    ) -> int:
        """读取并限制整数配置范围。"""
        try:
            value = int(self._get_map_config(key, default))
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, value))

    # 异步插件初始化钩子
    async def initialize(self):
        """异步插件初始化钩子"""
        pass

    # 异步插件清理钩子
    async def terminate(self):
        """可选的异步插件清理钩子"""
        pass
