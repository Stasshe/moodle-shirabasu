from typing import Any
import urllib.request

from bs4 import BeautifulSoup


def fetch_page(url: str, render_with_selenium: bool = False, timeout: int = 15) -> str | None:
    if not render_with_selenium:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset(failobj="utf-8")
                return resp.read().decode(charset)
        except Exception:
            return None

    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.common.exceptions import TimeoutException
    except Exception:
        return None

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=opts)
    try:
        driver.get(url)
        try:
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            pass
        return driver.page_source
    finally:
        driver.quit()


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _extract_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def page_looks_rendered(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return bool(
        soup.select_one('td[data-label]')
        or soup.select_one('.slds-form-element__label')
        or soup.select_one('table.slds-table')
    )


def _normalize_text(value: str) -> str:
    return "\n".join(_extract_lines(value.replace("\xa0", " ")))


def _extract_field_blocks(soup: BeautifulSoup) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for block in soup.select('c-form-element-static-cmp, .slds-form-element_readonly'):
        label_el = block.select_one('.slds-form-element__label')
        value_el = block.select_one('.slds-form-element__static')
        if not label_el or not value_el:
            continue
        label = _normalize_text(label_el.get_text(" ", strip=True))
        value = _normalize_text(value_el.get_text("\n", strip=True))
        if label:
            fields.append({"label": label, "value": value})
    return fields


def _extract_tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    section_label: str | None = None

    for node in soup.find_all(True):
        if node.name == "div" and "slds-form-element" in node.get("class", []):
            label_el = node.select_one('.slds-form-element__label')
            if label_el:
                section_label = _normalize_text(label_el.get_text(" ", strip=True))

        if node.name != "table":
            continue

        headers: list[str] = []
        thead = node.find("thead")
        if thead:
            header_rows = thead.find_all("tr")
            if header_rows:
                headers = [
                    _normalize_text(cell.get_text(" ", strip=True))
                    for cell in header_rows[0].find_all(["th", "td"])
                ]

        rows: list[list[str]] = []
        tbody = node.find("tbody") or node
        for tr in tbody.find_all("tr", recursive=False):
            cells = [
                _normalize_text(cell.get_text("\n", strip=True))
                for cell in tr.find_all(["th", "td"], recursive=False)
            ]
            if cells:
                rows.append(cells)

        if not rows:
            for tr in node.find_all("tr"):
                cells = [
                    _normalize_text(cell.get_text("\n", strip=True))
                    for cell in tr.find_all(["th", "td"], recursive=False)
                ]
                if cells:
                    rows.append(cells)

        if headers and rows:
            rows_with_headers = [
                {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
                for row in rows
            ]
        else:
            rows_with_headers = rows

        tables.append({
            "section": section_label,
            "headers": headers,
            "rows": rows_with_headers,
        })

    return tables


def _extract_teacher_values(fields: list[dict[str, str]], tables: list[dict[str, Any]]) -> list[str]:
    teachers: list[str] = []
    teacher_labels = {"全担当教員", "担当教員", "教員"}

    for field in fields:
        if field["label"] in teacher_labels and field["value"]:
            teachers.extend(_extract_lines(field["value"]))

    for table in tables:
        headers = table.get("headers") or []
        rows = table.get("rows") or []
        for row in rows:
            if isinstance(row, dict):
                for header, value in row.items():
                    if header in teacher_labels and value:
                        teachers.extend(_extract_lines(value))
            elif headers:
                for index, header in enumerate(headers):
                    if header in teacher_labels and index < len(row) and row[index]:
                        teachers.extend(_extract_lines(row[index]))

    return _unique([teacher for teacher in teachers if teacher])


def parse_syllabus(html: str) -> dict[str, Any]:
    """HTML から担当教員、表、リスト等の情報を抜き取る。"""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Any] = {}

    title_tag = soup.find(["h1", "h2"])
    out["title"] = title_tag.get_text(strip=True) if title_tag else None

    fields = _extract_field_blocks(soup)
    tables = _extract_tables(soup)
    teachers = _extract_teacher_values(fields, tables)

    out["fields"] = fields
    out["teachers"] = teachers
    out["tables"] = tables

    lists: list[list[str]] = []
    for ul in soup.find_all(["ul", "ol"]):
        items = [li.get_text(strip=True) for li in ul.find_all("li")]
        if items:
            lists.append(items)
    out["lists"] = lists

    return out
