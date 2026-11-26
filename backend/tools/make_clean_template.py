"""Build the blank NSW template used by the export from a filled NSW workbook.

    python tools/make_clean_template.py <filled_or_new_template.xlsx> templates/TemplateNSW.xlsx

Templates uploaded in the admin workspace are cleaned the same way automatically (app/template_clean.py).
"""
import sys

sys.path.insert(0, __file__.rsplit("/tools/", 1)[0])
from app.template_clean import clean_template  # noqa: E402

if __name__ == "__main__":
    n = clean_template(sys.argv[1], sys.argv[2])
    print(f"clean template written: {sys.argv[2]} ({n} sheets)")
