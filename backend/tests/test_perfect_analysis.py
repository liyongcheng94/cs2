"""完美风格完整对局分析（perfect_analysis）场景测试。

场景（Given/When/Then）：
1. side 过滤：给定我 T/CT 各若干回合，When side="T"，Then 只统计 T 回合的击杀/死亡/回合数。
2. 综合数据：给定 kills（含 assister/headshot/distance）+ hurts（伤害），Then KDA/助攻/爆头率/ADR 正确。
3. 突破分析：给定每回合首个击杀事件，Then 首杀/首死归因正确。
4. 补枪分析：给定队友死亡→我在 5s 内击杀凶手，Then 记一次补枪成功；超过 5s 不算；我死→队友复仇记"创造机会"。
5. 残局分析：给定我方其他人全死、对面还剩 2 人，Then 记 1v2；回合赢记"胜利"，我存活回合输记"保枪"，我死且回合输记"失败"。
6. 道具分析：给定闪光事件（致盲敌/友），Then 敌/友致盲数、闪光助攻正确。
7. 对位分析：给定我与某对手互杀若干次，Then 矩阵行包含对方且 K/D/伤害正确。
8. 边界：无任何事件 → 返回空结构不崩溃。
"""
from __future__ import annotations

import pytest

from app.services.perfect_analysis import analyze_perfect

MY = 76561198339750836
MATE = 11111111111111111
EN1 = 22222222222222222
EN2 = 33333333333333333
EN3 = 44444444444444444


def _round(no, start, end, winner, my_side):
    return {"round": no, "start_tick": start, "end_tick": end, "winner": winner, "my_side": my_side}


def _kill(tick, attacker, victim, weapon="ak47", headshot=False, assister=None, distance=15.0):
    return {
        "tick": tick, "attacker_steamid": attacker, "user_steamid": victim,
        "weapon": weapon, "headshot": headshot, "assister_steamid": assister,
        "distance": distance, "attacker_name": f"p{attacker % 100}", "user_name": f"p{victim % 100}",
    }


def _hurt(tick, attacker, victim, dmg=30):
    return {"tick": tick, "attacker_steamid": attacker, "user_steamid": victim, "dmg_health": dmg}


def _flash(tick, thrower, blinded):
    return {"tick": tick, "thrower_steamid": thrower, "blinded_steamids": blinded}


@pytest.fixture
def basic_events():
    """两个回合：R1 我 T 赢，R2 我 CT 输。事件混在两个回合里。"""
    rounds = [
        _round(1, 1000, 5000, "T", "T"),
        _round(2, 6000, 9000, "T", "CT"),  # 对面 T 赢 → 我输
    ]
    kills = [
        # R1: 我首杀 EN1（爆头，中距离），随后队友死、我 3s 内补枪 EN2
        _kill(1200, MY, EN1, headshot=True, distance=20.0),
        _kill(2000, EN2, MATE, distance=10.0),
        _kill(2300, MY, EN2, headshot=False, distance=12.0),  # 补枪成功
        # R2: EN3 首杀我，EN1 后被 MATE 复仇（为我创造补枪机会）
        _kill(6200, EN3, MY, distance=8.0),
        _kill(6400, MATE, EN3, distance=9.0),
    ]
    hurts = [
        _hurt(1150, MY, EN1, dmg=110),
        _hurt(2280, MY, EN2, dmg=95),
        _hurt(6180, EN3, MY, dmg=100),
    ]
    flashes = [_flash(1500, MY, [EN1, EN2, MATE])]  # 致盲2敌1友
    return {"rounds": rounds, "kills": kills, "hurts": hurts, "flashes": flashes}


class TestSideFilter:
    def test_t_side_only_counts_t_rounds(self, basic_events):
        """场景1：side=T 只统计 T 回合。R1 是我的 T 回合，R2 是 CT。"""
        res = analyze_perfect(basic_events, MY, side="T")
        assert res.summary.rounds == 1
        assert res.summary.kills == 2  # R1 我两个击杀
        assert res.summary.deaths == 0
        res_ct = analyze_perfect(basic_events, MY, side="CT")
        assert res_ct.summary.rounds == 1
        assert res_ct.summary.kills == 0
        assert res_ct.summary.deaths == 1

    def test_all_counts_everything(self, basic_events):
        assert analyze_perfect(basic_events, MY, side="ALL").summary.rounds == 2


class TestSummary:
    def test_kda_assists_hs_adr(self, basic_events):
        """场景2：KDA/助攻/爆头率/ADR。ALL 视角。"""
        res = analyze_perfect(basic_events, MY, side="ALL")
        s = res.summary
        assert s.kills == 2 and s.deaths == 1
        assert s.assists == 0
        assert s.hs_kills == 1  # 只有 R1 第一杀是爆头
        assert s.adr == pytest.approx((110 + 95) / 2)  # 我造成的伤害 / 2 回合
        assert s.round_wins == 1


class TestEntry:
    def test_entry_kills_and_deaths(self, basic_events):
        """场景3：R1 我拿首杀，R2 我是首死。"""
        res = analyze_perfect(basic_events, MY, side="ALL")
        assert res.entry.entry_kills == 1
        assert res.entry.entry_deaths == 1


class TestTrade:
    def test_trade_within_5s_counts(self, basic_events):
        """场景4：MATE 2000 tick 死于 EN2，我 2300（3s≈300tick@100tick/s）内复仇 → 补枪成功。"""
        res = analyze_perfect(basic_events, MY, side="ALL")
        assert res.trade.trade_kills == 1
        # R2：我死于 EN3，MATE 600 tick 后复仇 → 为我创造机会
        assert res.trade.created_opportunities == 1


