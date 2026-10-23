# -*- coding: utf-8 -*-
"""
把 gf_engine.py 的结果 JSON 生成 Word 研判报告（.docx）。只用标准库。

用法：
  python make_report.py result.json --out 绿色工厂研判报告.docx
  python make_report.py result.json --out report.docx --org "某某咨询" --contact "电话/微信"
"""
from __future__ import print_function

import argparse
import datetime as _dt
import io
import json
import os
import sys
import zipfile
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from gf_engine import fmt_auto, _utf8_stdout, STATUS_CN, QUAL_TEXT
except Exception:  # 兜底：单独拷走本文件也能用
    def fmt_auto(v):
        return "—" if v is None else "{:.4g}".format(v)

    def _utf8_stdout():
        pass
    STATUS_CN = {}
    QUAL_TEXT = {}

GREEN = "2F5D46"
TINT = "E9F0EB"
LINE = "BFCDC3"
COLORS = {"ok": "2E7D4F", "warn": "B7791F", "veto": "B23A2E", "muted": "6B7A71"}


def x(s):
    return escape("" if s is None else str(s))


def f1(v):
    return "—" if v is None else "{:.1f}".format(v)


def f2(v):
    return "—" if v is None else "{:.2f}".format(v)


class Doc(object):
    """极简 docx 写入：段落、标题、表格、页脚页码。"""
    W = 9638  # 正文宽度（A4 减去左右边距，单位 twip）

    def __init__(self):
        self.body = []

    def run(self, text, bold=False, color=None, size=None, font=None):
        rpr = []
        if font:
            rpr.append('<w:rFonts w:ascii="{0}" w:hAnsi="{0}" w:eastAsia="{0}"/>'.format(font))
        if bold:
            rpr.append("<w:b/><w:bCs/>")
        if color:
            rpr.append('<w:color w:val="{}"/>'.format(color))
        if size:
            rpr.append('<w:sz w:val="{0}"/><w:szCs w:val="{0}"/>'.format(int(size * 2)))
        return '<w:r>{}<w:t xml:space="preserve">{}</w:t></w:r>'.format(
            "<w:rPr>{}</w:rPr>".format("".join(rpr)) if rpr else "", x(text))

    def para(self, runs, style=None, align=None, before=None, after=None, shade=None, keep=False, indent=None):
        if isinstance(runs, str):
            runs = [self.run(runs)]
        ppr = []
        if style:
            ppr.append('<w:pStyle w:val="{}"/>'.format(style))
        if keep:
            ppr.append("<w:keepNext/>")
        if shade:
            ppr.append('<w:pBdr><w:left w:val="single" w:sz="18" w:space="8" w:color="{}"/></w:pBdr>'.format(GREEN))
            ppr.append('<w:shd w:val="clear" w:color="auto" w:fill="{}"/>'.format(shade))
        if before is not None or after is not None:
            ppr.append('<w:spacing w:before="{}" w:after="{}"/>'.format(before or 0, after or 0))
        if indent:
            ppr.append('<w:ind w:left="{0}" w:hanging="{0}"/>'.format(indent))
        if align:
            ppr.append('<w:jc w:val="{}"/>'.format(align))
        self.body.append("<w:p>{}{}</w:p>".format("<w:pPr>{}</w:pPr>".format("".join(ppr)) if ppr else "", "".join(runs)))

    def h1(self, text):
        self.para([self.run(text)], style="Heading1", keep=True)

    def h2(self, text):
        self.para([self.run(text)], style="Heading2", keep=True)

    def table(self, header, rows, widths, colors=None, align=None):
        total = sum(widths)
        widths = [int(w * self.W / total) for w in widths]
        grid = "".join('<w:gridCol w:w="{}"/>'.format(w) for w in widths)
        b = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="{1}"/>'
        borders = "".join(b.format(s, LINE) for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
        out = ['<w:tbl><w:tblPr><w:tblW w:w="{}" w:type="dxa"/><w:tblBorders>{}</w:tblBorders>'
               '<w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="50" w:type="dxa"/><w:left w:w="90" w:type="dxa"/>'
               '<w:bottom w:w="50" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tblCellMar></w:tblPr>'
               '<w:tblGrid>{}</w:tblGrid>'.format(sum(widths), borders, grid)]

        def cell(text, w, fill=None, bold=False, color=None, jc=None):
            tcpr = '<w:tcW w:w="{}" w:type="dxa"/>'.format(w)
            if fill:
                tcpr += '<w:shd w:val="clear" w:color="auto" w:fill="{}"/>'.format(fill)
            ppr = '<w:pPr><w:pStyle w:val="TableText"/>{}</w:pPr>'.format('<w:jc w:val="{}"/>'.format(jc) if jc else "")
            paras = []
            for line in str("" if text is None else text).split("\n"):
                paras.append("<w:p>{}{}</w:p>".format(ppr, self.run(line, bold=bold, color=color)))
            return "<w:tc><w:tcPr>{}</w:tcPr>{}</w:tc>".format(tcpr, "".join(paras))

        hdr = "".join(cell(h, widths[i], fill=TINT, bold=True, color=GREEN) for i, h in enumerate(header))
        out.append('<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>{}</w:tr>'.format(hdr))
        for ri, row in enumerate(rows):
            cs = []
            for ci, v in enumerate(row):
                col = colors[ri][ci] if colors and colors[ri] and ci < len(colors[ri]) else None
                jc = align[ci] if align else None
                cs.append(cell(v, widths[ci], color=COLORS.get(col, col) if col else None, bold=bool(col), jc=jc))
            out.append("<w:tr><w:trPr><w:cantSplit/></w:trPr>{}</w:tr>".format("".join(cs)))
        out.append("</w:tbl>")
        self.body.append("".join(out))
        self.para([self.run("")], after=60)

    def save(self, path, title):
        sect = ('<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter1"/>'
                '<w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1361" w:right="1134" w:bottom="1247" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/>'
                '</w:sectPr>')
        doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
               'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
               '<w:body>{}{}</w:body></w:document>').format("".join(self.body), sect)
        styles = STYLES
        footer = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                  '<w:p><w:pPr><w:pStyle w:val="Footer"/><w:jc w:val="center"/></w:pPr>'
                  '<w:r><w:t xml:space="preserve">第 </w:t></w:r><w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'
                  '<w:r><w:t xml:space="preserve"> 页</w:t></w:r></w:p></w:ftr>')
        ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/>'
              '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
              '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
              '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
              '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
              '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
              '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
              '</Types>')
        rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
                '</Relationships>')
        drels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                 '<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
                 '<Relationship Id="rIdFooter1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
                 '</Relationships>')
        settings = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    '<w:defaultTabStop w:val="420"/><w:compat><w:compatSetting w:name="compatibilityMode" '
                    'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>')
        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{}</dc:title><dc:creator>绿色工厂研判助手</dc:creator>'
                '<dcterms:created xsi:type="dcterms:W3CDTF">{}</dcterms:created></cp:coreProperties>').format(x(title), now)
        app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
               '<Application>lvse-gongchang</Application></Properties>')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("_rels/.rels", rels)
            z.writestr("word/document.xml", doc)
            z.writestr("word/_rels/document.xml.rels", drels)
            z.writestr("word/styles.xml", styles)
            z.writestr("word/settings.xml", settings)
            z.writestr("word/footer1.xml", footer)
            z.writestr("docProps/core.xml", core)
            z.writestr("docProps/app.xml", app)


STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
          '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="宋体" w:cs="Arial"/>'
          '<w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault>'
          '<w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="320" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
          '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
          '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/>'
          '<w:pPr><w:spacing w:before="0" w:after="120"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="黑体"/>'
          '<w:b/><w:color w:val="' + GREEN + '"/><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
          '<w:pPr><w:keepNext/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="4" w:color="' + LINE + '"/></w:pBdr><w:spacing w:before="320" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>'
          '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="黑体"/><w:b/><w:color w:val="' + GREEN + '"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>'
          '<w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr>'
          '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="黑体"/><w:b/><w:sz w:val="23"/><w:szCs w:val="23"/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/>'
          '<w:pPr><w:spacing w:before="0" w:after="0" w:line="260" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>'
          '<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/>'
          '<w:rPr><w:color w:val="6B7A71"/><w:sz w:val="16"/></w:rPr></w:style>'
          '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/>'
          '<w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'
          '</w:styles>')

GATE_CN = {"ok": "通过", "warn": "待核实", "veto": "否决", "ok_weak": "满足（未认证）"}
TIMING_CN = {"year": "须在评价年内落实", "status": "申报前完成即可", "info": "补资料即可"}

EVIDENCE = {
    "1": "能源购进、消费与库存台账；电、气、油发票或结算单；能源利用状况报告或统计报表；对标值来源（能耗限额标准分级或行业数据）",
    "2": "温室气体排放核算报告（GB/T 32150 或行业核算标准），核查报告更好；电力排放因子的出处",
    "3": "光伏发电自用量计量记录；绿电交易合同与结算凭证；绿证（核发/划转记录）；可再生电力消费核算清单",
    "4": "能碳管理系统运行截图、功能清单、数据导出记录；系统建设合同或验收材料",
    "5": "主要原材料领用与库存台账、物料平衡表；对标值来源",
    "6": "取水计量台账、水费票据或取水许可；用水定额文件",
    "7": "循环水、回用水计量记录；水平衡测试报告",
    "8": "一般工业固废产生、贮存、利用台账；综合利用合同与转移、接收凭证",
    "9": "工艺设备清单与推荐目录、行业规范条件的逐项对应表；采购合同、铭牌照片、验收资料",
    "10": "近三年绿色低碳改造项目清单、立项或备案文件、合同发票、竣工验收与成效证明；三年工业总产值统计",
    "11": "排污许可执行报告、自行监测报告或在线监测数据；对标值来源",
    "12": "依据 GB/T 24256 的产品绿色设计及验证报告；设计改进前后的环境绩效对比",
    "13": "依据 GB/T 24067 的主要产品碳足迹量化报告（第三方核查或认证更有说服力）",
    "14": "不动产权证（土地面积）、工业总产值统计；地方用地控制指标或对标值来源",
}


