"""Interface en ligne de commande pour l'analyse multi-source."""

import argparse
from collections.abc import Sequence
from typing import Literal

import pandas as pd

from annuaire.analyse import ResultatAnalyse, analyser
from annuaire.config import (
    FICHIER_CSV,
    FICHIER_EXPORT,
    FICHIER_PARQUET,
    NB_ANNEES_AFFICHEES,
    NB_DEPARTEMENTS_AFFICHES,
    NB_ENREGISTREMENTS_MAX,
)
from annuaire.lecture import Lecteur, LecteurApi, LecteurCsv, LecteurParquet

Source = Literal["csv", "parquet", "api"]


def construire_lecteur(source: Source, nombre: int) -> Lecteur:
    """Construit le lecteur demandé par l'utilisateur."""
    if source == "csv":
        return LecteurCsv(FICHIER_CSV)
    if source == "parquet":
        return LecteurParquet(FICHIER_PARQUET)
    return LecteurApi(nombre)


def lire_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Lit les options de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Analyse de l'annuaire scolaire.")
    parser.add_argument(
        "--source",
        choices=("csv", "parquet", "api"),
        default="api",
        help="source des données (défaut : api)",
    )
    parser.add_argument(
        "-n",
        "--nombre",
        type=int,
        default=NB_ENREGISTREMENTS_MAX,
        help="nombre maximal d'enregistrements à récupérer depuis l'API",
    )
    options = parser.parse_args(arguments)
    if options.nombre <= 0:
        parser.error("--nombre doit être supérieur à zéro")
    return options


def afficher_resultat(resultat: ResultatAnalyse) -> None:
    """Affiche les agrégats et le nombre de rejets par motif."""
    print(f"{resultat.enregistrements_lus} enregistrements lus")
    print(
        f"{resultat.enregistrements_valides} enregistrements valides · "
        f"{sum(resultat.par_departement.values())} établissements ouverts "
        "avec département"
    )

    print(f"\nTop {NB_DEPARTEMENTS_AFFICHES} des départements :")
    for departement, nombre in resultat.par_departement.most_common(
        NB_DEPARTEMENTS_AFFICHES
    ):
        print(f"{departement}: {nombre}")

    total = resultat.public + resultat.prive
    pourcentage = resultat.public / total * 100 if total else 0.0
    print(
        f"\nPublic : {resultat.public} · Privé : {resultat.prive} · "
        f"{pourcentage:.1f} % public"
    )

    print(f"\nOuvertures par année ({NB_ANNEES_AFFICHEES} dernières) :")
    annees = sorted(resultat.par_annee_ouverture.items())[-NB_ANNEES_AFFICHEES:]
    for annee, nombre in annees:
        print(f"{annee}: {nombre}")

    if resultat.rejets:
        print(f"\n{sum(resultat.rejets.values())} enregistrements rejetés :")
        for motif, nombre in resultat.rejets.most_common():
            print(f"- {motif}: {nombre}")
    else:
        print("\nAucun enregistrement rejeté")


def main(arguments: Sequence[str] | None = None) -> None:
    """Lance l'analyse avec la source choisie et exporte les établissements ouverts."""
    options = lire_arguments(arguments)
    lecteur = construire_lecteur(options.source, options.nombre)
    resultat = analyser(lecteur)
    afficher_resultat(resultat)

    colonnes = [
        "identifiant_de_l_etablissement",
        "nom_etablissement",
        "type_etablissement",
        "statut_public_prive",
        "code_postal",
        "nom_commune",
        "code_departement",
        "libelle_departement",
        "libelle_region",
        "etat",
        "date_ouverture",
    ]
    export = pd.DataFrame(resultat.enregistrements_ouverts).reindex(columns=colonnes)
    export.to_csv(FICHIER_EXPORT, index=False)
    print(f"\nExport : {FICHIER_EXPORT}")


if __name__ == "__main__":
    main()
