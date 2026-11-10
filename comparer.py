"""Quatre facons de repondre a la meme question, mesurees.

La question : combien d'etablissements OUVERTS par departement ?
Les quatre approches donnent le meme resultat. Elles ne coutent pas la meme chose.
"""

from pathlib import Path

D = Path("donnees_tp4")
CSV = D / "etablissements.csv"
PARQUET = D / "zstd.parquet"

COLONNES = ["libelle_departement", "etat"]


def pandas_naif() -> dict[str, int]:
    """Tout charger, puis boucler ligne par ligne. Ce que fait un notebook."""
    import pandas as pd

    tableau = pd.read_csv(CSV)
    comptes: dict[str, int] = {}
    for i in range(len(tableau)):
        ligne = tableau.iloc[i]
        if ligne["etat"] == "OUVERT":
            dep = ligne["libelle_departement"]
            comptes[dep] = comptes.get(dep, 0) + 1
    return comptes


def pandas_apply() -> dict[str, int]:
    """Tout charger, filtrer avec apply. Moins naïf, toujours ligne par ligne."""
    import pandas as pd

    tableau = pd.read_csv(CSV)
    ouverts = tableau[tableau.apply(lambda r: r["etat"] == "OUVERT", axis=1)]
    comptes = ouverts["libelle_departement"].value_counts()
    return {str(departement): int(nombre) for departement, nombre in comptes.items()}


def pandas_optimise() -> dict[str, int]:
    """Ne lire que les colonnes utiles, typer en categorie, vectoriser."""
    import pandas as pd

    tableau = pd.read_csv(
        CSV,
        usecols=COLONNES,
        dtype={"libelle_departement": "category", "etat": "category"},
    )
    ouverts = tableau[tableau["etat"] == "OUVERT"]
    comptes = ouverts["libelle_departement"].value_counts()
    return {str(departement): int(nombre) for departement, nombre in comptes.items()}


def polars_parquet() -> dict[str, int]:
    """Parquet + evaluation differee : Polars ne lit que ce dont il a besoin."""
    import polars as pl

    resultat = (
        pl.scan_parquet(PARQUET)
        .filter(pl.col("etat") == "OUVERT")
        .group_by("libelle_departement")
        .len()
        .collect()
    )
    return dict(zip(resultat["libelle_departement"], resultat["len"], strict=True))


APPROCHES = {
    "pandas naïf (boucle iloc)": pandas_naif,
    "pandas apply": pandas_apply,
    "pandas optimisé": pandas_optimise,
    "Polars lazy sur Parquet": polars_parquet,
}
