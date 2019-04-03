import os
import io
import re
import json
import html
import pandas as pd
import bs4
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from IPython.display import Markdown, display

META_FIELD_PATTERN = "[meta]"
PROJECT_NAME = "collective-actions-in-tech"
HEADER_ROW_ID = "header"
FIELDS = [
    "date",
    "source",
    "company",
    "action",
    "employment_type",
    "union_affiliation",
    "worker_count",
    "description",
]
MD_PATH = os.path.realpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "README.md")
)

MarkdownData = str
MarkdownDocument = str


class MarkdownDataIDNotFound(Exception):
    pass


class DateColumnNotFound(Exception):
    pass


class MarkdownDataNotFound(Exception):
    pass


class MultipleMarkdownDataFound(Exception):
    pass


class MarkdownDataIsMalformed(Exception):
    pass


def _serialize_meta_field(key: str) -> str:
    return f"{META_FIELD_PATTERN}{key}"


def _deserialize_meta_field(key: str) -> str:
    return key[len(META_FIELD_PATTERN) :]


def _decode_df_to_md_fields(td: bs4.element.Tag, col: str, val: str) -> bs4.element.Tag:
    """ Converts df fields to bs4 Tag / html format format. """
    td.string = val
    if col == "source":
        td = BeautifulSoup(html.unescape(str(td)), "html.parser")
    elif col == "date":
        td.string = str(datetime.strptime(td.string, "%Y-%m-%d %H:%M:%S").date())
    return td


def _md_data_to_df(md_data: MarkdownData) -> pd.DataFrame:
    """ Converts a markdown data to a DataFrame. """
    assert _is_valid_md_data(md_data)
    actions = []
    soup = BeautifulSoup(md_data, "html.parser")
    tables = soup.div.find_all("table")
    for table in tables:
        action = {}

        # add table attributes
        for key, val in table.attrs.items():
            if key != "class":
                action[_serialize_meta_field(key)] = val

        # add each tr in the table
        trs = table.find_all("tr")
        for i, tr in enumerate(trs):
            td_key = tr.find("td", class_="field-key")
            td_val = tr.find("td", class_="field-value")
            val = "".join(str(e) for e in td_val.contents).strip()
            key = "".join(str(e) for e in td_key.contents).strip()
            action[key] = val

        # if one of the FIELDS are missing from md_data, add it in as None
        for field in list(set(FIELDS) - set(action.keys())):
            action[field] = None

        if action:
            actions.append(action)

    df = pd.read_json(json.dumps(actions), orient="list")
    col_order = FIELDS + list(set(df.columns) - set(FIELDS))
    return df[col_order]


def _df_to_md_data(df: pd.DataFrame, project_id: str) -> MarkdownData:
    """ Converts a DataFrame to a markdown data. """
    soup = BeautifulSoup(f"<div id={project_id}></div>", "html.parser")
    cols = df.columns

    for index, row in df.iterrows():
        table = soup.new_tag("table")
        soup.div.append(table)
        for col in cols:
            if col.startswith(META_FIELD_PATTERN):
                table[_deserialize_meta_field(col)] = row[col]
            else:
                tr = soup.new_tag("tr")
                td_key = soup.new_tag("td", attrs={"class": "field-key"})
                td_val = soup.new_tag("td", attrs={"class": "field-value"})
                td_key.string = col
                td_val = _decode_df_to_md_fields(td_val, col, str(row[col]))
                if row[col]:
                    tr.append(td_key)
                    tr.append(td_val)
                    table.append(tr)

    return soup.prettify()


