"""Point d'entrée : `annuaire-ingest` ou `python -m annuaire`."""

import argparse

from annuaire.analyse import (
    calculer_pourcentage_public,
    compter_par_annee_ouverture,
    compter_par_departement,
    compter_public_prive,
)
from annuaire.config import (
    FICHIER_ECHANTILLON,
    FICHIER_EXPORT,
    NB_ANNEES_AFFICHEES,
    NB_DEPARTEMENTS_AFFICHES,
    NB_ENREGISTREMENTS_MAX,
)
from annuaire.ingestion import charger_echantillon, recuperer_enregistrements
from annuaire.nettoyage import nettoyer


def lire_arguments() -> argparse.Namespace:
    """Lit les options de la ligne de commande."""
    parser = argparse.ArgumentParser(description="Analyse de l'annuaire scolaire.")
    parser.add_argument(
        "-n",
        "--nombre",
        type=int,
        default=NB_ENREGISTREMENTS_MAX,
        help="nombre d'enregistrements à récupérer",
    )
    parser.add_argument(
        "--hors-ligne",
        action="store_true",
        help="utiliser le fichier échantillon au lieu de l'API",
    )
    return parser.parse_args()


def main() -> None:
    """Lance le pipeline complet, affiche les agrégats et exporte le CSV."""
    arguments = lire_arguments()
    if arguments.hors_ligne:
        enregistrements = charger_echantillon(FICHIER_ECHANTILLON)
    else:
        enregistrements = recuperer_enregistrements(arguments.nombre)
    print(f"{len(enregistrements)} enregistrements récupérés")

    df = nettoyer(enregistrements)
    print(f"{len(df)} établissements ouverts avec département\n")

    print(f"Top {NB_DEPARTEMENTS_AFFICHES} des départements :")
    print(compter_par_departement(df).head(NB_DEPARTEMENTS_AFFICHES).to_string())

    nb_public, nb_prive = compter_public_prive(df)
    pourcentage = calculer_pourcentage_public(nb_public, nb_prive)
    print(f"\nPublic : {nb_public} · Privé : {nb_prive} · {pourcentage:.1f} % public")

    print(f"\nOuvertures par année ({NB_ANNEES_AFFICHEES} dernières) :")
    print(compter_par_annee_ouverture(df).tail(NB_ANNEES_AFFICHEES).to_string())

    df.to_csv(FICHIER_EXPORT, index=False)
    print(f"\nExport : {FICHIER_EXPORT}")


if __name__ == "__main__":
    main()
