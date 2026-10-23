# -*- coding: utf-8 -*-
"""
绿色工厂研判引擎（GB/T 36132—2025 + 工信部年度《绿色工厂评价要求》14项指标）

用法：
  python gf_engine.py input.json --out result.json --md result.md
  python gf_engine.py --write-demo demo.json        # 生成演示输入
  python gf_engine.py input.json --today 2026-10-22 # 指定“今天”（用于时间倒排）

只用 Python 标准库，兼容 3.8 及以上。所有中文文件按 UTF-8 读写。
本引擎给出的是“按规则推算的结果”，不是官方评审结论；以平台和主管部门为准。
"""
from __future__ import print_function

import argparse
import datetime as _dt
import io
import json
import os
import sys

VERSION = "1.0.0"
POLICY_CHECKED = "2026-10-23"

# ---------------------------------------------------------------------------
# 一、指标模型：GB/T 36132—2025 附录C示例 = 工信部2025年度《绿色工厂评价要求》（非重点行业按此）
# kind: rev=逆向定量（越低越好） pos=正向定量（越高越好） qual=定性（按三档估计）
# ---------------------------------------------------------------------------
MODEL = [
    {"id": "1", "cat": "能源低碳化", "name": "能源消耗强度", "kind": "rev", "weight": 8,
     "lead_rule": "行业先进水平或能耗限额1级", "base_rule": "行业平均水平或能耗限额2级"},
    {"id": "2", "cat": "能源低碳化", "name": "碳排放强度", "kind": "rev", "weight": 8,
     "lead_rule": "行业先进水平", "base_rule": "行业平均水平"},
    {"id": "3", "cat": "能源低碳化", "name": "可再生能源利用率", "kind": "pos", "weight": 8,
     "lead_rule": "行业先进水平", "base_rule": "行业平均水平", "unit": "%"},
    {"id": "4", "cat": "能源低碳化", "name": "能碳管理系统平台功能符合数量", "kind": "pos", "weight": 6,
     "lead_rule": "8项", "base_rule": "0项", "unit": "项", "fixed": [8.0, 0.0]},
    {"id": "5", "cat": "资源高效化", "name": "原材料消耗强度", "kind": "rev", "weight": 8,
     "lead_rule": "行业先进水平", "base_rule": "行业平均水平"},
    {"id": "6", "cat": "资源高效化", "name": "取水强度", "kind": "rev", "weight": 8,
     "lead_rule": "行业先进水平或用水定额先进值", "base_rule": "行业平均水平或用水定额通用值"},
    {"id": "7", "cat": "资源高效化", "name": "工业用水重复利用率", "kind": "pos", "weight": 8,
     "lead_rule": "行业先进水平", "base_rule": "行业平均水平", "unit": "%"},
    {"id": "8", "cat": "资源高效化", "name": "一般工业固体废物综合利用率", "kind": "pos", "weight": 6,
     "lead_rule": "行业先进水平", "base_rule": "行业平均水平", "unit": "%"},
    {"id": "9", "cat": "生产洁净化", "name": "生产工艺和设备先进性", "kind": "qual", "weight": 6},
    {"id": "10", "cat": "生产洁净化", "name": "绿色低碳改造升级项目投资额占比", "kind": "pos", "weight": 4,
     "lead_rule": "行业先进水平", "base_rule": "行业平均水平", "unit": "%"},
    {"id": "11", "cat": "生产洁净化", "name": "主要污染物产生或排放强度", "kind": "rev", "weight": 6,
     "lead_rule": "行业先进水平", "base_rule": "行业平均水平"},
    {"id": "12", "cat": "产品绿色化", "name": "绿色设计", "kind": "qual", "weight": 8},
    {"id": "13", "cat": "产品绿色化", "name": "产品碳足迹", "kind": "qual", "weight": 8},
    {"id": "14", "cat": "用地集约化", "name": "土地产出率", "kind": "pos", "weight": 8,
     "lead_rule": "行业或地方先进水平", "base_rule": "行业平均水平"},
]
CATS = ["能源低碳化", "资源高效化", "生产洁净化", "产品绿色化", "用地集约化"]

QUAL_LEVELS = {"A": 1.0, "B": 0.5, "C": 0.0}
QUAL_TEXT = {
    "9": {"A": "主要工序的工艺设备能逐项对上国家推荐目录或行业规范条件，有合同/铭牌/验收证明，且无淘汰类设备",
          "B": "部分能对上，或证明材料不全",
          "C": "拿不出对应证明（若还有淘汰类设备，先解决合规问题）"},
    "12": {"A": "已按 GB/T 24256 形成产品绿色设计及验证报告，并有环境绩效改善的证据",
           "B": "有设计改进记录，但没有成体系的报告或验证",
           "C": "未开展"},
    "13": {"A": "主要产品已按 GB/T 24067 等完成碳足迹量化并出具报告",
           "B": "只做了部分主要产品，或方法不符合 GB/T 24067",
           "C": "未开展"},
}

ECMS_FUNCS = ["能耗查询", "能源消费量和强度计算", "能源消费分析与用能策略推荐", "能效对标",
              "能流分析", "能效平衡与优化", "用能与碳排放预算管理", "碳排放",
              "碳足迹核算", "供应链碳管理", "碳核查支撑", "碳资产管理"]

# ---------------------------------------------------------------------------
# 二、折标与排放参数
# ---------------------------------------------------------------------------
KGCE = {  # 折标准煤参考系数（GB/T 2589—2020 附录A；电力按当量值，国家统计局口径）
    "elec_kwh": 0.1229, "ng_m3": 1.2143, "diesel_kg": 1.4571, "gasoline_kg": 1.4714,
    "lpg_kg": 1.7143, "fuel_oil_kg": 1.4286, "coal_kg": 0.7143, "coke_kg": 0.9714,
    "heat_gj": 34.12,
}
# 燃料排放参数：低位热值(GJ/t 或 GJ/万m3)、单位热值含碳量(tC/TJ)、碳氧化率（GB/T 32150 常用缺省值）
FUEL_EF = {
    "ng_m3": (389.31, 15.32, 0.99, 1e4),
    "diesel_t": (42.652, 20.20, 0.98, 1.0),
    "gasoline_t": (43.070, 18.90, 0.98, 1.0),
    "lpg_t": (50.179, 17.20, 0.98, 1.0),
    "fuel_oil_t": (41.816, 21.10, 0.98, 1.0),
    "coal_t": (20.908, 26.37, 0.94, 1.0),
    "coke_t": (28.435, 29.50, 0.93, 1.0),
}
HEAT_EF_T_PER_GJ = 0.11
# 2023年电力二氧化碳排放因子（生态环境部 国家统计局 公告2025年第47号），kgCO2/kWh
GRID_2023 = {
    "全国": 0.5306, "华北": 0.6361, "东北": 0.5122, "华东": 0.5500, "华中": 0.5271,
    "西北": 0.5543, "南方": 0.4042, "西南": 0.2472,
    "北京": 0.5554, "天津": 0.6796, "河北": 0.6516, "山西": 0.6634, "内蒙古": 0.6479,
    "辽宁": 0.4878, "吉林": 0.4671, "黑龙江": 0.5229, "上海": 0.5737, "江苏": 0.5827,
    "浙江": 0.4974, "安徽": 0.6553, "福建": 0.4211, "江西": 0.5836, "山东": 0.6191,
    "河南": 0.5897, "湖北": 0.4044, "湖南": 0.4976, "广东": 0.4419, "广西": 0.4476,
    "海南": 0.3648, "重庆": 0.5581, "四川": 0.1564, "贵州": 0.5683, "云南": 0.1333,
    "陕西": 0.6335, "甘肃": 0.4471, "青海": 0.1796, "宁夏": 0.6187, "新疆": 0.6021,
}
GRID_RESIDUAL_2023 = 0.6096  # 全国电力平均因子（不包括市场化交易的非化石能源电量），市场法用

