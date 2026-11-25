"""武器归类边界：完美平台皮肤后缀（_vip/_txzNN）必须剥离后再归类。

场景：
- ak47_vip / m4a1_silencer_vip → rifle（此前 _vip 落 other，污染对枪矩阵）
- awp_txz01 → sniper（既有行为回归）
- 刀/雷/环境死亡独立归类，不再混入 other
"""

from app.services.demo_analysis import weapon_class


def test_vip_suffix_stripped_to_rifle():
    """Given 完美 vip 皮肤后缀，When 归类，Then 得到底层武器类（rifle）。"""
    assert weapon_class("ak47_vip") == "rifle"
    assert weapon_class("m4a1_silencer_vip") == "rifle"
    assert weapon_class("M4A1_VIP") == "rifle"  # 大小写不敏感


def test_txz_suffix_regression():
    """Given txz 后缀，When 归类，Then 保持既有剥离行为。"""
    assert weapon_class("awp_txz01") == "sniper"
    assert weapon_class("ak47_txz06") == "rifle"


def test_melee_grenade_env_classes():
    """Given 刀/手雷/燃烧/环境致死，When 归类，Then 不落入 other（对枪矩阵纯净）。"""
    assert weapon_class("knife_push") == "melee"
    assert weapon_class("knife") == "melee"
    assert weapon_class("hegrenade") == "nade"
    assert weapon_class("inferno") == "nade"
    assert weapon_class("planted_c4") == "env"
    assert weapon_class("world") == "env"
    # inferno 带皮肤后缀也要归 nade
    assert weapon_class("inferno_vip") == "nade"


def test_unknown_still_other():
    """Given 真正未知武器名，When 归类，Then other 兜底。"""
    assert weapon_class("mystery_gun_9000") == "other"
