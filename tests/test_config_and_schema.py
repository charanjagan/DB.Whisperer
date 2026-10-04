"""Saved settings, dialect lookup, table picking, and the summary prompt's row notes."""

import json

import pandas as pd
import pytest

from nl2sql.app_config import AppConfig, load_config, save_config
from nl2sql.dialects import DEFAULT_DIALECT, DIALECTS, get_dialect
from nl2sql.schema_introspection import _lexical_matches, _match_tables
from nl2sql.summary_generator import format_result_for_prompt

# --- app config --------------------------------------------------------------


def test_password_never_written(tmp_path):
    path = tmp_path / "config.json"
    save_config(AppConfig(username="sa", password="hunter2"), path)
    assert "hunter2" not in path.read_text(encoding="utf-8")
    assert "password" not in json.loads(path.read_text(encoding="utf-8"))


def test_round_trip(tmp_path):
    path = tmp_path / "config.json"
    original = AppConfig(server="db01", database="AdventureWorks", dialect="mysql")
    save_config(original, path)
    loaded = load_config(path)
    assert (loaded.server, loaded.database, loaded.dialect) == ("db01", "AdventureWorks", "mysql")


def test_from_dict_ignores_junk_and_bad_dialect():
    config = AppConfig.from_dict({"server": "x", "nonsense": 1, "dialect": "oracle", "password": "p"})
    assert config.server == "x"
    assert config.dialect == DEFAULT_DIALECT
    assert config.password == ""  # never read back from the file


@pytest.mark.parametrize("content", ["{not json", "[]", "\"x\"", "5", "null", ""])
def test_corrupt_config_falls_back_to_defaults(tmp_path, content):
    path = tmp_path / "config.json"
    path.write_text(content, encoding="utf-8")
    assert load_config(path) == AppConfig()


def test_missing_config_falls_back_to_defaults(tmp_path):
    assert load_config(tmp_path / "absent.json") == AppConfig()


# --- dialects ----------------------------------------------------------------


@pytest.mark.parametrize("key", list(DIALECTS))
def test_known_dialects(key):
    assert get_dialect(key).key == key


def test_unknown_dialect_raises_rather_than_defaulting():
    with pytest.raises(ValueError):
        get_dialect("oracle")


# --- table selection ---------------------------------------------------------

TABLES = [
    "Production.Product",
    "Production.ProductCategory",
    "Production.ProductSubcategory",
    "Sales.SalesOrderHeader",
]


def test_match_tables_accepts_any_reply_format():
    reply = "- Production.ProductCategory\n- SalesOrderHeader\n* productsubcategory"
    assert _match_tables(reply, TABLES) == [
        "Production.ProductCategory",
        "Production.ProductSubcategory",
        "Sales.SalesOrderHeader",
    ]


def test_match_tables_cannot_invent_a_table():
    assert _match_tables("dbo.Invoices, Customers", TABLES) == []


def test_lexical_match_is_whole_name_and_plural_tolerant():
    # "products" hits Product but not every Product* table.
    assert _lexical_matches("how many products are there", TABLES) == ["Production.Product"]


# --- summary prompt ----------------------------------------------------------


def test_summary_note_states_total_rows():
    df = pd.DataFrame({"n": range(50)})
    assert "of 50 rows" in format_result_for_prompt(df)


def test_summary_note_does_not_claim_capped_total():
    df = pd.DataFrame({"n": range(50)})
    df.attrs["truncated"] = True
    text = format_result_for_prompt(df)
    assert "more than 50 rows" in text
    assert "of 50 rows" not in text


def test_summary_of_empty_result():
    assert format_result_for_prompt(pd.DataFrame()) == "(no rows)"