# ---------------------------------------------------------------------------
# 三、门槛：否决项、基本要求、分数线
# ---------------------------------------------------------------------------
GATES = [
    ("g1", "近三年未正常经营生产（注销、连续停产12个月以上、列入经营异常名录未移出等）", "veto"),
    ("g2", "近三年发生较大及以上安全（含网络、数据、生产安全）、质量、环境污染事故", "veto"),
    ("g3", "近三年被动态调整出绿色制造名单", "veto"),
    ("g4", "近三年从事《反垄断法》规定的垄断行为", "veto"),
    ("g5", "近三年在国务院及有关部门督查中被发现存在严重问题", "veto"),
    ("g6", "被列入工业节能监察整改名单且未按要求完成整改", "veto"),
    ("g7", "近三年受到有关行政主管部门比较重大以上行政处罚", "veto"),
    ("g8", "被列为失信被执行人", "veto"),
    ("g9", "近三年有其他安全、质量、环保违法违规记录（含一般行政处罚；部分地市还看偷漏税）", "review"),
]
BASIC = [
    ("b1", "明确绿色制造管理层职责，有绿色低碳中长期规划和年度量化目标"),
    ("b2", "质量管理体系（GB/T 19001）"),
    ("b3", "环境管理体系（GB/T 24001）"),
    ("b4", "能源管理体系（GB/T 23331）"),
    ("b5", "职业健康安全管理体系（GB/T 45001）"),
]
DEFAULT_THRESHOLDS = {
    "市级": {"key": 60.0, "nonkey": 75.0,
             "src": "缺省值，参照安徽2026年省级口径和部分地市市级通知（重点行业≥60、非重点≥75），以当地通知为准"},
    "省级": {"key": 60.0, "nonkey": 75.0,
             "src": "安徽省工信厅2026年度省级绿色工厂推荐通知：原则上重点行业≥60、非重点≥75；其他省份以当地通知为准"},
}
PRIORITY_HONORS = ["能效领跑者", "水效领跑者", "节水标杆", "环保绩效A级", "专精特新", "小巨人", "单项冠军"]

