# -*- coding: utf-8 -*-
"""
读取 assets/绿色工厂数据采集表.xlsx（填好后），输出 gf_engine.py 的输入 JSON。只用标准库。

用法：
  python xlsx_to_json.py 填好的采集表.xlsx --out input.json
然后：
  python gf_engine.py input.json --out result.json --md result.md

只读“输入单元格”（蓝字黄底），不依赖表里公式的缓存值，所以用 WPS、Excel 保存都可以。
百分比指标（3、7、8、10）的对标值如果是以“12%”的形式输入的（单元格是百分比格式），会自动换算成 12。
"""
from __future__ import print_function

import argparse
import io
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}

S1, S2, S3, S4, S5 = "1基本信息", "2能源与碳", "3资源产出", "4定性与系统", "5对标值"

# 字段 -> (工作表, 单元格)。模板生成脚本也使用这张表，两边不会错位。
CELLMAP = {
    "meta.name": (S1, "C6"), "meta.province": (S1, "C7"), "meta.industry": (S1, "C8"),
    "meta.industry_code": (S1, "C9"), "meta.is_c_manufacturing": (S1, "C10"), "meta.key_industry": (S1, "C11"),
    "meta.target_level": (S1, "C12"), "meta.current_level": (S1, "C13"), "meta.eval_year": (S1, "C14"),
    "meta.smart_factory": (S1, "C15"), "meta.honors": (S1, "C16"), "meta.basis": (S1, "C17"),
    "meta.product_unit": (S1, "C18"),
    "gates.g1": (S1, "C21"), "gates.g2": (S1, "C22"), "gates.g3": (S1, "C23"), "gates.g4": (S1, "C24"),
    "gates.g5": (S1, "C25"), "gates.g6": (S1, "C26"), "gates.g7": (S1, "C27"), "gates.g8": (S1, "C28"),
    "gates.g9": (S1, "C29"),
    "basic.b1": (S1, "C32"), "basic.b2": (S1, "C33"), "basic.b3": (S1, "C34"), "basic.b4": (S1, "C35"),
    "basic.b5": (S1, "C36"),
    "thresholds.市级": (S1, "C39"), "thresholds.省级": (S1, "C40"), "thresholds.national_regional_avg": (S1, "C41"),
    "energy.grid_kwh": (S2, "C5"), "energy.pv_self_kwh": (S2, "C6"), "energy.direct_green_kwh": (S2, "C7"),
    "energy.green_trade_kwh": (S2, "C8"), "energy.gec_mwh": (S2, "C9"), "energy.natural_gas_m3": (S2, "C10"),
    "energy.diesel_t": (S2, "C11"), "energy.gasoline_t": (S2, "C12"), "energy.lpg_t": (S2, "C13"),
    "energy.fuel_oil_t": (S2, "C14"), "energy.coal_t": (S2, "C15"), "energy.coke_t": (S2, "C16"),
    "energy.heat_gj": (S2, "C17"), "energy.other_tce": (S2, "C18"), "energy.other_renewable_tce": (S2, "C19"),
    "energy.other_co2_t": (S2, "C20"), "energy.feedstock_tce": (S2, "C21"), "energy.exported_tce": (S2, "C22"),
    "energy.carbon_method": (S2, "C25"), "energy.grid_factor": (S2, "C26"), "energy.ng_coef": (S2, "C27"),
    "output.value_wan": (S3, "C5"), "output.qty": (S3, "C6"), "output.value_3y_wan": (S3, "C7"),
    "upgrade.invest_3y_wan": (S3, "C8"),
    "resources.water_withdrawal_m3": (S3, "C10"), "resources.water_reuse_m3": (S3, "C11"),
    "resources.material_name": (S3, "C13"), "resources.material_qty": (S3, "C14"), "resources.material_unit": (S3, "C15"),
    "resources.sw_generated_t": (S3, "C17"), "resources.sw_utilized_t": (S3, "C18"), "resources.sw_stock_utilized_t": (S3, "C19"),
    "pollution.name": (S3, "C21"), "pollution.qty": (S3, "C22"), "pollution.unit": (S3, "C23"),
    "land.area_m2": (S3, "C25"), "land.capacity": (S3, "C26"),
    "ecms.running": (S4, "C5"),
    "qualitative.9": (S4, "C20"), "qualitative.12": (S4, "C21"), "qualitative.13": (S4, "C22"),
}
ECMS_ROWS = list(range(7, 19))  # 4定性与系统!C7:C18 对应12项功能
ECMS_FUNCS = ["能耗查询", "能源消费量和强度计算", "能源消费分析与用能策略推荐", "能效对标",
              "能流分析", "能效平衡与优化", "用能与碳排放预算管理", "碳排放",
              "碳足迹核算", "供应链碳管理", "碳核查支撑", "碳资产管理"]
