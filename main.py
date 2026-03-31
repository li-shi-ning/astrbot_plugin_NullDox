import json
import random
from pathlib import Path

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.config import AstrBotConfig
from astrbot.core.star.filter import HandlerFilter
from astrbot.core.star.register.star_handler import get_handler_or_create
from astrbot.core.star.star_handler import EventType


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
    "1.0.0",
)
class NullDoxPlugin(Star):
    """开盒插件：生成虚假的用户信息"""

    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self.location_data: dict = {}      # 地理位置数据
        self.location_pool: list[str] = [] # 地理位置池
        self._load_location_data()

    @filter.command("盒")
    async def use_dox(self, event: AstrMessageEvent, qq: str):
        """使用 /盒 [QQ号] 生成虚假开盒信息"""
        sender_id = event.get_sender_id()
        if sender_id and not self._is_user_allowed(str(sender_id)):
            yield event.plain_result("当前账号未启用该功能")
            return

        target_id = None
        for component in event.message_obj.message:
            if isinstance(component, Comp.At):
                target_id = str(component.qq)
                break

        if target_id is None:
            qq = str(qq)
            if not self._validate_qq(qq):
                yield event.plain_result("QQ号格式错误，请使用纯数字")
                return
        else:
            qq = target_id
        yield event.plain_result(f"🚨 开始对 {qq} 进行盒打击")
        output_text = self.generate_fake_dox(qq)
        avatar = f"https://q4.qlogo.cn/headimg_dl?dst_uin={qq}&spec=640"
        chain = [
            Comp.Plain(output_text),
            Comp.Image.fromURL(avatar),
        ]
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
        output_text = self.generate_fake_dox(sender_id, str(group_id))
        avatar = f"https://q4.qlogo.cn/headimg_dl?dst_uin={sender_id}&spec=640"
        chain = [
            Comp.Plain(output_text),
            Comp.Image.fromURL(avatar),
        ]
        yield event.chain_result(chain)

    def generate_fake_dox(self, sender_id: str, group_id: str | None = None):
        """
        生成完整的假开盒信息
        sender_id: 发送者账号
        group_id: 群号（可选）
        """
        output = f"🔍 身份检索完毕\n"
        output += f"🆔 账号：{sender_id}\n"

        if group_id:
            output += f"🚪 退出群聊：{group_id}\n"

        output += f"📱 手机：{self._generate_phone()}\n"
        output += f"🌐 IP地址：{self._generate_ip()}\n"
        output += f"📍 物理地址：{self._generate_location()}"

        return output.strip()

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
            logger.info(
                f"[NullDox] 已加载 {len(self.location_pool)} 条地理位置数据"
            )
        except json.JSONDecodeError as exc:
            logger.error(f"[NullDox] 解析地理位置JSON失败：{exc}")
            self.location_data = {}
            self.location_pool = []
        except Exception as exc:
            logger.error(f"[NullDox] 加载地理位置数据失败：{exc}")
            self.location_data = {}
            self.location_pool = []

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

    def _validate_qq(self, qq: str) -> bool:
        """验证QQ号格式是否正确"""
        if not qq or not isinstance(qq, str):
            return False
        if not qq.isdigit():
            logger.warning(f"检测到无效的QQ格式：{qq}")
            return False
        return True

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

    def _generate_location(self) -> str:
        """生成一个随机的虚假地理位置"""
        if self.location_pool:
            return random.choice(self.location_pool)
        return "四川省成都市金牛区"  # 默认地址

    async def initialize(self):
        """可选的异步插件初始化钩子"""
        pass

    async def terminate(self):
        """可选的异步插件清理钩子"""
        pass
