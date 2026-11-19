"""Minimal, structure-preserving XLSX editor working directly on the OOXML parts.

Why not openpyxl for writing: the NSW template contains x14 (extension) data validations
(dropdowns that point to the 'Declaration list' sheet), cell comments, VML drawings,
printer settings and 9 external links. openpyxl silently drops x14 validations, so the
exported file would lose its dropdowns. Here only <sheetData> cells (and DV ranges when a
list grows) are touched; every other part of the package is copied byte-for-byte.
"""
import copy
import re
import zipfile

from lxml import etree

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NSR = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NSREL = "http://schemas.openxmlformats.org/package/2006/relationships"
NSCT = "http://schemas.openxmlformats.org/package/2006/content-types"
NSX14 = "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main"
NSXM = "http://schemas.microsoft.com/office/excel/2006/main"
Q = lambda t: f"{{{NS}}}{t}"


def col2num(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def num2col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def split_ref(ref):
    m = re.fullmatch(r"\$?([A-Z]+)\$?(\d+)", ref)
    return m.group(1), int(m.group(2))


class Sheet:
    def __init__(self, book, name, path, xml):
        self.book, self.name, self.path = book, name, path
        self.tree = etree.fromstring(xml)
        self.sheetData = self.tree.find(Q("sheetData"))
        self.dirty = False

    # ---------------------------------------------------------------- rows/cells
    def _rows(self):
        return {int(r.get("r")): r for r in self.sheetData.findall(Q("row"))}

    def _row(self, n, create=True):
        rows = self._rows()
        if n in rows:
            return rows[n]
        if not create:
            return None
        el = etree.Element(Q("row"), r=str(n))
        after = [k for k in rows if k < n]
        if after:
            rows[max(after)].addnext(el)
        else:
            self.sheetData.insert(0, el)
        return el

    def cell(self, ref, create=False):
        col, rn = split_ref(ref)
        row = self._row(rn, create)
        if row is None:
            return None
        for c in row.findall(Q("c")):
            if c.get("r") == ref:
                return c
        if not create:
            return None
        el = etree.Element(Q("c"), r=ref)
        # inherit column style from the nearest styled cell above (keeps borders/fonts)
        style = self._style_above(col, rn)
        if style:
            el.set("s", style)
        cn = col2num(col)
        prev = None
        for c in row.findall(Q("c")):
            if col2num(split_ref(c.get("r"))[0]) < cn:
                prev = c
        if prev is not None:
            prev.addnext(el)
        else:
            row.insert(0, el)
        return el

    def _style_above(self, col, rn):
        for r in range(rn - 1, 0, -1):
            c = self.cell(f"{col}{r}")
            if c is not None and c.get("s"):
                return c.get("s")
        return None

    def value(self, ref):
        c = self.cell(ref)
        if c is None:
            return None
        return self.book.cell_text(c)

    def formula(self, ref):
        c = self.cell(ref)
        if c is None:
            return None
        f = c.find(Q("f"))
        return f.text if f is not None else None

    def set(self, ref, value):
        """Write a text value (inline string). Formula cells are never overwritten."""
        c = self.cell(ref, create=value not in (None, ""))
        if c is None:
            return False
        if c.find(Q("f")) is not None:
            raise ValueError(f"{self.name}!{ref} chứa công thức - không ghi đè.")
        for child in list(c):
            c.remove(child)
        c.attrib.pop("t", None)
        if value in (None, ""):
            self.dirty = True
            return True
        c.set("t", "inlineStr")
        is_ = etree.SubElement(c, Q("is"))
        t = etree.SubElement(is_, Q("t"))
        t.text = str(value)
        if str(value) != str(value).strip():
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        self.dirty = True
        return True

    def clear(self, ref):
        c = self.cell(ref)
        if c is None or c.find(Q("f")) is not None:
            return False
        return self.set(ref, None)

    def clear_range(self, rng):
        a, b = rng.split(":") if ":" in rng else (rng, rng)
        ca, ra = split_ref(a)
        cb, rb = split_ref(b)
        for r in range(ra, rb + 1):
            for cn in range(col2num(ca), col2num(cb) + 1):
                self.clear(f"{num2col(cn)}{r}")

    # ---------------------------------------------------------------- repeating rows
    def regenerate_rows(self, template_row, first_row, old_last_row, count, max_row=None, block=None):
        """Replace rows first_row..old_last_row with `count` copies of template_row
        (styles, heights and formulas kept; formula references to the template row are moved
        to the new row; values cleared).  `block` = (start, height) repeats a multi-row block."""
        rows = self._rows()
        if block:
            bstart, bheight = block
            tpl = [copy.deepcopy(rows[r]) if r in rows else etree.Element(Q("row"), r=str(r)) for r in range(bstart, bstart + bheight)]
            new_count_rows = bheight * count
        else:
            tpl = [copy.deepcopy(rows[template_row])]
            bstart, bheight = template_row, 1
            new_count_rows = count
        last_needed = first_row + new_count_rows - 1
        limit = max_row or 1048576
        if last_needed > limit:
            raise ValueError(f"Sheet '{self.name}': cần {new_count_rows} dòng nhưng vùng dữ liệu của mẫu chỉ cho phép đến dòng {limit}.")
        for r, el in rows.items():
            if old_last_row < r <= last_needed and any(c.find(Q("v")) is not None or c.find(Q("f")) is not None or c.find(Q("is")) is not None
                                                      for c in el.findall(Q("c"))):
                raise ValueError(f"Sheet '{self.name}': dòng {r} của mẫu có nội dung, không thể mở rộng vùng dữ liệu.")
        anchor = None
        for r, el in sorted(rows.items()):
            if first_row <= r <= max(old_last_row, last_needed):
                if anchor is None:
                    anchor = el.getprevious()
                self.sheetData.remove(el)
        insert_after = anchor
        created = []
        for i in range(count):
            for j, t in enumerate(tpl):
                src_r = bstart + j
                new_r = first_row + i * bheight + j
                el = copy.deepcopy(t)
                el.set("r", str(new_r))
                for c in el.findall(Q("c")):
                    col, _ = split_ref(c.get("r"))
                    c.set("r", f"{col}{new_r}")
                    f = c.find(Q("f"))
                    for child in list(c):
                        if child is not f:
                            c.remove(child)
                    if f is not None:
                        f.text = _shift_formula(f.text, src_r, new_r, bstart, bstart + bheight - 1, first_row + i * bheight)
                        c.attrib.pop("t", None)
                    else:
                        c.attrib.pop("t", None)
                if insert_after is None:
                    self.sheetData.insert(0, el)
                else:
                    insert_after.addnext(el)
                insert_after = el
                created.append(new_r)
        self.dirty = True
        if count:
            self._extend_validations(bstart, bstart + bheight - 1, first_row, first_row + new_count_rows - 1, bheight)
        return created

    def _extend_validations(self, t1, t2, n1, n2, bheight):
        """Grow data-validation ranges that cover the template rows so new rows keep their dropdowns."""
        def fix(sqref):
            out = []
            for tok in sqref.split():
                a, b = (tok.split(":") + [tok])[:2]
                ca, ra = split_ref(a)
                cb, rb = split_ref(b)
                if ra <= t2 and rb >= t1:
                    out.append(f"{ca}{min(ra, n1)}:{cb}{max(rb, n2)}")
                else:
                    out.append(tok)
            return " ".join(out)
        for dv in self.tree.iter(Q("dataValidation")):
            dv.set("sqref", fix(dv.get("sqref")))
        for sq in self.tree.iter(f"{{{NSXM}}}sqref"):
            sq.text = fix(sq.text)

    def used_rows(self):
        return sorted(self._rows())

    def update_dimension(self):
        rows = self._rows()
        dim = self.tree.find(Q("dimension"))
        if dim is None or not rows:
            return
        maxc = 1
        for r in rows.values():
            for c in r.findall(Q("c")):
                maxc = max(maxc, col2num(split_ref(c.get("r"))[0]))
        dim.set("ref", f"A1:{num2col(maxc)}{max(rows)}")

    def xml(self):
        self.update_dimension()
        return etree.tostring(self.tree, xml_declaration=True, encoding="UTF-8", standalone=True)


_REF = re.compile(r"((?:'[^']+'|[A-Za-z0-9_\[\]\.]+)!)?(\$?)([A-Z]{1,3})(\$?)(\d+)(?::(\$?)([A-Z]{1,3})(\$?)(\d+))?(?![\w(])")


def _shift_formula(text, src_r, new_r, b1, b2, new_b1):
    """Move relative references that point inside the template block to the new block.
    Sheet-qualified references (e.g. 'Declaration list'!G3:H88) and absolute rows are kept."""
    def mv(dollar_row, row):
        r = int(row)
        if not dollar_row and b1 <= r <= b2:
            return str(new_b1 + (r - b1))
        return row

    def rep(m):
        if m.group(1):
            return m.group(0)
        out = f"{m.group(2)}{m.group(3)}{m.group(4)}{mv(m.group(4), m.group(5))}"
        if m.group(7):
            out += f":{m.group(6)}{m.group(7)}{m.group(8)}{mv(m.group(8), m.group(9))}"
        return out
    # do not touch text inside string literals
    parts = re.split(r'("[^"]*")', text)
    return "".join(p if p.startswith('"') else _REF.sub(rep, p) for p in parts)


class Book:
    def __init__(self, path):
        self.path = path
        with zipfile.ZipFile(path) as z:
            self.parts = {n: z.read(n) for n in z.namelist()}
            self.order = z.namelist()
        self.wb = etree.fromstring(self.parts["xl/workbook.xml"])
        rels = etree.fromstring(self.parts["xl/_rels/workbook.xml.rels"])
        rmap = {r.get("Id"): r.get("Target") for r in rels}
        self.sheet_paths = {}
        self.sheet_names = []
        self.sheet_state = {}
        for s in self.wb.find(Q("sheets")):
            target = rmap[s.get(f"{{{NSR}}}id")]
            self.sheet_paths[s.get("name")] = "xl/" + target.lstrip("/").replace("xl/", "") if not target.startswith("/") else target.lstrip("/")
            self.sheet_names.append(s.get("name"))
            self.sheet_state[s.get("name")] = s.get("state", "visible")
        self.shared = []
        if "xl/sharedStrings.xml" in self.parts:
            sst = etree.fromstring(self.parts["xl/sharedStrings.xml"])
            for si in sst.findall(Q("si")):
                self.shared.append("".join(t.text or "" for t in si.iter(Q("t"))))
        self._sheets = {}

    def sheet(self, name):
        if name not in self._sheets:
            p = self.sheet_paths[name]
            self._sheets[name] = Sheet(self, name, p, self.parts[p])
        return self._sheets[name]

    def cell_text(self, c):
        t = c.get("t")
        if t == "inlineStr":
            return "".join(x.text or "" for x in c.iter(Q("t")))
        v = c.find(Q("v"))
        if v is None:
            return None
        if t == "s":
            return self.shared[int(v.text)]
        return v.text

    def save(self, out_path):
        # formulas were added/removed -> drop calcChain (Excel rebuilds it) and force recalculation
        drop = {"xl/calcChain.xml"}
        ct = etree.fromstring(self.parts["[Content_Types].xml"])
        for o in list(ct):
            if o.get("PartName") == "/xl/calcChain.xml":
                ct.remove(o)
        rels = etree.fromstring(self.parts["xl/_rels/workbook.xml.rels"])
        for r in list(rels):
            if r.get("Target", "").endswith("calcChain.xml"):
                rels.remove(r)
        calc = self.wb.find(Q("calcPr"))
        if calc is not None:
            calc.set("fullCalcOnLoad", "1")
        out = dict(self.parts)
        out["[Content_Types].xml"] = etree.tostring(ct, xml_declaration=True, encoding="UTF-8", standalone=True)
        out["xl/_rels/workbook.xml.rels"] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
        out["xl/workbook.xml"] = etree.tostring(self.wb, xml_declaration=True, encoding="UTF-8", standalone=True)
        for s in self._sheets.values():
            if s.dirty:
                out[s.path] = s.xml()
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            for n in self.order:
                if n in drop:
                    continue
                z.writestr(n, out[n])