class TestClutch:
    def test_clutch_detection(self):
        """场景5：1v2 残局。R1 我方 MATE 先死，剩我 1v2，我连杀两人且回合赢 → 残局胜利。"""
        rounds = [_round(1, 1000, 5000, "T", "T")]
        kills = [
            _kill(1200, EN1, MATE),   # 队友先死 → 我 1v2
            _kill(2000, MY, EN1),
            _kill(3000, MY, EN2),     # 团灭对面
        ]
        ev = {"rounds": rounds, "kills": kills, "hurts": [], "flashes": []}
        res = analyze_perfect(ev, MY, side="ALL")
        assert len(res.clutch.attempts) == 1
        c = res.clutch.attempts[0]
        assert c.vs_count == 2 and c.outcome == "win"

    def test_clutch_saved_when_survive_lost_round(self):
        """场景5b：1v1 回合输了但我存活 → 保枪。"""
        rounds = [_round(1, 1000, 5000, "T", "CT")]
        kills = [_kill(1200, EN1, MATE)]
        ev = {"rounds": rounds, "kills": kills, "hurts": [], "flashes": []}
        res = analyze_perfect(ev, MY, side="ALL")
        assert res.clutch.attempts[0].outcome == "saved"


class TestUtility:
    def test_flash_blinds_enemy_and_teammate(self, basic_events):
        """场景6：我扔闪致盲 2 敌 1 友 → flash_enemies=2, flash_teammates=1。"""
        res = analyze_perfect(basic_events, MY, side="ALL")
        assert res.utility.flash_enemies == 2
        assert res.utility.flash_teammates == 1
        assert res.utility.util_damage == 0  # 没有燃烧/HE 伤害事件


class TestMatchup:
    def test_matchup_rows(self, basic_events):
        """场景7：对位矩阵——EN1 我 1 杀 0 死；EN3 我 0 杀 1 死。"""
        res = analyze_perfect(basic_events, MY, side="ALL")
        rows = {r.opponent_id: r for r in res.matchup.rows}
        assert rows[str(EN1)].my_kills == 1 and rows[str(EN1)].my_deaths == 0
        assert rows[str(EN3)].my_kills == 0 and rows[str(EN3)].my_deaths == 1
        assert rows[str(EN3)].my_damage == 0


class TestEmpty:
    def test_no_events_returns_empty_structure(self):
        """场景8：无事件不崩溃。"""
        ev = {"rounds": [], "kills": [], "hurts": [], "flashes": []}
        res = analyze_perfect(ev, MY, side="ALL")
        assert res.summary.rounds == 0 and res.summary.kills == 0
        assert res.matchup.rows == []


class TestAim:
    def test_hit_rate_and_distance(self):
        """场景9（瞄准分析）：weapon_fires 命中 1/4 = 25%；平均击杀距离 = (20+12)/2 = 16。"""
        rounds = [_round(1, 1000, 5000, "T", "T")]
        kills = [
            _kill(1200, MY, EN1, headshot=True, distance=20.0),
            _kill(2000, MY, EN2, distance=12.0),
        ]
        ev = {
            "rounds": rounds, "kills": kills, "hurts": [], "flashes": [],
            "weapon_fires": [
                {"tick": 1100, "shooter_steamid": MY}, {"tick": 1150, "shooter_steamid": MY},
                {"tick": 1190, "shooter_steamid": MY}, {"tick": 1990, "shooter_steamid": MY},
                {"tick": 1300, "shooter_steamid": EN1},  # 对面开枪不计我的命中率
            ],
        }
        res = analyze_perfect(ev, MY, side="ALL")
        assert res.aim.shots == 4
        assert res.aim.hits == 2  # 两次击杀=两次命中
        assert res.aim.hit_rate == pytest.approx(0.5)
        assert res.aim.avg_kill_distance == pytest.approx(16.0)


class TestTradeNearDistanceFilter:
    """补枪机会距离过滤：只有队友死时我在 ≤20m 内才算「我的补枪机会」。

    场景：
    - 队友死时我在附近（≤20m）→ 记 1 次机会；5s 内我击杀凶手 → 补枪成功。
    - 队友死时我在远处（>20m）→ 不计入我的机会。
    - events 无 positions（旧数据/旧测试）→ 回退为全队口径，行为不变。
    """

    def _pos(self, tick, sid, x, y):
        return {"tick": tick, "steamid": str(sid), "x": x, "y": y}

    def test_near_death_counts_far_death_excluded(self, basic_events):
        events = dict(basic_events)
        events["positions"] = [
            # R1 t=2000 MATE 死于 (100,100)：我在 (105,102) 附近 → 机会；EN2 凶手在 (98,99)
            self._pos(1968, MATE, 100.0, 100.0),
            self._pos(1968, MY, 105.0, 102.0),
            # 远处场景：R1 t=3500 MATE 再死一次 (0,0)，我在 (500,500) → 不算
            self._pos(3488, MATE, 0.0, 0.0),
            self._pos(3488, MY, 500.0, 500.0),
        ]
        # R1 后半段我附近（支持 t=2300 补枪位置无关）
        events["kills"] = [
            _kill(2000, EN2, MATE, distance=10.0),   # 队友死（近）
            _kill(2300, MY, EN2, distance=12.0),     # 我补枪成功
            _kill(3500, EN3, MATE, distance=10.0),   # 队友死（远）
        ]
        res = analyze_perfect(events, MY, side="ALL")
        assert res.trade.trade_opportunities == 1  # 只有近的那次
        assert res.trade.trade_kills == 1

    def test_positions_absent_falls_back_to_team_wide(self, basic_events):
        # basic_events 无 positions 字段 → 维持全队口径（MATE 死 1 次 = 1 机会）
        res = analyze_perfect(basic_events, MY, side="ALL")
        assert res.trade.trade_opportunities == 1
        assert res.trade.trade_kills == 1
