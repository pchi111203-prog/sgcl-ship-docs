"""Build the blank NSW template used by the export from a filled NSW workbook.

    python tools/make_clean_template.py <filled_or_new_template.xlsx> templates/TemplateNSW.xlsx

Every data cell (header values, list rows, helper rows, sample rows) is removed; labels,
styles, dropdowns, comments, lookup formulas and the 'Declaration list' code sheet are kept.
Unused shared strings are dropped so no voyage data remains inside the file.
Run it again whenever SGCL receives a newer NSW template, then run the tests.
"""
import sys

sys.path.insert(0, __file__.rsplit("/tools/", 1)[0])
from app.xlsxpatch import Book  # noqa: E402

# clear = remove values only (lookup formulas kept); wipe = remove values AND helper/broken formulas
REGIONS = {
    "Notice ship to port": {"clear": ["B3:B4", "B6:B32", "A36:C41", "A44:G46"]},
    "ConfirmationOfArrival": {"clear": ["B3:B4", "B6:B10", "A13:F18"]},
    "Goods Declaration": {"clear": ["B3:B4", "B6:B7", "A10:W14"]},
    "List of House bill of lading": {"clear": ["A4:X4", "B7:G7", "A12:X12", "B15:G17"]},
    "General Declaration": {"clear": ["B3:B4", "B6:B34", "A38:C43", "A46:G51"]},
    "Crew list": {"clear": ["B3:B4", "B6:B8", "G8"], "wipe": ["A11:P48"]},
    "Crew's Effects Declaration": {"clear": ["B3:B4", "B6:B8", "A11:D29"]},
    "Ship's store declaration": {"clear": ["B3:B4", "B6:B10", "A13:H85"]},
    "Cargo manifest": {"clear": ["B3:B4", "B6:B9", "A12:K15"]},
    "Passenger list": {"wipe": ["B3:B5"], "clear": ["B6:B8", "A11:M11"]},
    "Dangerous goods manifest": {"clear": ["B3:B4", "B6:B11", "A14:P14"]},
    "Declaration For Ship Security": {"clear": ["B3:B4", "B6:B22", "D17"], "wipe": ["A25:E34", "C36:D45"]},
    "Declaration For Plant": {"clear": ["B3:B4", "B6:B15"]},
    "Declaration For Animal": {"clear": ["B3:B4", "B6:B12"]},
    "Declaration For Health": {"clear": ["B3:B4", "B6:B22", "B25:B42", "A46:G49", "A52:N54"]},
    "Empty Container": {"wipe": ["B3:B5"], "clear": ["A8:D11"]},
    "Arms And Explosive Materials": {"clear": ["A8", "C8:H8"]},
    "Declaration of Stowaway": {"clear": ["B4:B5", "B7:B10", "A13:AS13"]},
    "Add User": {"clear": ["A5:Q6"]},
    "InlandAttachmentList": {"clear": ["A5:A7", "C5:H7"]},
}
# document-function cells that were broken formulas in the source get the template default back
DEFAULT_VALUES = {("Passenger list", "B5"): "CN01", ("Empty Container", "B5"): "CN01"}


def main(src, dst):
    book = Book(src)
    for name in book.sheet_names:
        spec = REGIONS.get(name)
        if not spec:
            continue
        sh = book.sheet(name)
        for rng in spec.get("wipe", []):
            sh.wipe_range(rng)
        for rng in spec.get("clear", []):
            sh.clear_range(rng)
    for (name, ref), v in DEFAULT_VALUES.items():
        if name in book.sheet_names:
            book.sheet(name).set(ref, v)
    book.compact_shared_strings()
    book.save(dst)
    print(f"clean template written: {dst} ({len(book.sheet_names)} sheets)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
