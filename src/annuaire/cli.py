"""Interface en ligne de commande.

Analyser (séances 1 à 4), tout sauvegarder depuis l'API (TP 5), charger en base
(TP 6). Plus aucun `print` : tout passe par le journal, avec l'identifiant
d'exécution sur chaque ligne.
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import Literal

import pandas as pd
import sqlalchemy as sa
from pydantic import ValidationError

from annuaire.analyse import ResultatAnalyse, ResultatCle, analyser, analyser_cle
from annuaire.base import (
    charger,
    empreinte,
    lister_departement,
    lister_departement_fstring,
)
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
    Reglages,
    ReglagesJournal,
)
from annuaire.ingestion import Api, exporter_csv, sauvegarder_tout, trouver_mur
from annuaire.journal import configurer_journal
from annuaire.lecture import (
    Lecteur,
    LecteurApi,
    LecteurCsv,
    LecteurParquet,
    LecteurPartitions,
    charger_partitions,
)

journal = logging.getLogger("annuaire")

Source = Literal["csv", "parquet", "api", "partitions"]
CODE_INJECTION = "059' OR '1'='1"


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
    action.add_argument(
        "--charger",
        action="store_true",
        help="TP 6 : charger les partitions en base (upsert rejouable)",
    )
    action.add_argument(
        "--injection",
        action="store_true",
        help="TP 6 : comparer f-string et paramètre lié face à une injection",
    )
    options = parser.parse_args(arguments)
    if options.nombre <= 0:
        parser.error("--nombre doit être supérieur à zéro")
    return options


def afficher_resultat(resultat: ResultatAnalyse) -> None:
    """Journalise les agrégats et le nombre de rejets par motif."""
    total = resultat.public + resultat.prive
    journal.info(
        "analyse terminée",
        extra={
            "lus": resultat.enregistrements_lus,
            "valides": resultat.enregistrements_valides,
            "ouverts_avec_departement": sum(resultat.par_departement.values()),
            "public": resultat.public,
            "prive": resultat.prive,
            "part_public": round(resultat.public / total, 3) if total else 0.0,
        },
    )
    journal.info(
        "top des départements",
        extra={
            "top": dict(resultat.par_departement.most_common(NB_DEPARTEMENTS_AFFICHES))
        },
    )
    annees = sorted(resultat.par_annee_ouverture.items())[-NB_ANNEES_AFFICHEES:]
    journal.info("ouvertures par année", extra={"annees": dict(annees)})
    if resultat.rejets:
        journal.warning(
            "enregistrements rejetés",
            extra={
                "rejets": sum(resultat.rejets.values()),
                "motifs": dict(resultat.rejets.most_common()),
            },
        )


def afficher_cle(resultat: ResultatCle) -> None:
    """Journalise l'enquête sur les doublons d'identifiant (TP 5 · étape 5)."""
    journal.info(
        "analyse de la clé",
        extra={
            "lignes": resultat.lignes,
            "identifiants_distincts": resultat.identifiants_distincts,
            "identifiants_en_double": resultat.identifiants_en_double,
            "lignes_en_double": resultat.lignes_en_double,
            "doublons_meme_partition": resultat.doublons_meme_partition,
            "doublons_identiques": resultat.doublons_identiques,
        },
    )
    if resultat.identifiants_en_double:
        journal.info(
            "détail des doublons\nmulti_uai (doublons) :\n%s\n\ncolonnes qui diffèrent "
            ":\n%s\n\nexemple :\n%s",
            resultat.multi_uai_doublons,
            resultat.colonnes_differentes,
            resultat.exemple,
        )


def exporter() -> None:
    """Écrit le CSV de la web app, une ligne par UAI."""
    lues, ecrites = exporter_csv(DOSSIER_BRUT, FICHIER_CSV_COMPLET)
    journal.info(
        "CSV exporté",
        extra={
            "fichier": str(FICHIER_CSV_COMPLET),
            "etablissements": ecrites,
            "doublons_retires": lues - ecrites,
        },
    )


def executer_tp5(options: argparse.Namespace) -> None:
    """Les actions du TP 5."""
    if options.csv:
        exporter()
        return
    if options.cle:
        afficher_cle(analyser_cle(charger_partitions(DOSSIER_BRUT)))
        return
    api = Api.ouvrir()
    try:
        if options.mur:
            for limite in (1, TAILLE_PAGE):
                offset = trouver_mur(api, limite)
                journal.info(
                    "mur mesuré",
                    extra={
                        "limit": limite,
                        "offset_max": offset,
                        "somme": offset + limite,
                    },
                )
        else:
            bilan = sauvegarder_tout(api, DOSSIER_BRUT)
            journal.info(
                "sauvegarde terminée",
                extra={
                    "ecrites": bilan.ecrites,
                    "sautees": bilan.sautees,
                    "sur_disque": bilan.lignes_sur_disque,
                    "attendues": bilan.total_api,
                },
            )
            exporter()
    finally:
        api.fermer()


def lire_reglages() -> Reglages:
    """Valide la configuration ; refuse de démarrer si une valeur manque ou est
    du mauvais type."""
    try:
        return Reglages()  # type: ignore[call-arg]  # valeurs lues dans l'environnement
    except ValidationError as erreur:
        champs = [
            f"ANNUAIRE_{'_'.join(str(p) for p in e['loc']).upper()} : {e['msg']}"
            for e in erreur.errors(include_url=False)
        ]
        journal.error(
            "configuration invalide, arrêt (voir .env.exemple)",
            extra={"erreurs": champs},
        )
        raise SystemExit(2) from erreur


def executer_tp6(options: argparse.Namespace, execution: str) -> None:
    """Les actions du TP 6 : charger en base, et la démonstration d'injection."""
    reglages = lire_reglages()
    journal.info("connexion à la base", extra={"base": reglages.url_journal})
    engine = sa.create_engine(reglages.url_connexion)
    try:
        if options.charger:
            charger(engine, reglages.source, reglages.lot, execution, reglages.ecartees)
            with engine.connect() as connexion:
                lignes, somme = empreinte(connexion)
            journal.info(
                "empreinte de la table", extra={"lignes": lignes, "sha256": somme}
            )
        else:
            with engine.connect() as connexion:
                avec_fstring = len(
                    lister_departement_fstring(connexion, CODE_INJECTION)
                )
                avec_parametre = len(lister_departement(connexion, CODE_INJECTION))
            journal.warning(
                "injection SQL : comparaison des deux styles",
                extra={
                    "code": CODE_INJECTION,
                    "lignes_fstring": avec_fstring,
                    "lignes_parametre": avec_parametre,
                },
            )
    finally:
        engine.dispose()


def main(arguments: Sequence[str] | None = None) -> None:
    """Lance l'action demandée : par défaut, l'analyse et l'export des ouverts."""
    options = lire_arguments(arguments)
    reglages_journal = ReglagesJournal()
    execution = configurer_journal(
        reglages_journal.niveau_journal, reglages_journal.journal_json
    )
    try:
        if options.charger or options.injection:
            executer_tp6(options, execution)
            return
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
        export = pd.DataFrame(resultat.enregistrements_ouverts).reindex(
            columns=colonnes
        )
        export.to_csv(FICHIER_EXPORT, index=False)
        journal.info("export écrit", extra={"fichier": str(FICHIER_EXPORT)})
    except SystemExit:
        raise
    except Exception:
        journal.exception("le traitement a échoué")
        sys.exit(1)


if __name__ == "__main__":
    main()
