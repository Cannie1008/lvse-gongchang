# -*- coding: utf-8 -*-
"""
把 gf_engine.py 的结果 JSON 生成“绿色工厂自评价报告（底稿）”Word 文件。只用标准库。

用途：部分地方要求提交纸质自评价报告（例：辽宁朝阳2026年市级通知“对照自评价报告模板形成纸质版自评价报告”）。
有当地模板的，以模板为准；没有的，用本底稿按七部分结构改写。

用法：
  python make_selfeval.py result.json --out 自评价报告底稿.docx
  python make_selfeval.py result.json --out 底稿.docx --org "某某有限公司"

原则：只填工具算出来的数和用户给的数；企业才知道的内容一律写成【待企业补充：……】，不替企业编。
"""
from __future__ import print_function

import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_report import Doc, COLORS, GATE_CN, GREEN, TINT, evidence_for, f1, f2  # noqa: E402
from gf_engine import fmt_auto, _utf8_stdout, QUAL_TEXT  # noqa: E402

TODO = "【待企业补充：{}】"
CAT_PROMPTS = [
    ("能源低碳化", "近三年节能降碳改造项目及成效；光伏、绿电、绿证情况；能碳管理系统建设和运行情况"),
    ("资源高效化", "原材料利用率提升、节水与水循环利用、一般工业固废综合利用的做法和数据"),
    ("生产洁净化", "先进工艺设备采用情况、污染治理设施升级、有毒有害物质替代"),
    ("产品绿色化", "产品绿色设计、碳足迹量化、绿色设计产品或绿色产品认证情况"),
    ("用地集约化", "厂房多层化、用地效率提升、亩均产出变化"),
]


def _level_cn(lv):
    return {"ok": "符合", "ok_weak": "符合（体系已建立运行，未认证）", "warn": "待核实", "risk": "存疑", "veto": "不符合"}.get(lv, lv)


