"""高光检测契约（借鉴 cs2-highlights-maker 评分思路，纯解析版）：击杀聚类 → 可看性评分 → TopN。

评分公式：kills×2 + 爆头×1 + 特殊击杀(刀/zeus/noscope/穿墙 各+1) + 多杀加成(3K+2/4K+5/ACE+8)
         + 回合胜利+1 + 残局起点(队内存活≤2) +2；单时刻击杀 <2 不收录。
"""
import polars as pl

from app.services.highlight import detect_highlights


def _kills(rows):
    cols = ["attacker_steamid", "victim_steamid", "attacker_side", "weapon", "tick",
            "headshot", "noscope", "penetrated"]
    data = {c: [] for c in cols}
    for r in rows:
        for c in cols:
            data[c].append(r.get(c))
    return pl.DataFrame(data)


def _rounds():
    return pl.DataFrame([
        {"round_num": 1, "start_tick": 0, "official_end_tick": 2000, "winner_side": "counter-terrorist"},
        {"round_num": 2, "start_tick": 2001, "official_end_tick": 4000, "winner_side": "terrorist"},
        {"round_num": 3, "start_tick": 4001, "official_end_tick": 6000, "winner_side": "counter-terrorist"},
    ])


CT = "counter-terrorist"
T = "terrorist"


def test_detect_highlights_clusters_and_scores():
    """
    Given R1 三杀（2 爆头 + 1 刀，20s 内）胜局、R2 双杀（先死 3 队友的残局起点）、R3 单杀
    When  detect_highlights
    Then  R1 时刻 score=6+2+1+2+1=12 标"3K"排第一；R2 score=4+2=6 标"双杀" clutch=True；
          R3 单杀不收录
    """
    sid, foe = 111, 222
    kills = _kills([
        # R1：user 三杀（间隔 <1280 tick）
        {"attacker_steamid": sid, "victim_steamid": foe, "attacker_side": CT, "weapon": "m4a1", "tick": 100,
         "headshot": True, "noscope": False, "penetrated": False},
        {"attacker_steamid": sid, "victim_steamid": 223, "attacker_side": CT, "weapon": "m4a1", "tick": 200,
         "headshot": True, "noscope": False, "penetrated": False},
        {"attacker_steamid": sid, "victim_steamid": 224, "attacker_side": CT, "weapon": "knife", "tick": 300,
         "headshot": False, "noscope": False, "penetrated": False},
        # R2：队友先死 3 个（残局起点），user 双杀
        {"attacker_steamid": foe, "victim_steamid": 331, "attacker_side": T, "weapon": "ak47", "tick": 3500,
         "headshot": False, "noscope": False, "penetrated": False},
        {"attacker_steamid": foe, "victim_steamid": 332, "attacker_side": T, "weapon": "ak47", "tick": 3600,
         "headshot": False, "noscope": False, "penetrated": False},
        {"attacker_steamid": foe, "victim_steamid": 333, "attacker_side": T, "weapon": "ak47", "tick": 3700,
         "headshot": False, "noscope": False, "penetrated": False},
        {"attacker_steamid": sid, "victim_steamid": foe, "attacker_side": CT, "weapon": "awp", "tick": 5000,
         "headshot": False, "noscope": False, "penetrated": False},
        {"attacker_steamid": sid, "victim_steamid": 223, "attacker_side": CT, "weapon": "awp", "tick": 6000,
         "headshot": False, "noscope": False, "penetrated": False},
        # R3：单杀（低于 min_kills=2）
        {"attacker_steamid": sid, "victim_steamid": foe, "attacker_side": CT, "weapon": "m4a1", "tick": 5000,
         "headshot": False, "noscope": False, "penetrated": False},
    ])
    out = detect_highlights(kills, _rounds(), sid, CT)
    assert len(out) == 2
    top, second = out
    assert top.round_no == 1 and top.kills == 3 and top.headshots == 2
    assert top.label == "3K" and top.score == 12 and top.round_won is True and top.clutch is False
    assert second.round_no == 2 and second.kills == 2 and second.label == "双杀"
    assert second.score == 6 and second.clutch is True and second.round_won is False


def test_detect_highlights_empty_and_enemy_only():
    """
    Given 无击杀 / 仅对方击杀
    When  detect_highlights
    Then  返回空列表（不臆造高光）
    """
    sid, foe = 111, 222
    assert detect_highlights(_kills([]), _rounds(), sid, CT) == []
    enemy_only = _kills([
        {"attacker_steamid": foe, "victim_steamid": sid, "attacker_side": T, "weapon": "ak47", "tick": 100,
         "headshot": False, "noscope": False, "penetrated": False},
    ])
    assert detect_highlights(enemy_only, _rounds(), sid, CT) == []


def test_detect_highlights_ace_label():
    """
    Given R1 内 5 杀
    When  detect_highlights
    Then  label=ACE 且多杀加成 8 分
    """
    sid, foe = 111, 222
    rows = [
        {"attacker_steamid": sid, "victim_steamid": foe + i, "attacker_side": CT, "weapon": "m4a1",
         "tick": 100 + i * 100, "headshot": False, "noscope": False, "penetrated": False}
        for i in range(5)
    ]
    out = detect_highlights(_kills(rows), _rounds(), sid, CT)
    assert len(out) == 1
    assert out[0].label == "ACE" and out[0].score == 10 + 8 + 1  # kills×2 + ACE加成 + 胜局