PCT_BENCH = {"3", "7", "8", "10"}  # 这几项的对标值是百分数
BENCH_ROWS = {"1": 5, "2": 6, "3": 7, "5": 8, "6": 9, "7": 10, "8": 11, "10": 12, "11": 13, "14": 14}  # 5对标值 C=引领 D=基准 E=来源
NUMERIC = {"meta.eval_year"}
YESNO_BOOL = {"meta.is_c_manufacturing", "meta.key_industry"}


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _pct_styles(z, names):
    """返回被设成百分比格式的样式序号集合（内置格式9、10，或自定义格式里含引号外的 %）。"""
    if "xl/styles.xml" not in names:
        return set()
    root = ET.fromstring(z.read("xl/styles.xml"))
    custom = {}
    nf = root.find("m:numFmts", NS)
    if nf is not None:
        for f in nf.findall("m:numFmt", NS):
            custom[int(f.attrib["numFmtId"])] = f.attrib.get("formatCode", "")
    out = set()
    xfs = root.find("m:cellXfs", NS)
    if xfs is None:
        return out
    for i, xf in enumerate(xfs.findall("m:xf", NS)):
        fid = int(xf.attrib.get("numFmtId", "0"))
        code = custom.get(fid, "")
        if fid in (9, 10) or "%" in re.sub(r'"[^"]*"', "", code):
            out.add(i)
    return out


def read_cells(path, pct_refs=None):
    """返回 {工作表名: {单元格: 值}}，值为字符串或数字。pct_refs 传入时，会记录百分比格式的单元格（sheet!ref）。"""
    z = zipfile.ZipFile(path)
    names = z.namelist()
    pct_style = _pct_styles(z, names)
    shared = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid2target = {}
    for rel in rels:
        t = rel.attrib["Target"]
        t = t.lstrip("/")
        if not t.startswith("xl/"):
            t = "xl/" + t
        rid2target[rel.attrib["Id"]] = t
    out = {}
    for sh in wb.find("m:sheets", NS):
        name = sh.attrib["name"]
        rid = sh.attrib["{%s}id" % NS["r"]]
        target = rid2target.get(rid)
        if not target or target not in names:
            continue
        root = ET.fromstring(z.read(target))
        cells = {}
        for c in root.iter("{%s}c" % NS["m"]):
            ref = c.attrib.get("r")
            t = c.attrib.get("t")
            v = c.find("m:v", NS)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
            elif t in ("str", "e"):
                val = v.text if v is not None else None
            elif v is not None and v.text is not None:
                try:
                    f = float(v.text)
                    val = int(f) if f.is_integer() and abs(f) < 1e15 else f
                except ValueError:
                    val = v.text
            else:
                val = None
            if c.find("m:f", NS) is not None:
                continue  # 公式单元格不作为输入
            cells[ref] = val
            if pct_refs is not None and isinstance(val, (int, float)) and int(c.attrib.get("s", "0")) in pct_style:
                pct_refs.add("{}!{}".format(name, ref))
        out[name] = cells
    return out


def _set(d, dotted, value):
    keys = dotted.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def to_input(cells, pct_refs=None):
    pct_refs = pct_refs or set()
    data = {"schema": "lvse-gongchang/v1"}
    for field, (sheet, ref) in CELLMAP.items():
        v = cells.get(sheet, {}).get(ref)
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                v = None
        if v is None:
            continue
        if field in YESNO_BOOL:
            v = True if str(v) in ("是", "Y", "y", "1", "true") else (False if str(v) in ("否", "N", "n", "0", "false") else None)
            if v is None:
                continue
        if field == "meta.honors":
            v = [h for h in re.split(r"[,，、;；\s]+", str(v)) if h]
        if field == "energy.carbon_method":
            v = "market" if "市场" in str(v) else "location"
        if field in NUMERIC:
            try:
                v = int(float(v))
            except (TypeError, ValueError):
                pass
        _set(data, field, v)
    funcs = []
    for i, row in enumerate(ECMS_ROWS):
        v = cells.get(S4, {}).get("C{}".format(row))
        if str(v).strip() in ("是", "Y", "y", "1", "有"):
            funcs.append(ECMS_FUNCS[i])
    data.setdefault("ecms", {})["functions"] = funcs
    run = (data.get("ecms") or {}).get("running")
    if run is not None:
        data["ecms"]["running"] = True if str(run) in ("是", "有") else False
    bm = {}
    for k, row in BENCH_ROWS.items():
        c5 = cells.get(S5, {})
        lead, base, src = c5.get("C{}".format(row)), c5.get("D{}".format(row)), c5.get("E{}".format(row))
        if k in PCT_BENCH:
            if "{}!C{}".format(S5, row) in pct_refs and isinstance(lead, (int, float)):
                lead = round(lead * 100, 10)
            if "{}!D{}".format(S5, row) in pct_refs and isinstance(base, (int, float)):
                base = round(base * 100, 10)
        if lead not in (None, "") or base not in (None, ""):
            bm[k] = {"lead": lead, "base": base, "src": src or ""}
    data["benchmarks"] = bm
    return data


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="采集表 -> 引擎输入 JSON")
    ap.add_argument("xlsx")
    ap.add_argument("--out", default="input.json")
    a = ap.parse_args(argv)
    pct = set()
    data = to_input(read_cells(a.xlsx, pct), pct)
    with io.open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("input written: " + os.path.abspath(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