def build(res, org=None, contact=None):
    m = res.get("meta") or {}
    d = Doc()
    name = m.get("name") or "（未填企业名称）"
    d.para([d.run("绿色工厂研判报告")], style="Title")
    d.para([d.run(name, bold=True, size=13)], after=40)
    sub = "目标：{}　当前：{}　评价年：{}　行业：{}（{}）".format(
        m.get("target_level") or "—", m.get("current_level") or "无", m.get("eval_year") or "—",
        m.get("industry") or "—", "重点行业" if m.get("key_industry") else "非重点行业，按通则")
    d.para([d.run(sub, color=COLORS["muted"], size=9.5)], after=40)
    who = "出具：{}".format(org) if org else "出具：绿色工厂研判助手"
    if contact:
        who += "　联系：{}".format(contact)
    d.para([d.run("{}　生成日期：{}　政策核对至：{}".format(who, res.get("generated"), res.get("policy_checked")),
                  color=COLORS["muted"], size=9)], after=200)

    # 一、结论
    d.h1("一、结论")
    t = res["total"]
    gst = res["gates"]["status"]
    gst_cn = {"ok": "通过", "warn": "有待核实项", "veto": "存在否决项"}[gst]
    if gst == "veto" and res["gates"].get("veto_from") == "basic":
        gst_cn = "基本要求不满足"
    lines = []
    for v in res["tiers"]:
        th = "无固定分数线" if v.get("threshold") is None else "{}分".format(f1(v["threshold"]))
        lines.append("{}（{}）：{}。{}".format(v["tier"], th, v.get("verdict", ""), v.get("detail", "")))
    d.para([d.run("分数账本　", bold=True, color=GREEN),
            d.run("确定分 {}，待定 {} 分，上限 {}。门槛核查：{}。".format(
                f1(t["certain"]), f1(t["pending_weight"]), f1(t["upper"]), gst_cn))],
           shade=TINT, before=60, after=60)
    for ln in lines:
        d.para([d.run(ln)], indent=0)
    p = res.get("path")
    if p and p.get("steps"):
        d.h2("过{}线的最短路径（差{}分）".format(p["tier"], f1(p["need"])))
        rows = [["指标{} {}".format(s["id"], s["name"]), "+{}".format(f2(s["gain"])), f1(s["after"]),
                 TIMING_CN.get(s["timing"], "")] for s in p["steps"]]
        d.table(["措施对应指标", "加分", "累计", "时效"], rows, [46, 12, 12, 30], align=[None, "center", "center", None])
        if not p.get("enough"):
            d.para([d.run("以上措施全部做到仍不够，需要更长周期的改造。", color=COLORS["warn"])])
        if p.get("pending_note"):
            d.para([d.run(p["pending_note"], color=COLORS["muted"])])
    if res.get("priority"):
        d.para([d.run("优先推荐因素：", bold=True), d.run("、".join(res["priority"]))])
    if res.get("dynamic"):
        d.para([d.run(res["dynamic"], color=COLORS["warn"])])

    # 二、门槛
    d.h1("二、门槛核查")
    d.h2("近三年否决情形")
    rows, cols = [], []
    for it in res["gates"]["items"]:
        rows.append([it["label"], it["value"], GATE_CN.get(it["level"], it["level"])])
        cols.append([None, None, it["level"]])
    d.table(["情形", "企业情况", "判定"], rows, [70, 15, 15], colors=cols, align=[None, "center", "center"])
    d.h2("基本要求（GB/T 36132—2025 第4.2条）")
    rows, cols = [], []
    for it in res["gates"]["basic"]:
        lv = it["level"]
        rows.append([it["label"], it["value"], GATE_CN.get(lv, lv)])
        cols.append([None, None, "ok" if lv in ("ok", "ok_weak") else lv])
    d.table(["要求", "企业情况", "判定"], rows, [62, 19, 19], colors=cols, align=[None, "center", "center"])
    d.para([d.run("四个管理体系，标准要求的是建立、实施、保持并持续改进，没有强制认证；未认证的要备好手册、内审和管理评审记录。",
                  color=COLORS["muted"], size=9)])

    # 三、得分
    d.h1("三、五化得分与{}项明细".format(len(res["indicators"])))
    rows = [[c["cat"], f1(c["weight"]), f2(c["score"]), f2(c["upper"])] for c in res["categories"]]
    rows.append(["合计", "100", f1(t["certain"]), f1(t["upper"])])
    d.table(["一级指标", "满分", "确定得分", "上限"], rows, [40, 20, 20, 20], align=[None, "center", "center", "center"])
    rows, cols = [], []
    for it in res["indicators"]:
        if it["kind"] == "qual":
            act = "{}档".format(it.get("level")) if it.get("level") else "—"
            lead = base = "—"
        else:
            act = "{} {}".format(fmt_auto(it["actual"]), it.get("unit") or "") if it["actual"] is not None else "—"
            lead, base = fmt_auto(it["lead"]), fmt_auto(it["base"])
        st = STATUS_CN.get(it["status"], it["status"])
        sc = "{}/{}".format(f2(it["score"]) if it["score"] is not None else "—", int(it["weight"]))
        rows.append([it["id"], it["name"], act, lead, base, sc, st])
        colmap = {"full": "ok", "zero": "veto", "no_data": "warn", "no_benchmark": "warn", "unknown": "warn"}
        cols.append([None] * 6 + [colmap.get(it["status"])])
    d.table(["序号", "指标", "实际值", "引领值", "基准值", "得分", "状态"], rows, [6, 25, 20, 11, 11, 12, 15],
            colors=cols, align=["center", None, None, "center", "center", "center", "center"])
    srcs = [(it["id"], it.get("src")) for it in res["indicators"] if it.get("src")]
    if srcs:
        d.para([d.run("对标值来源：", bold=True, size=9)] +
               [d.run("指标{} {}；".format(i, s), size=9, color=COLORS["muted"]) for i, s in srcs])
    d.para([d.run("定性项（指标9、12、13）按满分、半分、零分三档估计，平台细则以填报说明为准。", size=9, color=COLORS["muted"])])

    # 四、提分
    d.h1("四、提分清单")
    rows = []
    for a in res["gaps"]:
        rows.append(["指标{}\n{}".format(a["id"], a["name"]), "+{}".format(f2(a["gain"])), a.get("need") or a.get("how"),
                     a["speed"], TIMING_CN.get(a["timing"], "")])
    if rows:
        d.table(["指标", "最多可加", "要做到什么", "周期", "时效"], rows, [17, 9, 48, 13, 13], align=[None, "center", None, None, None])
    d.para([d.run("“须在评价年内落实”的措施只改变当年数据：例如绿证要对应评价年用电，固废利用和回用水要在年内发生。", size=9, color=COLORS["muted"])])

    # 五、口径
    if res.get("warnings"):
        d.h1("五、数据口径提醒")
        for i, w in enumerate(res["warnings"], 1):
            d.para([d.run("（{}）{}".format(i, w))])

    # 六、时间
    tl = res.get("timeline") or {}
    d.h1("六、时间安排")
    for w in tl.get("windows", []):
        d.para([d.run("{} {}年度　".format(w["level"], w["year"]), bold=True),
                d.run("{}；{}；用{}年数据。{}".format(w["open"], w["close"], w["data_year"], w.get("state", "")))])
    for n in tl.get("notes", []):
        d.para([d.run(n, color=COLORS["warn"])])
    if tl.get("plan"):
        rows = [[s["by"], s["task"] + ("（已晚于建议时间）" if s.get("late") else "")] for s in tl["plan"]]
        d.table(["建议完成日期", "事项"], rows, [18, 82])
    d.para([d.run("申报窗口按近两年规律推算：省级多在5—6月，国家级多在9月下旬发通知、10月下旬前后截止。以当年当地通知为准。",
                  size=9, color=COLORS["muted"])])

    # 七、材料
    d.h1("七、需要准备的佐证材料")
    need_ids = [a["id"] for a in res["gaps"]] + [i["id"] for i in res["indicators"] if i["status"] in ("full", "partial")]
    seen, rows = set(), []
    for i in need_ids:
        if i in seen:
            continue
        seen.add(i)
        nm = next((it["name"] for it in res["indicators"] if it["id"] == i), "")
        rows.append(["指标{} {}".format(i, nm), EVIDENCE.get(i, "")])
    rows.sort(key=lambda r: (0, int(r[0].split()[0][2:])) if r[0].split()[0][2:].isdigit() else (1, r[0]))
    rows.insert(0, ["门槛与基本要求", "营业执照；近三年信用记录截图（信用中国、国家企业信用信息公示系统）；四体系证书或运行记录；绿色低碳中长期规划和年度目标文件；排污许可证"])
    d.table(["对应项", "材料"], rows, [24, 76])

    # 八、说明
    d.h1("八、说明")
    for s in ["本报告依据 GB/T 36132—2025《绿色工厂评价通则》、工信部年度绿色工厂评价要求及公开政策推算，不是主管部门的评审结论。",
              "重点行业以管理平台上的行业评价要求为准，其指标、对标值可能与通则不同。",
              "对标值决定得分，来源须可追溯；没有可靠来源的指标宁可标为待定，也不要估一个数凑分。",
              "申报数据必须真实。发现数据或材料造假的，会被移出名单，并三年内不得再次申报。"]:
        d.para([d.run(s, size=9.5)])
    return d


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="生成绿色工厂研判 Word 报告")
    ap.add_argument("result", help="gf_engine.py 输出的结果 JSON")
    ap.add_argument("--out", default="绿色工厂研判报告.docx")
    ap.add_argument("--org", help="出具单位（可选）")
    ap.add_argument("--contact", help="联系方式（可选）")
    a = ap.parse_args(argv)
    with io.open(a.result, "r", encoding="utf-8-sig") as f:
        res = json.load(f)
    d = build(res, a.org, a.contact)
    d.save(a.out, "绿色工厂研判报告 - " + str((res.get("meta") or {}).get("name") or ""))
    print("report written: " + os.path.abspath(a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
