"""Mise en forme des données brutes en un DataFrame exploitable."""

from typing import Any

import pandas as pd

from annuaire.config import (
    COLONNE_DEPARTEMENT,
    COLONNE_ETAT,
    COLONNE_FICHE_ONISEP,
    COLONNE_IDENTIFIANT,
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


def aplatir_position(df: pd.DataFrame) -> pd.DataFrame:
    """Retire `position` ({lat, lon}), illisible en CSV.

    Elle double `latitude` et `longitude` ; à défaut, on l'éclate en deux colonnes.
    """
    if "position" not in df.columns:
        return df
    if {"latitude", "longitude"} <= set(df.columns):
        return df.drop(columns="position")
    position = df["position"]
    return df.drop(columns="position").assign(
        latitude=position.map(lambda p: p.get("lat") if isinstance(p, dict) else None),
        longitude=position.map(lambda p: p.get("lon") if isinstance(p, dict) else None),
    )


def dedoublonner(df: pd.DataFrame) -> pd.DataFrame:
    """Une seule ligne par établissement (UAI).

    La source renvoie plusieurs fiches pour certains UAI (`multi_uai = 1` :
    antennes, sites, fiches ONISEP). Règle, documentée dans le README : on garde
    la fiche la plus complète (le plus de champs renseignés) ; à égalité, la
    première dans l'ordre de `fiche_onisep`, pour un résultat reproductible.
    """
    tri = [COLONNE_IDENTIFIANT, "_renseignes"]
    croissant = [True, False]
    if COLONNE_FICHE_ONISEP in df.columns:
        tri.append(COLONNE_FICHE_ONISEP)
        croissant.append(True)
    resultat = (
        df.assign(_renseignes=df.notna().sum(axis=1))
        .sort_values(tri, ascending=croissant, na_position="last", kind="stable")
        .drop_duplicates(COLONNE_IDENTIFIANT)
        .drop(columns="_renseignes")
        .sort_index()
    )
    return resultat
