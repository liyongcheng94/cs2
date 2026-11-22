# demo 解析库 spike 结论（2026-11-22，真 demo 实测）

样本：`data/demos/9215177922805569036_0.dem`（58MB，荒漠迷城/de_mirage，17 回合，21 分钟，完美平台天梯）。

## 基准

| 库 | 版本 | 首次解析耗时 | 峰值内存 | 四维素材完整性 |
|---|---|---|---|---|
| demoparser2 | 0.42.2 | 5.0s | 50MB | 事件帧（player_death 含 distance/dmg、player_blind 含 blind_duration）；grenade_throw 事件名需另行发现；经济需手工组装 |
| **awpy（选用）** | 3.3.0 | **2.4s / 18MB**（二次解析 0s，内部缓存） | **18MB** | kills（双方 steamid+xyz 坐标+weapon+headshot+is_trade/victim_traded+thrusmoke+assist_flash）、round_economy（equipment_value/buy_type）、grenades（thrower/tick/type/xyz）、damages、shots、smokes、rounds、header（map 英文 ID） |

## 决定

**选用 awpy**：
1. 更快更省内存（polars 惰性 + 内部缓存）；
2. 高层帧直接覆盖四维：对枪矩阵（damages/kills+坐标）、死亡还原（kills 帧逐事件）、经济（round_economy）、道具（grenades + events.player_blind）；
3. polars group_by/join 适合十万级事件聚合（评审指定选型基准）；
4. demoparser2 作为其底层引擎兜底（awpy 内部即 demoparser2），不单独引入。

## 口径约定（写入引擎 docstring）

- 距离：kills/damages 帧的 xyz 欧氏距离 × 0.01905（CS2 1 unit ≈ 1.905cm）→ 米。
- 对枪对：damages 帧中 user 与同一名敌人在 5s 窗口内互有伤害，以任一方死亡结算；先手=窗口内首个伤害由谁发起；胜=user 未死。
- 劣势枪位（近似口径）：死亡时无队友支援（无同队 assister 且回合内无队友随后补枪）且被 thrusmoke/attackerblind 或距离 >15m 的 AWP 击杀。真实"掩体/交叉火力"判定需要视线检测（VisibilityChecker，二期）。
- 道具浪费率：首版仅统计闪光弹（有 player_blind 事件可判定致盲数=0 的投掷）；其余类型置 null。
- 致盲时长中位数：user 造成敌方致盲的 blind_duration 中位数（抗离群）。

## 基准数据

`docs/spike-results.json`（自动生成）。
