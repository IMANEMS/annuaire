"""Convertit le CSV en Parquet, en trois variantes, et compare les tailles.

C'est la premiere mesure de la seance : pourquoi un format colonne pese moins, et
ce que le partitionnement change.
"""

import errno
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

D = Path("donnees_tp4")
CSV = D / "etablissements.csv"


def mo(chemin: Path) -> float:
    if chemin.is_dir():
        return (
            sum(f.stat().st_size for f in chemin.rglob("*") if f.is_file()) / 1_048_576
        )
    return chemin.stat().st_size / 1_048_576


def main() -> None:
    D.mkdir(parents=True, exist_ok=True)
    if not CSV.exists():
        raise FileNotFoundError(CSV)
    csv_mtime = CSV.stat().st_mtime_ns
    tableau = pd.read_csv(CSV, dtype=str)

    with tempfile.TemporaryDirectory(prefix=".convertir-tmp-", dir=D) as temporaire:
        staging = Path(temporaire)
        tableau.to_parquet(staging / "brut.parquet", index=False, compression=None)
        tableau.to_parquet(
            staging / "snappy.parquet", index=False, compression="snappy"
        )
        tableau.to_parquet(staging / "zstd.parquet", index=False, compression="zstd")

        # Parquet utilise déjà l'encodage dictionnaire pour ces colonnes.
        categoriel = tableau.copy()
        for colonne in (
            "type_etablissement",
            "statut_public_prive",
            "libelle_departement",
            "libelle_region",
            "etat",
            "code_departement",
        ):
            categoriel[colonne] = categoriel[colonne].astype("category")
        categoriel.to_parquet(
            staging / "categories.parquet", index=False, compression="zstd"
        )

        partition_stage = staging / "partitionne"
        tableau.to_parquet(
            partition_stage,
            index=False,
            compression="zstd",
            partition_cols=["code_departement"],
        )

        if CSV.stat().st_mtime_ns != csv_mtime:
            raise RuntimeError("Le CSV a changé pendant sa conversion.")
        outputs = (
            "brut.parquet",
            "snappy.parquet",
            "zstd.parquet",
            "categories.parquet",
        )
        for nom in outputs:
            os.replace(staging / nom, D / nom)

        partitionne = D / "partitionne"
        if partitionne.exists():
            if not partitionne.is_dir():
                raise NotADirectoryError(partitionne)
            shutil.rmtree(partitionne)
        os.replace(partition_stage, partitionne)

    print(f"{'Format':34s} {'Taille':>10s}  {'vs CSV':>8s}")
    print("-" * 56)
    base = mo(CSV)
    for libelle, chemin in [
        ("CSV", CSV),
        ("Parquet sans compression", D / "brut.parquet"),
        ("Parquet snappy", D / "snappy.parquet"),
        ("Parquet zstd", D / "zstd.parquet"),
        ("Parquet zstd + catégories", D / "categories.parquet"),
        ("Parquet zstd partitionné", partitionne),
    ]:
        taille = mo(chemin)
        print(f"{libelle:34s} {taille:7.0f} Mo  {base / taille:7.1f}×")


if __name__ == "__main__":
    try:
        main()
    except OSError as erreur:
        if erreur.errno != errno.ENOSPC:
            raise
        print(
            "Disque plein : la conversion a été annulée et les fichiers temporaires "
            "ont été supprimés. Libérez de la place puis relancez convertir.py.",
            file=sys.stderr,
        )
        raise SystemExit(1) from erreur
