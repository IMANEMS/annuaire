"""Agrégats calculés sur les données nettoyées."""

import pandas as pd

from annuaire.config import (
    COLONNE_DATE_OUVERTURE,
    COLONNE_DEPARTEMENT,
    COLONNE_STATUT,
    STATUT_PUBLIC,
)


def compter_par_departement(df: pd.DataFrame) -> pd.Series:
    """Nombre d'établissements par département, du plus grand au plus petit."""
    return df[COLONNE_DEPARTEMENT].value_counts()


def compter_public_prive(df: pd.DataFrame) -> tuple[int, int]:
    """Renvoie (nombre d'établissements publics, nombre de privés)."""
    nb_public = int((df[COLONNE_STATUT] == STATUT_PUBLIC).sum())
    return nb_public, len(df) - nb_public


def calculer_pourcentage_public(nb_public: int, nb_prive: int) -> float:
    """Part des établissements publics, en pourcentage."""
    return nb_public / (nb_public + nb_prive) * 100


def compter_par_annee_ouverture(df: pd.DataFrame) -> pd.Series:
    """Nombre d'établissements par année d'ouverture."""
    annees = df[COLONNE_DATE_OUVERTURE].str[0:4]
    return annees.value_counts().sort_index()
