from pathlib import Path
import json
import random

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from astrbot.core.star.filter import HandlerFilter
from astrbot.core.star.register.star_handler import get_handler_or_create
from astrbot.core.star.star_handler import EventType
from astrbot.core.config import AstrBotConfig

class DecreaseTypeFilter(HandlerFilter):
    """检查主动退群事件"""
    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        raw_message = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw_message, dict):
            return False
        return (
                raw_message.get('post_type', None) == 'notice' and
                raw_message.get('notice_type', None) == 'group_decrease' and
                raw_message.get('sub_type', None) == 'leave'
        )

def register_decrease_type(**kwargs):
    """注册一个 PackTypeFilter"""
    def decorator(awaitable):
        handler_md = get_handler_or_create(awaitable, EventType.AdapterMessageEvent)
        handler_md.event_filters.append(
            DecreaseTypeFilter(),
        )
        return awaitable
    return decorator

@register(
    "NullDox",
    "lishining",
    "伪造虚假的用户信息来假装开盒",
    "1.0.0"
)
class NullDoxPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.location_data: dict = {}
        self.location_pool: list[str] = []
        self._load_location_data()

    @filter.command("盒")
    async def use_dox(self, event: AstrMessageEvent, qq: str):
        if not self._validate_qq(qq):
            yield event.plain_result("QQ号格式错误，请使用纯数字")
            return
        yield event.plain_result(f"🚨 开始对 {qq} 进行盒打击")
        output_text = self.generate_fake_dox(qq)
        wife_avatar = f"https://q4.qlogo.cn/headimg_dl?dst_uin={qq}&spec=640"
        chain = [
            Comp.Plain(output_text),
            Comp.Image.fromURL(wife_avatar),
        ]
        yield event.chain_result(chain)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @register_decrease_type()
    async def decrease_dox(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        sender_id = str(event.get_sender_id())
        is_group = group_id is not None
        if not is_group:
            return
        yield event.plain_result(f"🚨 检测到 {sender_id} 退出群聊,正在进行盒打击")
        output_text = self.generate_fake_dox(
            sender_id,
            str(group_id)
        )
        wife_avatar = f"https://q4.qlogo.cn/headimg_dl?dst_uin={sender_id}&spec=640"
        chain = [
            Comp.Plain(output_text),
            Comp.Image.fromURL(wife_avatar),
        ]
        yield event.chain_result(chain)

    # 生成假数据
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
        """将位置JSON加载到内存中并扁平化以便随机选择"""
        data_path = Path(__file__).resolve().parent / "china_clean_v2.json"
        try:
            if not data_path.exists():
                logger.warning(f"[NullDox] 位置文件不存在: {data_path}")
                return

            with data_path.open("r", encoding="utf-8") as file:
                self.location_data = json.load(file)

            if not isinstance(self.location_data, dict):
                logger.warning("[NullDox] 位置数据格式无效，预期为字典类型")
                self.location_data = {}
                return

            self.location_pool = self._flatten_locations(self.location_data)
            logger.info(f"[NullDox] 已加载 {len(self.location_pool)} 个位置信息到内存")
        except json.JSONDecodeError as exc:
            logger.error(f"[NullDox] 解析位置JSON文件失败: {exc}")
            self.location_data = {}
            self.location_pool = []
        except Exception as exc:
            logger.error(f"[NullDox] 加载位置数据失败: {exc}")
            self.location_data = {}
            self.location_pool = []

    # 扁平化
    def _flatten_locations(self, data: dict) -> list[str]:
        """将嵌套的位置JSON扁平化为可读地址"""
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
                            locations.append(f"{province_name}{city_name}{district_name}")
                            continue

                        for street_name in streets.keys():
                            locations.append(f"{province_name}{city_name}{district_name}{street_name}")

        return locations

    # 检测QQ号是否合法
    def _validate_qq(self, qq: str) -> bool:
        """验证QQ号是否合法（只包含数字）"""
        if not qq or not isinstance(qq, str):
            return False
        if not qq.isdigit():
            logger.warning(f"检测到非法QQ号格式: {qq}")
            return False
        return True

    # 生成手机号
    def _generate_phone(self) -> str:
        """生成假的手机号"""
        # 常见手机号段
        prefixes = [
            "130",
            "131",
            "132",
            "133",
            "135",
            "136",
            "137",
            "138",
            "139",
            "150",
            "151",
            "152",
            "155",
            "156",
            "157",
            "158",
            "159",
            "166",
            "177",
            "180",
            "181",
            "182",
            "183",
            "184",
            "185",
            "186",
            "187",
            "188",
            "189",
            "198",
            "199",
        ]
        prefix = random.choice(prefixes)
        suffix = "".join(str(random.randint(0, 9)) for _ in range(8))
        return f"{prefix}{suffix}"

    # 生成IP地址
    def _generate_ip(self) -> str:
        """生成假的 IP 地址"""
        # 保留一些私有 IP 段作为假数据更真实
        # 避免生成 0.0.0.0 或 255.255.255.255 这种无效地址
        first = random.choice(
            [58, 61, 110, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 172, 192]
        )
        second = random.randint(1, 255)
        third = random.randint(0, 255)
        fourth = random.randint(1, 254)
        return f"{first}.{second}.{third}.{fourth}"

    # 生成地理位置
    def _generate_location(self) -> str:
        """随机生成地理位置"""
        if self.location_pool:
            return random.choice(self.location_pool)
        return "四川省成都市金牛区"

    # 初始化插件
    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法"""
        pass

    # 清理资源
    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会被调用"""
        pass
