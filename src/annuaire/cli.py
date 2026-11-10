"""Interface en ligne de commande : analyser, et (TP 5) sauvegarder toute l'API."""

import argparse
from collections.abc import Sequence
from typing import Literal

import pandas as pd

from annuaire.analyse import ResultatAnalyse, ResultatCle, analyser, analyser_cle
from annuaire.config import (
    DOSSIER_BRUT,
    FICHIER_CSV,
    FICHIER_CSV_COMPLET,
    FICHIER_EXPORT,
    FICHIER_PARQUET,
    NB_ANNEES_AFFICHEES,
    NB_DEPARTEMENTS_AFFICHES,
    NB_ENREGISTREMENTS_MAX,
    TAILLE_PAGE,
)
from annuaire.ingestion import Api, exporter_csv, sauvegarder_tout, trouver_mur
from annuaire.lecture import (
    Lecteur,
    LecteurApi,
    LecteurCsv,
    LecteurParquet,
    LecteurPartitions,
    charger_partitions,
)

Source = Literal["csv", "parquet", "api", "partitions"]


def construire_lecteur(source: Source, nombre: int) -> Lecteur:
    """Construit le lecteur demandé par l'utilisateur."""
    if source == "csv":
        return LecteurCsv(FICHIER_CSV)
    if source == "parquet":
        return LecteurParquet(FICHIER_PARQUET)
    if source == "partitions":
        return LecteurPartitions(DOSSIER_BRUT)
    return LecteurApi(nombre)


def lire_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Lit les options de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Analyse de l'annuaire scolaire.")
    parser.add_argument(
        "--source",
        choices=("csv", "parquet", "api", "partitions"),
        default="api",
        help="source des données à analyser (défaut : api)",
    )
    parser.add_argument(
        "-n",
        "--nombre",
        type=int,
        default=NB_ENREGISTREMENTS_MAX,
        help="nombre maximal d'enregistrements à récupérer depuis l'API",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--mur",
        action="store_true",
        help="TP 5 · étape 1 : mesurer le plafond offset + limit de l'API",
    )
    action.add_argument(
        "--sauvegarder",
        action="store_true",
        help=f"TP 5 · étapes 2 à 4 : sauvegarder toute l'API dans {DOSSIER_BRUT}/",
    )
    action.add_argument(
        "--csv",
        action="store_true",
        help=f"exporter les partitions en un CSV sans doublon ({FICHIER_CSV_COMPLET})",
    )
    action.add_argument(
        "--cle",
        action="store_true",
        help="TP 5 · étape 5 : comparer lignes et identifiants distincts",
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


def afficher_cle(resultat: ResultatCle) -> None:
    """Affiche l'enquête sur les doublons d'identifiant (TP 5 · étape 5)."""
    print(f"lignes                  : {resultat.lignes}")
    print(f"identifiants distincts  : {resultat.identifiants_distincts}")
    print(
        f"identifiants en double  : {resultat.identifiants_en_double} "
        f"({resultat.lignes_en_double} lignes)"
    )
    if not resultat.identifiants_en_double:
        return
    print(
        "doublons dans un même fichier de partition : "
        f"{resultat.doublons_meme_partition} / {resultat.identifiants_en_double}"
    )
    print(
        "doublons strictement identiques (toutes colonnes) : "
        f"{resultat.doublons_identiques} / {resultat.identifiants_en_double}"
    )
    if resultat.multi_uai_doublons is not None:
        print(f"\nmulti_uai, lignes en double :\n{resultat.multi_uai_doublons}")
        print(f"\nmulti_uai, toutes les lignes :\n{resultat.multi_uai_tout}")
    print(f"\ncolonnes qui diffèrent entre copies :\n{resultat.colonnes_differentes}")
    print(f"\nexemple :\n{resultat.exemple}")


def exporter(options: argparse.Namespace) -> None:
    """Écrit le CSV de la web app, une ligne par UAI."""
    lues, ecrites = exporter_csv(DOSSIER_BRUT, FICHIER_CSV_COMPLET)
    print(
        f"CSV : {FICHIER_CSV_COMPLET} · {ecrites} établissements "
        f"({lues - ecrites} doublons d'UAI retirés sur {lues} lignes)"
    )


def executer_tp5(options: argparse.Namespace) -> None:
    """Les actions du TP 5."""
    if options.csv:
        exporter(options)
        return
    if options.cle:
        afficher_cle(analyser_cle(charger_partitions(DOSSIER_BRUT)))
        return
    api = Api.ouvrir()
    try:
        if options.mur:
            for limite in (1, TAILLE_PAGE):
                offset = trouver_mur(api, limite)
                print(
                    f"limit={limite:>3} : plus grand offset accepté = {offset} "
                    f"(offset + limit = {offset + limite})"
                )
        else:
            bilan = sauvegarder_tout(api, DOSSIER_BRUT)
            print(
                f"\n{bilan.ecrites} partitions écrites, {bilan.sautees} sautées · "
                f"{bilan.lignes_sur_disque} lignes sur disque = "
                f"{bilan.total_api} attendues ✅"
            )
            exporter(options)
    finally:
        api.fermer()


def main(arguments: Sequence[str] | None = None) -> None:
    """Lance l'action demandée : par défaut, l'analyse et l'export des ouverts."""
    options = lire_arguments(arguments)
    if options.mur or options.sauvegarder or options.csv or options.cle:
        executer_tp5(options)
        return

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
