"""Mise en forme des données brutes en un DataFrame exploitable."""

from typing import Any

import pandas as pd

from annuaire.config import (
    COLONNE_DEPARTEMENT,
    COLONNE_ETAT,
    COLONNES_RETENUES,
    ETAT_OUVERT,
)


def construire_dataframe(enregistrements: list[dict[str, Any]]) -> pd.DataFrame:
    """Transforme la liste d'enregistrements JSON en DataFrame."""
    return pd.DataFrame(enregistrements)


def selectionner_colonnes(df: pd.DataFrame) -> pd.DataFrame:
    """Ne garde que les colonnes utiles à l'analyse."""
    return df[COLONNES_RETENUES].copy()


def retirer_sans_departement(df: pd.DataFrame) -> pd.DataFrame:
    """Écarte les établissements dont le département est inconnu."""
    return df[df[COLONNE_DEPARTEMENT].notna()].copy()


def garder_ouverts(df: pd.DataFrame) -> pd.DataFrame:
    """Ne garde que les établissements ouverts."""
    return df[df[COLONNE_ETAT] == ETAT_OUVERT].copy()


def nettoyer(enregistrements: list[dict[str, Any]]) -> pd.DataFrame:
    """Enchaîne les étapes de nettoyage."""
    df = construire_dataframe(enregistrements)
    df = selectionner_colonnes(df)
    df = retirer_sans_departement(df)
    return garder_ouverts(df)