def _get_data_from_md_document(project_id: str, doc: MarkdownDocument) -> MarkdownData:
    """ Extract table from a markdown document.

    This function will not extract any table from the document. Instead, it looks specifically for a
    tables in a div expressed in html with the id {table_id}.

    If multiple such tables are found, or none are found at all, it will raise
    an error.

    Args:
        project_id: the id to look for
        doc: the markdown document to parse

    Raise:
        MarkdownDataNotFound: if no such table is found
        MultipleMarkdownDataFound: if multiple tables are found
        MarkdownDataIsMalformed: if table is malformed

    Returns:
        The parsed Markdown table
    """
    md_data = re.findall(fr"<div[\s\S]+{project_id}+[\s\S]+<\/div>", doc)

    if not md_data:
        raise MarkdownDataNotFound
    if len(md_data) > 1:
        raise MultipleMarkdownDataFound
    assert len(md_data) == 1

    md_data = md_data[0]

    if not _is_valid_md_data(md_data):
        raise MarkdownDataIsMalformed

    return md_data


def _is_valid_md_data(md_data: MarkdownData) -> bool:
    """ Checks if markdown table is malformed.

    Checks:
    - the number of td elements inside each tr element equals or is less than len(FIELDS)
    - fields are correctly labeled

    Args:
        md_data: the markdown data div
    """
    assert md_data.startswith("<div")
    assert md_data.endswith("</div>")
    soup = BeautifulSoup(md_data, "html.parser")
    tables = soup.div.find_all("table")
    for table in tables:
        trs = table.find_all("tr")
        if len(trs) > len(FIELDS):
            return False
        for tr in trs:
            td = tr.find("td", class_="field-key")
            if td and td.string.strip() not in FIELDS:
                return False
    return True


def _replace_md_data(
    doc: MarkdownDocument, project_id: str, md_data: MarkdownData
) -> MarkdownDocument:
    """ Replace the table in {doc} with {md_data}. """
    assert _is_valid_md_data(md_data)
    new_md_data = BeautifulSoup(md_data, "html.parser")
    soup = BeautifulSoup(doc, "html.parser")
    data = soup.find("div", id=project_id)
    if not data:
        raise MarkdownDataNotFound
    old_soup = data.replace_with(new_md_data)
    return soup.prettify()


def _sort_df(df: pd.DataFrame) -> pd.DataFrame:
    """ Sort dataframe by date.

    Date is not used as index as multiple actions may happen on one date.

    Args:
        df: The dataframe to sort

    Returns:
        The sorted Dataframe
    """
    if "date" not in df.columns:
        raise DateColumnNotFound
    df["date"] = pd.to_datetime(df["date"], unit="D")
    df.sort_values(by=["date"], ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def save_md_data_to_csv(
    input_fp: Path, output_fp: Path, project_id: str = PROJECT_NAME
) -> None:
    """ Saves table in markdown document as csv.

    Saves a cleaned-up version of the markdown data found in the passed in markdown
    file as a csv.

    Args:
        input_fp: input file path
        project_id: the id of the element to search for when finding the
        markdown data
        output_fp: the output file path
    """
    md_document = input_fp.read_text()
    data = _get_data_from_md_document(project_id, md_document)
    df = _md_data_to_df(data)
    df = _sort_df(df)
    df.to_csv(output_fp)


def get_df_from_md_document(
    input_fp: Path, project_id: str = PROJECT_NAME
) -> pd.DataFrame:
    """ Gets df from table in markdown document.

    Returns a cleaned-up version of the markdown data found in the passed in markdown
    file as a dataframe.

    Args:
        input_fp: input file path
        project_id: the id of the element to search for when finding the
        markdown data
    """
    md_document = input_fp.read_text()
    data = _get_data_from_md_document(project_id, md_document)
    df = _md_data_to_df(data)
    df = _sort_df(df)
    return df


def clean_md_document(input_fp: Path, project_id: str = PROJECT_NAME) -> None:
    """ Cleans the table from the markdown document.

    Replaces the markdown data in the passed in markdown file with a cleaned-up version
    of the data.

    Args:
        input_fp: input file path
        project_id: the id of the element to search for when finding the
        markdown data
    """
    md_document = input_fp.read_text()
    data = _get_data_from_md_document(project_id, md_document)
    df = _md_data_to_df(data)
    df = _sort_df(df)
    md_data = _df_to_md_data(df, project_id)
    updated_md_document = _replace_md_data(md_document, project_id, md_data)
    input_fp.write_text(updated_md_document)