def build(res, org=None):
    m = res.get("meta") or {}
    t = res["total"]
    d = Doc()
    d.para([d.run("绿色工厂自评价报告（底稿）")], style="Title")
    d.para([d.run(m.get("name") or TODO.format("企业名称"), bold=True, size=13)], after=40)
    d.para([d.run("评价年：{}　依据：GB/T 36132—2025《绿色工厂评价通则》{}　生成日期：{}".format(
        m.get("eval_year") or TODO.format("评价年"),
        "及平台行业评价要求" if m.get("key_industry") else "",
        res.get("generated")), color=COLORS["muted"], size=9.5)], after=120)

    # 醒目提示
    warn_lines = ["本底稿由AI智能体技能“绿色工厂研判助手”按已填数据生成（AI辅助生成），仅供企业内部修改。【待企业补充】处须企业据实填写；"
                  "标为演示值、待定、缺数据、缺对标值的内容不得直接提交。数据或材料造假的，移出名单，三年内不得再次申报。"]
    gst = res["gates"]["status"]
    if gst == "veto":
        if res["gates"].get("veto_from") == "basic":
            warn_lines.append("基本要求不满足：按规定不得申报，本底稿只作内部整改参考。")
        else:
            warn_lines.append("存在否决情形：按规定不得申报，本底稿只作内部整改参考。")
    elif gst == "risk":
        warn_lines.append("近三年有违法违规记录：先向当地工信部门确认能否申报，再形成申报材料。")
    if any("演示" in (it.get("src") or "") for it in res["indicators"]):
        warn_lines.append("对标值中含演示值，必须换成有出处的真实对标值后才能使用。")
    if t.get("pending_weight"):
        warn_lines.append("有{}分的指标待定（缺数据或缺对标值），自评总分暂不能确定。".format(f1(t["pending_weight"])))
    for w in warn_lines:
        d.para([d.run(w, color=COLORS["veto"], bold=True, size=10)], shade=TINT, before=40, after=40)

    # 一、企业基本情况
    d.h1("一、企业基本情况")
    en = res.get("energy") or {}
    tce_by = en.get("tce_by_type") or {}
    tot = en.get("total_tce")
    if tot:
        mix = "；".join("{} {} tce（{}%）".format(k, fmt_auto(v), f1(v / tot * 100)) for k, v in tce_by.items() if v)
    else:
        mix = TODO.format("评价年各类能源消费量")
    place = (m.get("province") or "") + (m.get("city") or "")
    rows = [
        ["企业名称（申报主体）", m.get("name") or TODO.format("企业名称")],
        ["统一社会信用代码", TODO.format("统一社会信用代码")],
        ["所在地区", place or TODO.format("所在省市")],
        ["所属行业及代码（GB/T 4754）", "{} {}".format(m.get("industry") or "", m.get("industry_code") or "").strip() or TODO.format("行业及代码")],
        ["是否属于重点行业", "是（按平台行业评价要求自评）" if m.get("key_industry") else "否（按 GB/T 36132—2025 通则自评）"],
        ["主要产品及产能", TODO.format("主要产品名称、设计产能、评价年产量")],
        ["评价年综合能耗", "{} tce（不含用作原料的能源）".format(fmt_auto(tot)) if tot else TODO.format("评价年综合能耗")],
        ["评价年能源消费结构", mix],
        ["近三年经营情况", TODO.format("近三年工业总产值、营业收入、利润、员工人数，与统计报表一致")],
    ]
    d.table(["项目", "内容"], rows, [30, 70])

    # 二、基本要求与否决情形自查
    d.h1("二、基本要求与否决情形自查")
    d.h2("近三年否决情形")
    rows, cols = [], []
    for it in res["gates"]["items"]:
        rows.append([it["label"], it["value"], _level_cn(it["level"]), TODO.format("信用中国、企业信用信息公示系统截图或说明")])
        cols.append([None, None, it["level"] if it["level"] != "ok" else "ok", None])
    d.table(["情形", "企业情况", "自查结论", "依据或证明材料"], rows, [44, 12, 14, 30], colors=cols, align=[None, "center", "center", None])
    d.h2("基本要求（GB/T 36132—2025 第4.2条）")
    rows, cols = [], []
    for it in res["gates"]["basic"]:
        lv = it["level"]
        rows.append([it["label"], it["value"], _level_cn(lv), TODO.format("证书编号、有效期，或手册、内审、管理评审记录")])
        cols.append([None, None, "ok" if lv in ("ok", "ok_weak") else lv, None])
    d.table(["要求", "企业情况", "自查结论", "证明材料"], rows, [36, 14, 18, 32], colors=cols, align=[None, "center", "center", None])

    # 三、评价指标自评
    d.h1("三、评价指标自评")
    rows, cols = [], []
    for it in res["indicators"]:
        if it["kind"] == "qual":
            lv = it.get("level")
            act = "拟定{}档".format(lv) if lv else TODO.format("开展情况")
            calc = (QUAL_TEXT.get(it["id"], {}).get(lv, "") if not it.get("custom") and lv else "") + " " + TODO.format("对应报告或证明的名称、编号、出具单位")
            bench = "定性项"
        else:
            act = "{} {}".format(fmt_auto(it["actual"]), it.get("unit") or "") if it["actual"] is not None else TODO.format("实际值")
            calc = it.get("calc") or ""
            if it["lead"] is not None and it["base"] is not None:
                bench = "引领{}／基准{}；出处：{}".format(fmt_auto(it["lead"]), fmt_auto(it["base"]), it.get("src") or TODO.format("文件名、条款、年份"))
            else:
                bench = TODO.format("有出处的引领值和基准值")
        sc = "{}/{}".format(f2(it["score"]) if it["score"] is not None else "待定", int(it["weight"]))
        rows.append([it["id"], it["name"], act, calc.strip(), bench, sc])
        bad = it["status"] in ("no_data", "no_benchmark", "unknown") or "演示" in (it.get("src") or "")
        cols.append([None] * 5 + ["warn" if bad else None])
    d.table(["序号", "指标", "实际值", "计算过程或依据", "对标值及出处", "自评得分"], rows, [6, 18, 16, 26, 22, 12],
            colors=cols, align=["center", None, None, None, None, "center"])
    d.para([d.run("定性项（工艺设备先进性、绿色设计、产品碳足迹）的档次是研判工具的经验估计，提交前按平台填报说明逐项核对。",
                  size=9, color=COLORS["muted"])])

    # 四、自评结果
    d.h1("四、自评结果")
    rows = [[c["cat"], f1(c["weight"]), f2(c["score"]), f2(c["upper"])] for c in res["categories"]]
    rows.append(["合计", "100", f1(t["certain"]), f1(t["upper"])])
    d.table(["一级指标", "满分", "确定得分", "上限"], rows, [40, 20, 20, 20], align=[None, "center", "center", "center"])
    if t.get("pending_weight"):
        concl = "按已确定的数据，自评得分{}分；另有{}分的指标待定，补齐数据和对标值后再形成自评结论。".format(f1(t["certain"]), f1(t["pending_weight"]))
    else:
        concl = "按 GB/T 36132—2025 及评价要求自评，总分{}分。".format(f1(t["certain"]))
    if gst in ("veto", "risk"):
        concl += "门槛核查：{}。".format({"veto": "存在否决情形或基本要求不满足", "risk": "近三年有违法违规记录，待当地主管部门确认"}[gst])
    d.para([d.run(concl, bold=True)])

    # 五、主要做法与亮点
    d.h1("五、主要做法与亮点")
    for cat, prompt in CAT_PROMPTS:
        d.para([d.run(cat + "：", bold=True, color=GREEN), d.run(TODO.format(prompt))])

    # 六、存在问题与改进计划
    d.h1("六、存在问题与改进计划")
    rows = []
    for a in res.get("gaps") or []:
        need = a.get("need") or a.get("how") or ""
        rows.append(["指标{} {}".format(a["id"], a["name"]), need, "可选：" + (a.get("how") or ""),
                     TODO.format("完成时间"), TODO.format("责任部门")])
    if rows:
        d.table(["指标", "差距", "改进措施", "完成时间", "责任部门"], rows, [16, 30, 26, 14, 14])
    else:
        d.para([d.run(TODO.format("存在的问题和下一步改进计划"))])

    # 七、佐证材料索引
    d.h1("七、附件：佐证材料索引")
    rows = [["0", "营业执照、信用记录截图、四个管理体系证书或运行记录、绿色低碳规划和年度目标文件、排污许可证", "门槛-材料名-年份", TODO.format("页码")]]
    for it in res["indicators"]:
        rows.append([it["id"], "指标{} {}：{}".format(it["id"], it["name"], evidence_for(it)),
                     "指标{}-材料名-年份".format(it["id"]), TODO.format("页码")])
    d.table(["序号", "材料", "建议文件名", "页码"], rows, [8, 58, 20, 14], align=["center", None, None, "center"])

    d.h1("八、真实性承诺")
    d.para([d.run("本单位承诺：本报告及所附材料中的数据和信息真实、准确、完整，与统计报表、审计报告、能源利用状况报告等口径一致；"
                  "如有虚假，愿意承担相应责任（包括被移出名单、三年内不得再次申报）。")])
    d.para([d.run("法定代表人（签字）：" + TODO.format("签字") + "　　单位（盖章）：" + TODO.format("盖章") + "　　日期：" + TODO.format("日期"))], before=120)
    d.para([d.run("当地另有承诺书格式的，以当地格式为准。", size=9, color=COLORS["muted"])])

    d.h1("说明")
    for s in ["本底稿由AI智能体技能辅助生成，只填入了按规则算出的数和用户提供的数，须经企业逐项核对、补充并对真实性负责后才能使用。",
              "本底稿按 GB/T 36132—2025 和工信部年度评价要求的结构生成；当地有自评价报告模板的，以模板为准。",
              "申报数据必须真实，并与统计报表、审计报告、能源利用状况报告等口径一致。",
              "出具：{}".format(org) if org else "出具：企业自评（研判工具生成底稿）"]:
        d.para([d.run(s, size=9.5)])
    return d


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="生成绿色工厂自评价报告（底稿）")
    ap.add_argument("result", help="gf_engine.py 输出的结果 JSON")
    ap.add_argument("--out", default="绿色工厂自评价报告底稿.docx")
    ap.add_argument("--org", help="出具单位（可选，一般为企业自身）")
    a = ap.parse_args(argv)
    with io.open(a.result, "r", encoding="utf-8-sig") as f:
        res = json.load(f)
    d = build(res, a.org)
    d.save(a.out, "绿色工厂自评价报告（底稿） - " + str((res.get("meta") or {}).get("name") or ""))
    print("draft written: " + os.path.abspath(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
