"""Filename parsing, using real file names observed on pbs.gov.pk."""

import datetime as dt

import pytest

from kitchen_inflation.discover import classify, week_hint

D = dt.date


@pytest.mark.parametrize(
    "name, uploaded, expected, rule",
    [
        ("SPI_AnnexUSCP_06072023.pdf", D(2023, 7, 7), D(2023, 7, 6), "ddmmyyyy"),
        ("SPI-AnnexUSCP12102023.pdf", None, D(2023, 10, 12), "ddmmyyyy"),
        # "%20" left behind as a literal "20": "ANNEX 26 USCP 02.05.2024"
        ("ANNEX202620USCP2002.05.2024.pdf", None, D(2024, 5, 2), "dd.mm.yyyy"),
        ("SPI20Executive20Summary202620Report_2018.07.2024.pdf", None, D(2024, 7, 18), "dd.mm.yyyy"),
        ("SPI20Executive20Sumary202620SPI20Report2020.06.2024.pdf", None, D(2024, 6, 20), "dd.mm.yyyy"),
        ("SPI20Annexture_13.06.2024202620USCP-merged.pdf", None, D(2024, 6, 13), "dd.mm.yyyy"),
        ("SPI_AnnexUSCP_070923.pdf", None, D(2023, 9, 7), "ddmmyy"),
        ("Annex-12-06-2025.pdf", None, D(2025, 6, 12), "dd.mm.yyyy"),
        ("3.-Annexure-22-05-2025.pdf", None, D(2025, 5, 22), "dd.mm.yyyy"),
        ("Annex-09.10.2025_0.xlsx", None, D(2025, 10, 9), "dd.mm.yyyy"),
        ("Annex_04-12-2025.pdf", None, D(2025, 12, 4), "dd.mm.yyyy"),
        # No year: inferred from the upload date.
        ("Annex_05.11.pdf", D(2026, 11, 6), D(2026, 11, 5), "dd.mm+upload_year"),
        # Year boundary: a 31 Dec report uploaded on 1 Jan.
        ("Annex_31.12.pdf", D(2026, 1, 1), D(2025, 12, 31), "dd.mm+upload_year"),
        ("Annex.pdf", D(2024, 1, 5), None, "none"),
    ],
)
def test_week_hint(name, uploaded, expected, rule):
    assert week_hint(name, uploaded) == (expected, rule)


@pytest.mark.parametrize(
    "name, kind",
    [
        ("SPI_AnexUSCP_10082023.pdf", "annex"),
        ("3.-Annexure-22-05-2025.pdf", "annex"),
        ("SPI_Executive-SumaryReport_06072023.pdf", "summary"),
        ("Executive-Summary-SPI-Report_29.10.2026.pdf", "summary"),
        ("3.-SPI-Report-29.10.2026.xlsx", "report_xlsx"),
        ("SPI-Monthly-Prices-Annex-10.xlsx", "monthly"),
    ],
)
def test_classify(name, kind):
    assert classify(name) == kind