# 提分措施的时效属性：year=只改变评价年当年数据；status=申报前完成即可
GAP_PLAYBOOK = {
    "1": ("year", "中–慢", "节能改造（空压、电机变频、余热回收、照明、工艺优化），并核对能耗限额标准分级"),
    "2": ("year", "中", "节能降碳；如当地/平台认可市场法，可用绿电交易或绿证降低外购电排放"),
    "3": ("year", "快–中", "单独购买绿证（快）、参与绿电交易（中）、新建或扩建屋顶光伏（中–慢）"),
    "4": ("status", "快–中", "补齐能碳管理系统业务功能并保证建成运行，留存运行截图和数据导出"),
    "5": ("year", "慢", "工艺优化、提高材料利用率、边角料回用"),
    "6": ("year", "中", "节水改造、分质供水、对照用水定额排查高耗水环节"),
    "7": ("year", "中", "循环冷却水、中水回用、工艺水梯级利用"),
    "8": ("year", "快–中", "签订一般固废综合利用协议、分类收集提高可利用比例"),
    "9": ("status", "快（整理）/慢（更新设备）", "对照国家推荐目录和行业规范条件逐项整理证明；仍有淘汰类设备的先更新"),
    "10": ("year", "跨年", "只能计入近三年真实实施的绿色低碳改造项目；新项目会计入下一轮"),
    "11": ("year", "中–慢", "治理设施提标、源头替代低毒低挥发原辅料"),
    "12": ("status", "中（2–4个月）", "按 GB/T 24256 开展主要产品绿色设计并形成设计及验证报告"),
    "13": ("status", "快–中（1–3个月）", "按 GB/T 24067 完成主要产品碳足迹量化并出具报告"),
    "14": ("year", "慢", "提高单位用地产值或产能；用地面积以不动产权证为准，不能随意调整"),
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _utf8_stdout():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            try:
                setattr(sys, stream_name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"))
            except Exception:
                pass


def num(v):
    """把各种写法转成 float；空、None、无法识别 -> None。支持 '1,234'、'12%'、全角数字。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "" or s in ("-", "—", "无", "未知", "不清楚", "N/A", "n/a"):
        return None
    table = {ord(c): ord(c) - 0xFEE0 for c in "０１２３４５６７８９．－＋"}
    s = s.translate(table).replace(",", "").replace("，", "").replace(" ", "")
    if s.endswith("%"):
        s = s[:-1]
    try:
        return float(s)
    except ValueError:
        return None


def r(v, nd=2):
    return None if v is None else round(v, nd)


def fmt(v, nd=2):
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return "{:,.{}f}".format(v, nd if abs(v) < 1e6 else 0)
    return "{:.{}f}".format(v, nd)


def fmt_auto(v):
    """按数量级自动保留位数，避免 0.0001 这类失真显示。"""
    if v is None:
        return "—"
    a = abs(v)
    if a == 0:
        return "0"
    if a >= 1000:
        return "{:,.0f}".format(v)
    if a >= 100:
        return "{:.1f}".format(v)
    if a >= 1:
        return "{:.2f}".format(v)
    if a >= 0.01:
        return "{:.4f}".format(v)
    import math
    nd = int(-math.floor(math.log10(a))) + 2
    return "{:.{}f}".format(v, nd)


def rsig(v, sig=6):
    """按有效数字保留，避免小数量级指标（如污染物排放强度 0.0000474）被固定小数位截断。"""
    if v is None or v == 0:
        return v
    import math
    nd = sig - int(math.floor(math.log10(abs(v)))) - 1
    return round(v, max(nd, 0))


def g(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


# ---------------------------------------------------------------------------
# 计算：能源、碳、可再生能源
# ---------------------------------------------------------------------------
def compute_energy(data, warnings):
    e = data.get("energy") or {}
    meta = data.get("meta") or {}
    grid = num(e.get("grid_kwh")) or 0.0
    pv = num(e.get("pv_self_kwh")) or 0.0
    direct = num(e.get("direct_green_kwh")) or 0.0
    trade = num(e.get("green_trade_kwh")) or 0.0
    gec_kwh = (num(e.get("gec_mwh")) or 0.0) * 1000.0
    ng_coef = num(e.get("ng_coef"))
    if ng_coef is None:
        ng_coef = KGCE["ng_m3"]
        if num(e.get("natural_gas_m3")):
            warnings.append("天然气按 1.2143 kgce/m³ 折标（GB/T 2589—2020 参考范围 1.1000～1.3300）；有燃气公司热值或当地统计口径时以其为准。")

    tce = {}
    tce["电力"] = (grid + pv + direct) * KGCE["elec_kwh"] / 1000.0
    tce["天然气"] = (num(e.get("natural_gas_m3")) or 0.0) * ng_coef / 1000.0
    tce["柴油"] = (num(e.get("diesel_t")) or 0.0) * KGCE["diesel_kg"]
    tce["汽油"] = (num(e.get("gasoline_t")) or 0.0) * KGCE["gasoline_kg"]
    tce["液化石油气"] = (num(e.get("lpg_t")) or 0.0) * KGCE["lpg_kg"]
    tce["燃料油"] = (num(e.get("fuel_oil_t")) or 0.0) * KGCE["fuel_oil_kg"]
    tce["原煤"] = (num(e.get("coal_t")) or 0.0) * KGCE["coal_kg"]
    tce["焦炭"] = (num(e.get("coke_t")) or 0.0) * KGCE["coke_kg"]
    tce["外购热力"] = (num(e.get("heat_gj")) or 0.0) * KGCE["heat_gj"] / 1000.0
    tce["其他能源"] = num(e.get("other_tce")) or 0.0
    tce["其他可再生能源"] = num(e.get("other_renewable_tce")) or 0.0
    gross = sum(tce.values())
    feed = num(e.get("feedstock_tce")) or 0.0
    exported = num(e.get("exported_tce")) or 0.0
    total = gross - feed - exported
    has_energy = gross > 0

    # 可再生能源电力：自发自用 + 专线直供 + 市场化交易绿电 + 单独购买绿证（不重复计算）
    claim_grid_green = trade + gec_kwh
    if trade and gec_kwh:
        warnings.append("同时填了市场化交易绿电（{:,.0f} kWh）和单独购买的绿证（{:,.0f} kWh）：绿电交易合同若已附带绿证，两者对应的是同一批电量，只能算一次，请核对凭证后只填一种；确属两批不同电量时，须分别有结算凭证和绿证划转记录。".format(trade, gec_kwh))
    if claim_grid_green > grid and grid > 0:
        warnings.append("绿电交易电量与绿证合计（{:,.0f} kWh）超过外购电量（{:,.0f} kWh），超出部分不计入；同一电量不能既算绿电交易又算绿证。".format(claim_grid_green, grid))
        claim_grid_green = grid
    re_kwh = pv + direct + claim_grid_green
    re_tce = re_kwh * KGCE["elec_kwh"] / 1000.0 + tce["其他可再生能源"]

    # 碳排放
    method = (e.get("carbon_method") or "location").lower()
    prov = (meta.get("province") or "").replace("省", "").replace("市", "").replace("自治区", "").replace("壮族", "").replace("回族", "").replace("维吾尔", "")
    override = num(e.get("grid_factor"))
    if override is not None:
        factor, factor_src = override, "用户指定"
    elif method == "market":
        factor, factor_src = GRID_RESIDUAL_2023, "市场法：全国电力平均因子（不含市场化交易非化石电量）0.6096，2023年"
    elif prov in GRID_2023:
        factor, factor_src = GRID_2023[prov], "{}省级电力平均因子，2023年（公告2025年第47号）".format(prov)
    else:
        factor, factor_src = GRID_2023["全国"], "全国电力平均因子 0.5306，2023年（公告2025年第47号）"
    if method == "market":
        grid_emitting_kwh = max(grid - claim_grid_green, 0.0)
    else:
        grid_emitting_kwh = grid
    co2 = {"外购电力": grid_emitting_kwh * factor / 1000.0}
    fuel_map = [("ng_m3", "natural_gas_m3", "天然气"), ("diesel_t", "diesel_t", "柴油"),
                ("gasoline_t", "gasoline_t", "汽油"), ("lpg_t", "lpg_t", "液化石油气"),
                ("fuel_oil_t", "fuel_oil_t", "燃料油"), ("coal_t", "coal_t", "原煤"),
                ("coke_t", "coke_t", "焦炭")]
    for k, field, label in fuel_map:
        q = num(e.get(field)) or 0.0
        ncv, cc, of, per = FUEL_EF[k]
        co2[label] = q / per * ncv / 1000.0 * cc * of * 44.0 / 12.0
    co2["外购热力"] = (num(e.get("heat_gj")) or 0.0) * HEAT_EF_T_PER_GJ
    co2["过程及其他"] = num(e.get("other_co2_t")) or 0.0
    co2_total = sum(co2.values())
    if (num(e.get("other_tce")) or 0) > 0 and not num(e.get("other_co2_t")):
        warnings.append("“其他能源”只计入了折标量，没有对应排放；如是化石能源，请在 other_co2_t 补上排放量。")
    if method == "market":
        warnings.append("碳排放按市场法计算（绿电、绿证对应电量按零排放，其余外购电按 0.6096）。平台或当地若要求按地区平均因子，请改用 location，两种口径不要混用。")

    return {
        "has_energy": has_energy, "tce_by_type": {k: r(v, 2) for k, v in tce.items() if v},
        "gross_tce": r(gross, 2), "feedstock_tce": r(feed, 2), "exported_tce": r(exported, 2),
        "total_tce": total if has_energy else None, "elec_total_kwh": grid + pv + direct,
        "re_kwh": re_kwh, "re_tce": re_tce, "grid_kwh": grid, "claim_grid_green_kwh": claim_grid_green,
        "co2_by_source": {k: r(v, 2) for k, v in co2.items() if v}, "co2_total": co2_total if has_energy else None,
        "grid_factor": factor, "grid_factor_src": factor_src, "carbon_method": method,
    }


def basis_value(data, ind_id):
    """返回 (分母数值, 分母说明, 单位后缀)。默认按全局 basis；可在 meta.basis_by 里逐项覆盖。"""
    meta = data.get("meta") or {}
    out = data.get("output") or {}
    b = (g(meta, "basis_by", ind_id) or meta.get("basis") or "产值")
    if b == "产量":
        unit = meta.get("product_unit") or "产品单位"
        return num(out.get("qty")), "合格产品产量", unit
    return num(out.get("value_wan")), "工业总产值", "万元"


def compute_actuals(data, en, warnings):
    res = data.get("resources") or {}
    pol = data.get("pollution") or {}
    land = data.get("land") or {}
    up = data.get("upgrade") or {}
    out = data.get("output") or {}
    ecms = data.get("ecms") or {}
    direct = data.get("direct") or {}
    acts = {}

    def per_basis(numerator, ind_id, num_unit):
        d, dname, dunit = basis_value(data, ind_id)
        if numerator is None or not d:
            return None, "{}/{}".format(num_unit, dunit), dname
        return numerator / d, "{}/{}".format(num_unit, dunit), dname

    v, u, dn = per_basis(en["total_tce"], "1", "tce")
    acts["1"] = (v, u, "综合能耗{} tce ÷ {}".format(fmt(en["total_tce"]), dn))
    v, u, dn = per_basis(en["co2_total"], "2", "tCO2")
    acts["2"] = (v, u, "二氧化碳排放{} t ÷ {}".format(fmt(en["co2_total"]), dn))
    if en["total_tce"]:
        acts["3"] = (en["re_tce"] / en["total_tce"] * 100.0, "%",
                     "可再生能源{} tce ÷ 综合能耗{} tce".format(fmt(en["re_tce"]), fmt(en["total_tce"])))
    else:
        acts["3"] = (None, "%", "缺能源数据")
    funcs = [f for f in (ecms.get("functions") or []) if f]
    n_funcs = len(set(funcs))
    if not funcs and num(ecms.get("count")) is not None:
        n_funcs = int(num(ecms.get("count")))
        funcs = ["(数量)"]
    running = ecms.get("running")
    if running is True or str(running) in ("是", "true", "True", "1"):
        acts["4"] = (float(min(n_funcs, 12)), "项", "已建成运行，具备{}项业务功能".format(n_funcs))
    elif running is None and not funcs:
        acts["4"] = (None, "项", "未说明是否建成能碳管理系统")
    else:
        acts["4"] = (0.0, "项", "系统未建成运行，按0项计（功能再多也不计分）")
    mat = num(res.get("material_qty"))
    v, u, dn = per_basis(mat, "5", res.get("material_unit") or "原材料单位")
    acts["5"] = (v, u, "主要原材料{} ÷ {}".format(fmt(mat), dn))
    wv = num(res.get("water_withdrawal_m3"))
    v, u, dn = per_basis(wv, "6", "m³")
    acts["6"] = (v, u, "取水量{} m³ ÷ {}".format(fmt(wv), dn))
    vr = num(res.get("water_reuse_m3"))
    if wv is not None and vr is not None and (wv + vr) > 0:
        acts["7"] = (vr / (wv + vr) * 100.0, "%", "重复利用水量{} ÷（取水量{} + 重复利用水量）".format(fmt(vr), fmt(wv)))
    else:
        acts["7"] = (None, "%", "缺取水量或重复利用水量")
    z = num(res.get("sw_generated_t"))
    zr = num(res.get("sw_utilized_t"))
    zw = num(res.get("sw_stock_utilized_t")) or 0.0
    if z is not None and zr is not None and (z + zw) > 0:
        k = zr / (z + zw) * 100.0
        acts["8"] = (k, "%", "综合利用量{} ÷（产生量{} + 利用往年贮存量{}）".format(fmt(zr), fmt(z), fmt(zw)))
        if k > 100.0001:
            warnings.append("一般工业固废综合利用率超过100%，请核对：利用量不应含外购固废，往年贮存利用量应计入分母。")
    else:
        acts["8"] = (None, "%", "缺一般工业固废产生量或利用量")
    acts["9"] = (None, "", "定性项")
    inv = num(up.get("invest_3y_wan"))
    o3 = num(out.get("value_3y_wan"))
    if inv is not None and o3:
        acts["10"] = (inv / o3 * 100.0, "%", "近三年改造投资{}万元 ÷ 三年总产值{}万元".format(fmt(inv), fmt(o3)))
    else:
        acts["10"] = (None, "%", "缺近三年改造投资额或三年总产值")
    pq = num(pol.get("qty"))
    v, u, dn = per_basis(pq, "11", pol.get("unit") or "污染物单位")
    acts["11"] = (v, u, "{}{} ÷ {}".format(pol.get("name") or "主要污染物", fmt(pq), dn))
    acts["12"] = (None, "", "定性项")
    acts["13"] = (None, "", "定性项")
    area = num(land.get("area_m2"))
    if (g(data, "meta", "basis_by", "14") or "") == "产量":
        cap = num(land.get("capacity"))
        if cap is not None and area:
            acts["14"] = (cap / area, "{}/m²".format(g(data, "meta", "product_unit") or "产品单位"), "总产能 ÷ 用地面积{} m²".format(fmt(area, 0)))
        else:
            acts["14"] = (None, "产品单位/m²", "缺产能或用地面积")
    else:
        val = num(out.get("value_wan"))
        if val is not None and area:
            acts["14"] = (val / area, "万元/m²", "工业总产值{}万元 ÷ 用地面积{} m²（约{}亩）".format(fmt(val), fmt(area, 0), fmt(area / 666.67, 1)))
        else:
            acts["14"] = (None, "万元/m²", "缺工业总产值或用地面积")
    # 直接给定的实际值优先（例如企业已按行业标准算好的单位产品能耗）
    for k, dv in direct.items():
        dvn = num(dv)
        if dvn is not None and k in acts:
            acts[k] = (dvn, acts[k][1], "直接填报值")
    return acts


# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------
def frac(actual, lead, base, kind):
    if kind == "rev":
        if lead > base:
            lead, base = base, lead
        if actual <= lead:
            return 1.0
        if actual >= base:
            return 0.0
        return (base - actual) / (base - lead)
    if lead < base:
        lead, base = base, lead
    if actual >= lead:
        return 1.0
    if actual <= base:
        return 0.0
    return (actual - base) / (lead - base)


def score_custom(cm, warnings):
    """重点行业：按平台“行业评价要求”逐项给出的指标表打分。"""
    alias = {"逆向": "rev", "reverse": "rev", "正向": "pos", "positive": "pos", "定性": "qual", "qualitative": "qual"}
    rows = []
    for k, it in enumerate(cm):
        i = str(it.get("id") or (k + 1))
        kind = alias.get(str(it.get("kind") or "rev").strip(), str(it.get("kind") or "rev").strip().lower())
        w = num(it.get("weight")) or 0.0
        row = {"id": i, "cat": it.get("cat") or "其他", "name": it.get("name") or "指标" + i, "kind": kind, "weight": w,
               "actual": None, "unit": it.get("unit") or "", "calc": "行业评价要求（自定义）", "lead": None, "base": None,
               "src": it.get("src") or "", "score": None, "status": "", "note": "", "custom": True}
        if kind == "qual":
            lv = str(it.get("level") or "").strip().upper()[:1]
            row["level"] = lv or None
            if lv in QUAL_LEVELS:
                row["score"] = w * QUAL_LEVELS[lv]
                row["status"] = {"A": "full", "B": "partial", "C": "zero"}[lv]
            else:
                row["status"] = "unknown"
            rows.append(row)
            continue
        a, lead, base = num(it.get("actual")), num(it.get("lead")), num(it.get("base"))
        row.update({"actual": a, "lead": lead, "base": base})
        if a is None:
            row["status"], row["note"] = "no_data", "缺数据：实际值"
        elif lead is None or base is None:
            row["status"] = "no_benchmark"
        else:
            if lead == base:
                f = 1.0 if ((kind == "rev" and a <= lead) or (kind == "pos" and a >= lead)) else 0.0
            else:
                f = frac(a, lead, base, kind)
            row["score"] = w * f
            row["status"] = "full" if f >= 0.9999 else ("zero" if f <= 0.0001 else "partial")
        rows.append(row)
    tw = sum(x["weight"] for x in rows)
    if abs(tw - 100) > 0.01:
        warnings.append("自定义指标表权重合计为{}，不是100分，请核对是否抄全。".format(fmt(tw, 1)))
    return rows


def score_all(data, acts, warnings):
    if data.get("custom_model"):
        return score_custom(data.get("custom_model"), warnings)
    bm = data.get("benchmarks") or {}
    qual = data.get("qualitative") or {}
    model = list(MODEL)
    rows = []
    for m in model:
        i = m["id"]
        w = float(m["weight"])
        row = {"id": i, "cat": m["cat"], "name": m["name"], "kind": m["kind"], "weight": w,
               "actual": None, "unit": "", "calc": "", "lead": None, "base": None, "src": "",
               "score": None, "status": "", "note": ""}
        if m["kind"] == "qual":
            lv = (qual.get(i) or "").strip().upper()[:1]
            row["level"] = lv or None
            if lv in QUAL_LEVELS:
                row["score"] = w * QUAL_LEVELS[lv]
                row["status"] = {"A": "full", "B": "partial", "C": "zero"}[lv]
                row["note"] = "按经验三档估计（满/半/零），平台细则以填报说明为准：" + QUAL_TEXT[i][lv]
            else:
                row["status"] = "unknown"
                row["note"] = "未说明开展情况"
            rows.append(row)
            continue
        actual, unit, calc = acts.get(i, (None, "", ""))
        row["actual"], row["unit"], row["calc"] = actual, unit, calc
        if "fixed" in m:
            lead, base = m["fixed"]
            src = "评价要求固定值"
        else:
            b = bm.get(i) or {}
            lead, base, src = num(b.get("lead")), num(b.get("base")), b.get("src") or ""
            if lead is not None and base is not None:
                bad = (m["kind"] == "rev" and lead > base) or (m["kind"] == "pos" and lead < base)
                if bad:
                    warnings.append("指标{}【{}】的引领值和基准值方向填反了，已按“{}”自动对调，请核对来源。".format(
                        i, m["name"], "越低越好" if m["kind"] == "rev" else "越高越好"))
        row["lead"], row["base"], row["src"] = lead, base, src
        if actual is None:
            row["status"] = "no_data"
            row["note"] = "缺数据：" + calc
        elif lead is None or base is None:
            row["status"] = "no_benchmark"
            row["note"] = "已算出实际值，缺引领值/基准值，暂不能计分"
        else:
            if lead == base:
                f = 1.0 if ((m["kind"] == "rev" and actual <= lead) or (m["kind"] == "pos" and actual >= lead)) else 0.0
            else:
                f = frac(actual, lead, base, m["kind"])
            row["score"] = w * f
            row["status"] = "full" if f >= 0.9999 else ("zero" if f <= 0.0001 else "partial")
        rows.append(row)
    return rows


def summarize(rows):
    certain = sum(x["score"] for x in rows if x["score"] is not None)
    pending = sum(x["weight"] for x in rows if x["score"] is None)
    cats = []
    cat_list = [c for c in CATS if any(x["cat"] == c for x in rows)]
    for x in rows:
        if x["cat"] not in cat_list:
            cat_list.append(x["cat"])
    for c in cat_list:
        rs = [x for x in rows if x["cat"] == c]
        cw = sum(x["weight"] for x in rs)
        cs = sum(x["score"] for x in rs if x["score"] is not None)
        cp = sum(x["weight"] for x in rs if x["score"] is None)
        cats.append({"cat": c, "weight": cw, "score": r(cs, 2), "upper": r(cs + cp, 2)})
    return {"certain": certain, "pending_weight": pending, "upper": certain + pending}, cats


# ---------------------------------------------------------------------------
# 否决项与基本要求
# ---------------------------------------------------------------------------
def check_gates(data):
    gin = data.get("gates") or {}
    items, worst = [], "ok"
    veto_from = None
    order = {"ok": 0, "warn": 1, "veto": 2}
    for key, label, kind in GATES:
        v = (gin.get(key) or "不确定").strip()
        if v in ("否", "无", "没有", "no", "No", "false"):
            lvl = "ok"
        elif v in ("是", "有", "yes", "Yes", "true"):
            lvl = "veto" if kind == "veto" else "warn"
        else:
            lvl = "warn"
            v = "不确定"
        items.append({"key": key, "label": label, "value": v, "level": lvl})
        if lvl == "veto" and veto_from is None:
            veto_from = "gate"
        if order[lvl] > order[worst]:
            worst = lvl
    bin_ = data.get("basic") or {}
    basic_items = []
    for key, label in BASIC:
        v = (bin_.get(key) or "不确定").strip()
        if key == "b1":
            lvl = "ok" if v in ("是", "有") else ("veto" if v in ("否", "无") else "warn")
        else:
            if v in ("认证", "已认证", "获证"):
                lvl = "ok"
            elif v in ("建立", "已建立", "建立运行", "运行未认证"):
                lvl = "ok_weak"
            elif v in ("无", "否", "未建立"):
                lvl = "veto"
            else:
                lvl = "warn"
        basic_items.append({"key": key, "label": label, "value": v, "level": lvl})
        if lvl == "veto" and veto_from is None:
            veto_from = "basic"
        mapped = "ok" if lvl == "ok_weak" else lvl
        if order.get(mapped, 0) > order[worst]:
            worst = mapped
    return {"status": worst, "items": items, "basic": basic_items, "veto_from": veto_from}


# ---------------------------------------------------------------------------
# 层级判定
# ---------------------------------------------------------------------------
def tier_verdicts(data, total, gates):
    meta = data.get("meta") or {}
    key = bool(meta.get("key_industry"))
    th_in = data.get("thresholds") or {}
    out = []
    cur0 = meta.get("current_level") or "无"
    tiers_needed = []
    if cur0 == "无":
        tiers_needed.append("市级")
    if cur0 in ("无", "市级"):
        tiers_needed.append("省级")
    for tier in tiers_needed:
        t = num(th_in.get(tier))
        src = "用户指定（来自当地通知）" if t is not None else DEFAULT_THRESHOLDS[tier]["src"]
        if t is None:
            t = DEFAULT_THRESHOLDS[tier]["key" if key else "nonkey"]
        out.append(_verdict(tier, t, src, total, gates))
    # 国家级：前置条件 + 相对门槛
    cur = meta.get("current_level") or "无"
    pre = []
    if meta.get("is_c_manufacturing") is False:
        pre.append("不属于《国民经济行业分类》C类制造业，不能申报国家绿色工厂")
    if cur not in ("省级", "国家级"):
        pre.append("2026年起国家绿色工厂须先列入省级绿色工厂名单（当前：{}）".format(cur))
    avg = num(th_in.get("national_regional_avg"))
    nat = {"tier": "国家级", "threshold": avg, "prereq": pre,
           "src": "国家级没有固定分数线：要求“行业领先”且优于本地区已有绿色工厂平均水平；平均水平需向当地工信部门了解"}
    if cur == "国家级":
        nat["verdict"] = "已是国家级，看动态管理"
        nat["detail"] = "确定分{}。每年对照新评价要求填报动态管理表，得分连续三年处于后5%会被移出".format(fmt(total["certain"], 1))
    elif gates["status"] == "veto":
        nat["verdict"] = "不具备申报条件"
        nat["detail"] = "存在否决项或基本要求不满足"
    elif pre:
        nat["verdict"] = "当年不能报"
        nat["detail"] = "；".join(pre)
    elif avg is not None:
        v = _verdict("国家级", avg, "本地区已有绿色工厂平均水平（用户提供）", total, gates)
        nat.update({k: v[k] for k in ("verdict", "detail", "gap")})
    else:
        nat["verdict"] = "需对比本地区平均水平"
        nat["detail"] = "确定分{}，上限{}。没有本地区平均分时无法下结论；一般需要明显高于省级线".format(fmt(total["certain"], 1), fmt(total["upper"], 1))
    out.append(nat)
    return out


def _verdict(tier, t, src, total, gates):
    c, u = total["certain"], total["upper"]
    d = {"tier": tier, "threshold": t, "src": src}
    if gates["status"] == "veto":
        d["verdict"] = "不具备申报条件"
        d["detail"] = "存在否决项或基本要求不满足，分数再高也不能报"
        d["gap"] = None
    elif c >= t - 1e-9:
        d["verdict"] = "确定分已过线"
        d["detail"] = "确定分{}，高出分数线{}分".format(fmt(c, 1), fmt(c - t, 1))
        d["gap"] = 0.0
    elif total["pending_weight"] > 30:
        d["verdict"] = "信息不足"
        d["detail"] = "能计分的只有{}分，待定{}分，先补数据和对标值再判断".format(fmt(c, 1), fmt(total["pending_weight"], 0))
        d["gap"] = t - c
    elif u >= t - 1e-9:
        d["verdict"] = "有希望，待补齐"
        d["detail"] = "确定分{}，还差{}分，待定项最多可补{}分".format(fmt(c, 1), fmt(t - c, 1), fmt(total["pending_weight"], 1))
        d["gap"] = t - c
    else:
        d["verdict"] = "目前达不到"
        d["detail"] = "待定项全拿满也只有{}分，比分数线低{}分，需要先做改造提分".format(fmt(u, 1), fmt(t - u, 1))
        d["gap"] = t - c
    if gates["status"] == "warn" and d["verdict"] != "不具备申报条件":
        d["detail"] += "；另有门槛项待核实"
    return d


# ---------------------------------------------------------------------------
# 提分：每项要做到多少
# ---------------------------------------------------------------------------
def gap_actions(data, rows, en):
    acts = []
    out = data.get("output") or {}
    res = data.get("resources") or {}
    for x in rows:
        i, w = x["id"], x["weight"]
        if x.get("custom"):
            timing, speed, how = (("status", "视材料而定", "按行业评价要求准备证明") if x["kind"] == "qual"
                                  else ("year", "视措施而定", "按行业评价要求改善"))
        else:
            timing, speed, how = GAP_PLAYBOOK[i]
        gain = w - (x["score"] or 0.0) if x["score"] is not None else w
        if gain <= 0.0001:
            continue
        item = {"id": i, "name": x["name"], "gain": r(gain, 2), "timing": timing, "speed": speed, "how": how,
                "need": "", "per_point": ""}
        a, lead, base = x["actual"], x["lead"], x["base"]
        if x["status"] == "no_data":
            item["need"] = "先补数据（{}）".format(x["note"].replace("缺数据：", ""))
            item["kind"] = "data"
            item["timing"], item["speed"] = "info", "快（补资料）"
        elif x["status"] == "no_benchmark":
            mrule = {} if x.get("custom") else next((mm for mm in MODEL if mm["id"] == i), {})
            item["need"] = "先找对标值：引领值取{}，基准值取{}；得分在0到{}分之间".format(
                mrule.get("lead_rule", "行业先进水平"), mrule.get("base_rule", "行业平均水平"), fmt(w, 0))
            item["kind"] = "benchmark"
            item["timing"], item["speed"] = "info", "快（补资料）"
        elif x["status"] == "unknown":
            item["need"] = "确认开展情况并准备证明"
            item["kind"] = "qual"
        elif x["kind"] == "qual":
            atext = "按行业评价要求补齐证明材料" if x.get("custom") else QUAL_TEXT[i]["A"]
            item["need"] = "从{}档提到A档：{}".format(x.get("level"), atext)
            item["kind"] = "qual"
        else:
            item["kind"] = "improve"
            d, _, dunit = basis_value(data, i)
            if x.get("custom"):
                item["need"] = "{}从{}{}改善到引领值{}".format(x["name"], fmt_auto(a), x.get("unit") or "", fmt_auto(lead))
            elif i == "3" and en.get("total_tce"):
                need_tce = lead / 100.0 * en["total_tce"] - en["re_tce"]
                mwh = need_tce / (KGCE["elec_kwh"])  # tce -> MWh: 1 MWh = 0.1229 tce
                item["need"] = "可再生能源利用率从{}%提到{}%，需新增约{:,.0f} MWh 可再生电力（约{:,.0f}张绿证，1张=1 MWh）".format(
                    fmt(a, 1), fmt(lead, 1), mwh, mwh)
                if lead != base:
                    pp = (lead - base) / w / 100.0 * en["total_tce"] / KGCE["elec_kwh"]
                    item["per_point"] = "每1分约需{:,.0f} MWh".format(pp)
            elif i == "4":
                n = int(a or 0)
                item["need"] = "再补{}项业务功能（引领值8项，每项0.75分）".format(max(0, 8 - n))
            elif i == "7":
                wv = num(res.get("water_withdrawal_m3"))
                vr = num(res.get("water_reuse_m3"))
                t = lead / 100.0
                if wv is not None and t < 1:
                    need = t / (1 - t) * wv - (vr or 0)
                    item["need"] = "重复利用率到{}%：取水量不变时，重复利用水量需再增加约{:,.0f} m³".format(fmt(lead, 1), need)
            elif i == "8":
                z = num(res.get("sw_generated_t")) or 0
                zw = num(res.get("sw_stock_utilized_t")) or 0
                zr = num(res.get("sw_utilized_t")) or 0
                need = lead / 100.0 * (z + zw) - zr
                item["need"] = "综合利用率到{}%：一般固废综合利用量需再增加约{:,.1f} t".format(fmt(lead, 1), need)
            elif i == "10":
                o3 = num(out.get("value_3y_wan"))
                inv = num((data.get("upgrade") or {}).get("invest_3y_wan")) or 0
                if o3:
                    need = lead / 100.0 * o3 - inv
                    item["need"] = "投资占比到{}%：近三年真实实施的改造投资需达到约{:,.0f}万元（现{:,.0f}万元）".format(fmt(lead, 2), lead / 100.0 * o3, inv)
            elif i == "14":
                area = num((data.get("land") or {}).get("area_m2"))
                if area and a is not None:
                    item["need"] = "土地产出率到{}：用地不变时，需新增产值约{:,.0f}万元".format(fmt_auto(lead), (lead - a) * area)
            elif x["kind"] == "rev" and a is not None and d:
                delta = (a - lead) * d
                label = {"1": "综合能耗", "2": "二氧化碳排放", "5": "主要原材料消耗", "6": "取水量", "11": "主要污染物"}.get(i, "总量")
                unit_num = (x["unit"] or "").split("/")[0]
                pct = (a - lead) / a * 100 if a else 0
                item["need"] = "{}从{}降到{}（降{:.1f}%）：同等{}下，{}需减少约{:,.1f} {}".format(
                    x["name"], fmt_auto(a), fmt_auto(lead), pct, "产值" if dunit == "万元" else "产量", label, delta, unit_num)
                if i == "2":
                    kwh = delta * 1000.0 / en["grid_factor"] if en.get("grid_factor") else None
                    if kwh:
                        item["need"] += "；若按市场法认可绿电，相当于约{:,.0f} MWh 外购电改为绿电".format(kwh / 1000.0)
            else:
                item["need"] = "提高到引领值 {}".format(fmt_auto(lead))
        acts.append(item)
    speed_rank = {"快": 0, "快–中": 1, "快（整理）/慢（更新设备）": 1, "快–中（1–3个月）": 1, "中": 2,
                  "中（2–4个月）": 2, "中–慢": 3, "跨年": 4, "慢": 5}
    kind_rank = {"data": 0, "benchmark": 0, "qual": 1, "improve": 2}
    acts.sort(key=lambda z: (kind_rank.get(z.get("kind"), 3), -z["gain"], speed_rank.get(z["speed"], 3)))
    return acts


def path_to_pass(res_total, tiers, gaps):
    """先用“申报前完成即可”的措施，再用影响评价年数据的措施，凑够离分数线的差距。"""
    target = None
    for v in tiers:
        if v.get("threshold") is not None and v.get("gap") and v["gap"] > 0 and v.get("verdict") not in ("不具备申报条件",):
            target = v
            break
    if not target:
        return None
    need = target["gap"]
    steps, acc = [], 0.0
    status_items = sorted([a for a in gaps if a["timing"] == "status"], key=lambda z: -z["gain"])
    year_items = [a for a in gaps if a["timing"] == "year" and a.get("kind") == "improve"]
    for a in status_items + year_items:
        if acc >= need - 1e-9:
            break
        acc += a["gain"]
        steps.append({"id": a["id"], "name": a["name"], "gain": a["gain"], "timing": a["timing"],
                      "after": r(res_total["certain"] + acc, 1)})
    pending = [a for a in gaps if a["timing"] == "info"]
    return {"tier": target["tier"], "threshold": target["threshold"], "need": r(need, 1), "steps": steps,
            "enough": acc >= need - 1e-9,
            "pending_note": ("另有{}项缺数据或缺对标值（最多{}分），补齐后可能直接改变结论".format(
                len(pending), fmt(sum(a["gain"] for a in pending), 0)) if pending else "")}


# ---------------------------------------------------------------------------
# 数据口径检查
# ---------------------------------------------------------------------------
def quality_checks(data, en, warnings):
    meta = data.get("meta") or {}
    out = data.get("output") or {}
    b = meta.get("basis") or "产值"
    # 用行业评价指标表（custom_model）时，分母由指标表自己规定，与产值/产量无关
    if not data.get("custom_model"):
        if b == "产值" and not num(out.get("value_wan")):
            warnings.append("强度类指标按产值计算，但没有工业总产值（万元，现价）。注意用统计报表的工业总产值，不要用营业收入代替。")
        if b == "产量" and not num(out.get("qty")):
            warnings.append("强度类指标按产量计算，但没有合格产品产量。多产品时要折标准产品或按产量分摊，并与对标值口径一致。")
    if en.get("has_energy") and not num((data.get("energy") or {}).get("feedstock_tce")):
        warnings.append("综合能耗不含用作原料的能源（如化工原料用气、用煤）；如有，请填 feedstock_tce 扣除。")
    if num((data.get("resources") or {}).get("water_withdrawal_m3")):
        warnings.append("取水量只算主要、辅助、附属生产系统，不含基建改造、消防和外供水量；重复利用率分母是“取水量+重复利用水量”。")
    if num(g(data, "land", "area_m2")):
        warnings.append("用地面积按土地权属和界址（不动产权证）确定；租赁厂房按实际使用且权属清楚的面积，口径要前后一致。")
    ey = meta.get("eval_year")
    if ey:
        warnings.append("评价年为{}年：强度、比率类指标都用该自然年数据；近三年改造投资取{}—{}年。".format(ey, int(ey) - 2, ey))


# ---------------------------------------------------------------------------
# 时间倒排
# ---------------------------------------------------------------------------
def timeline(data, today):
    meta = data.get("meta") or {}
    target = meta.get("target_level") or "省级"
    cur = meta.get("current_level") or "无"
    y = today.year
    res = {"today": today.isoformat(), "target": target, "windows": [], "notes": []}

    def win(level, year):
        if level == "省级":
            return {"level": "省级", "year": year, "open": "{}年5月前后发通知".format(year),
                    "close": "{}年6月中下旬（以当地为准）".format(year), "data_year": year - 1,
                    "start": _dt.date(year, 5, 15)}
        if level == "国家级":
            return {"level": "国家级", "year": year, "open": "{}年9月下旬发通知".format(year),
                    "close": "{}年10月中下旬地方截止，10月底前后省级报部".format(year), "data_year": year - 1,
                    "start": _dt.date(year, 9, 25)}
        return {"level": "市级", "year": year, "open": "各地不一，常见4—8月", "close": "以当地通知为准",
                "data_year": year - 1, "start": _dt.date(year, 4, 15)}

    def next_win(level):
        w = win(level, y)
        end_guess = {"省级": _dt.date(y, 6, 30), "国家级": _dt.date(y, 10, 31), "市级": _dt.date(y, 8, 31)}[level]
        if today <= end_guess:
            if today >= w["start"]:
                w["state"] = "本年度窗口进行中或接近截止，先查当地通知确认是否还来得及"
            else:
                w["state"] = "本年度窗口未开"
            return w
        w = win(level, y + 1)
        w["state"] = "本年度窗口已过，按下一年度准备"
        return w

    path = []
    if target == "国家级":
        if cur in ("省级", "国家级"):
            path = ["国家级"]
        elif cur == "市级":
            path = ["省级", "国家级"]
        else:
            path = ["市级", "省级", "国家级"]
    elif target == "省级":
        path = ["省级"] if cur in ("市级", "省级", "国家级") else ["市级", "省级"]
    else:
        path = ["市级"]
    prev_year = None
    for lv in path:
        w = next_win(lv)
        if prev_year is not None and w["year"] < prev_year:
            w = win(lv, prev_year)
            w["state"] = "需等上一级名单公布后"
        if lv == "国家级" and prev_year is not None and w["year"] == prev_year:
            w["state"] += "；同年先省级后国家级时间很紧，取决于省级名单公布时间"
        prev_year = w["year"]
        res["windows"].append({k: (v.isoformat() if isinstance(v, _dt.date) else v) for k, v in w.items()})
    if res["windows"]:
        first = res["windows"][0]
        dy = first["data_year"]
        end_of_data_year = _dt.date(dy, 12, 31)
        left = (end_of_data_year - today).days
        if left >= 0:
            res["notes"].append("下一个窗口用{}年数据，{}年还剩{}天：绿证/绿电要对应当年用电，固废利用、回用水要在年内落实，才能体现在评价年数据里。".format(dy, dy, left))
        else:
            res["notes"].append("下一个窗口用{}年数据，该年已结束，定量指标基本定型；现在能做的是补对标值、定性项和能碳系统，以及为下一轮改善当年数据。".format(dy))
        ey = meta.get("eval_year")
        try:
            ey = int(ey) if ey else None
        except (TypeError, ValueError):
            ey = None
        if ey and ey != dy:
            res["notes"].append("注意：你提供的是{}年数据，而下一个窗口按{}年数据评价。本次结论只作参照，{}年全年数据出来后要重算。".format(ey, dy, dy))
        start = _dt.date.fromisoformat(first["start"]) if hasattr(_dt.date, "fromisoformat") else today
        steps = [
            (180, "确定申报主体与边界，判断是否属于重点行业，拉齐评价年能源、水、固废、产值台账"),
            (150, "核对近三年处罚与信用记录（信用中国、企业信用信息公示系统、生态环境和应急部门公示），补齐四体系与绿色低碳规划"),
            (120, "能碳管理系统补齐功能并稳定运行（保留运行记录）"),
            (90, "主要产品碳足迹（GB/T 24067）、绿色设计及验证报告（GB/T 24256）"),
            (60, "整理先进工艺设备证明、近三年改造项目证明、对标值来源文件"),
            (30, "在平台按评价要求预填一遍，自查口径和佐证材料（部分地方提交后只有一次修改机会）"),
        ]
        plan = []
        for d, txt in steps:
            dt = start - _dt.timedelta(days=d)
            plan.append({"by": dt.isoformat(), "task": txt, "late": dt < today})
        res["plan"] = plan
    return res


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def evaluate(data, today=None):
    if today is None:
        today = _dt.date.today()
    warnings = []
    en = compute_energy(data, warnings)
    acts = compute_actuals(data, en, warnings)
    rows = score_all(data, acts, warnings)
    total, cats = summarize(rows)
    gates = check_gates(data)
    tiers = tier_verdicts(data, total, gates)
    gaps = gap_actions(data, rows, en)
    quality_checks(data, en, warnings)
    meta = data.get("meta") or {}
    honors = [h for h in (meta.get("honors") or []) if h]
    pri = [h for h in honors if any(p in h for p in PRIORITY_HONORS)]
    if (meta.get("smart_factory") or "") in ("卓越级", "领航级"):
        pri.insert(0, "{}智能工厂（2026年国家绿色工厂优先推荐）".format(meta.get("smart_factory")))
    result = {
        "engine": "lvse-gongchang/gf_engine " + VERSION, "policy_checked": POLICY_CHECKED,
        "generated": today.isoformat(), "meta": meta,
        "gates": gates, "energy": {k: (r(v, 4) if isinstance(v, float) else v) for k, v in en.items()},
        "indicators": [dict(x, score=r(x["score"], 2), actual=rsig(x["actual"], 6)) for x in rows],
        "categories": cats,
        "total": {"certain": r(total["certain"], 1), "upper": r(total["upper"], 1), "pending_weight": r(total["pending_weight"], 1)},
        "tiers": tiers, "gaps": gaps, "warnings": warnings, "priority": pri,
        "path": path_to_pass(total, tiers, gaps),
        "timeline": timeline(data, today),
    }
    if (meta.get("current_level") or "") == "国家级":
        result["dynamic"] = ("已是国家绿色工厂：每年要对照新评价要求填报动态管理表；"
                             "得分连续三年处于后5%的会被移出，达不到新评价要求的会被适时移出。")
    return result


STATUS_CN = {"full": "满分", "partial": "部分得分", "zero": "零分", "no_data": "缺数据",
             "no_benchmark": "缺对标值", "unknown": "未说明"}


def render_md(res):
    m = res["meta"]
    L = []
    L.append("# 绿色工厂研判结果：{}".format(m.get("name") or "（未填企业名）"))
    L.append("")
    L.append("- 行业：{}（{}）；目标：{}；当前：{}；评价年：{}".format(
        m.get("industry") or "—", "重点行业" if m.get("key_industry") else "非重点行业，按通则",
        m.get("target_level") or "—", m.get("current_level") or "无", m.get("eval_year") or "—"))
    t = res["total"]
    L.append("- 分数账本：确定分 **{}**，待定 {} 分，上限 {}".format(fmt(t["certain"], 1), fmt(t["pending_weight"], 0), fmt(t["upper"], 1)))
    gs = {"ok": "通过", "warn": "有待核实项", "veto": "存在否决项"}[res["gates"]["status"]]
    if res["gates"]["status"] == "veto" and res["gates"].get("veto_from") == "basic":
        gs = "基本要求不满足"
    L.append("- 门槛：{}".format(gs))
    L.append("")
    L.append("## 各层级判断")
    for v in res["tiers"]:
        th = "—" if v.get("threshold") is None else fmt(v["threshold"], 0)
        L.append("- {}（分数线 {}）：**{}**。{}".format(v["tier"], th, v.get("verdict", ""), v.get("detail", "")))
    L.append("")
    L.append("## 指标明细（{}项）".format(len(res["indicators"])))
    L.append("| 序号 | 指标 | 实际值 | 引领值 | 基准值 | 得分/满分 | 状态 |")
    L.append("|---|---|---|---|---|---|---|")
    for x in res["indicators"]:
        if x["kind"] == "qual":
            act = "{}档".format(x.get("level")) if x.get("level") else "—"
        else:
            act = "{} {}".format(fmt_auto(x["actual"]), x["unit"]) if x["actual"] is not None else "—"
        L.append("| {} | {} | {} | {} | {} | {}/{} | {} |".format(
            x["id"], x["name"], act, fmt_auto(x["lead"]), fmt_auto(x["base"]),
            fmt(x["score"], 2) if x["score"] is not None else "—", fmt(x["weight"], 0), STATUS_CN.get(x["status"], "")))
    L.append("")
    p = res.get("path")
    if p:
        L.append("## 过{}线的最短路径（差{}分）".format(p["tier"], fmt(p["need"], 1)))
        for st in p["steps"]:
            L.append("- 指标{} {}：+{}分 → {}分（{}）".format(st["id"], st["name"], fmt(st["gain"], 2), fmt(st["after"], 1),
                     "申报前完成即可" if st["timing"] == "status" else "须改善评价年数据"))
        if not p["enough"]:
            L.append("- 以上全部做到仍不够，需要更长周期的改造")
        if p["pending_note"]:
            L.append("- " + p["pending_note"])
        L.append("")
    L.append("## 提分清单（先补缺口，再按分值排序）")
    for a in res["gaps"][:10]:
        tm = {"year": "影响评价年数据，须在当年落实", "status": "申报前完成即可", "info": "补资料即可，不改数据"}[a["timing"]]
        L.append("- 指标{} {}：最多+{}分｜{}｜{}。{}{}".format(
            a["id"], a["name"], fmt(a["gain"], 2), a["speed"], tm, a["need"],
            "（{}）".format(a["per_point"]) if a.get("per_point") else ""))
    if res["warnings"]:
        L.append("")
        L.append("## 口径提醒")
        for w in res["warnings"]:
            L.append("- " + w)
    tl = res.get("timeline") or {}
    if tl.get("windows"):
        L.append("")
        L.append("## 时间")
        for w in tl["windows"]:
            L.append("- {} {}年度：{}；{}；用{}年数据。{}".format(w["level"], w["year"], w["open"], w["close"], w["data_year"], w.get("state", "")))
        for n in tl.get("notes", []):
            L.append("- " + n)
    if res.get("priority"):
        L.append("")
        L.append("优先推荐因素：" + "、".join(res["priority"]))
    if res.get("dynamic"):
        L.append("")
        L.append(res["dynamic"])
    L.append("")
    L.append("> 本结果按 GB/T 36132—2025 和工信部年度评价要求推算，定性项按经验三档估计，不是官方评审结论；政策核对日期 {}。".format(res["policy_checked"]))
    return "\n".join(L)


DEMO = {
    "schema": "lvse-gongchang/v1",
    "meta": {"name": "示例传动科技有限公司（演示数据）", "province": "江苏", "industry": "齿轮及齿轮减、变速箱制造",
             "industry_code": "C3453", "is_c_manufacturing": True, "key_industry": False,
             "target_level": "省级", "current_level": "市级", "eval_year": 2025, "smart_factory": "先进级",
             "honors": ["专精特新"], "basis": "产值", "product_unit": "台"},
    "thresholds": {},
    "gates": {"g1": "否", "g2": "否", "g3": "否", "g4": "否", "g5": "否", "g6": "否", "g7": "否", "g8": "否", "g9": "否"},
    "basic": {"b1": "是", "b2": "认证", "b3": "认证", "b4": "建立运行", "b5": "认证"},
    "energy": {"grid_kwh": 18900000, "pv_self_kwh": 2600000, "green_trade_kwh": 0, "gec_mwh": 0,
               "natural_gas_m3": 380000, "diesel_t": 45, "gasoline_t": 12, "carbon_method": "location"},
    "output": {"value_wan": 62000, "qty": 48000, "value_3y_wan": 171000},
    "resources": {"water_withdrawal_m3": 96000, "water_reuse_m3": 1104000, "material_qty": 21800, "material_unit": "t",
                  "sw_generated_t": 2350, "sw_utilized_t": 2256, "sw_stock_utilized_t": 0},
    "pollution": {"name": "VOCs", "qty": 6.2, "unit": "t"},
    "land": {"area_m2": 66700},
    "upgrade": {"invest_3y_wan": 4000},
    "ecms": {"running": True, "functions": ["能耗查询", "能源消费量和强度计算", "能源消费分析与用能策略推荐",
                                             "能效对标", "能流分析", "碳排放"]},
    "qualitative": {"9": "A", "12": "C", "13": "B"},
    "benchmarks": {
        "1": {"lead": 0.045, "base": 0.070, "src": "演示值，非真实行业数据"},
        "2": {"lead": 0.160, "base": 0.300, "src": "演示值，非真实行业数据"},
        "3": {"lead": 12, "base": 2, "src": "演示值，非真实行业数据"},
        "6": {"lead": 1.2, "base": 3.0, "src": "演示值，非真实行业数据"},
        "7": {"lead": 90, "base": 70, "src": "演示值，非真实行业数据"},
        "8": {"lead": 95, "base": 80, "src": "演示值，非真实行业数据"},
        "10": {"lead": 2.5, "base": 0.5, "src": "演示值，非真实行业数据"},
        "14": {"lead": 1.0, "base": 0.5, "src": "演示值，非真实行业数据"},
    },
}


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="绿色工厂研判引擎")
    ap.add_argument("input", nargs="?", help="输入 JSON 文件（UTF-8）")
    ap.add_argument("--out", help="结果 JSON 输出路径")
    ap.add_argument("--md", help="结果 Markdown 输出路径")
    ap.add_argument("--today", help="指定今天日期 YYYY-MM-DD")
    ap.add_argument("--write-demo", help="把演示输入写到这个路径")
    ap.add_argument("--quiet", action="store_true", help="不在终端打印 Markdown")
    a = ap.parse_args(argv)
    if a.write_demo:
        with io.open(a.write_demo, "w", encoding="utf-8") as f:
            json.dump(DEMO, f, ensure_ascii=False, indent=2)
        print("demo written: " + a.write_demo)
        return 0
    if not a.input:
        ap.print_help()
        return 1
    with io.open(a.input, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    today = None
    if a.today:
        y, mth, d = [int(x) for x in a.today.split("-")]
        today = _dt.date(y, mth, d)
    res = evaluate(data, today)
    if a.out:
        with io.open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
    md = render_md(res)
    if a.md:
        with io.open(a.md, "w", encoding="utf-8") as f:
            f.write(md)
    if not a.quiet:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
