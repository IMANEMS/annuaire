"""Récupération des données depuis l'API de l'Éducation nationale."""

import json
from pathlib import Path
from typing import Any

import requests

from annuaire.config import API_URL, TAILLE_PAGE, TIMEOUT_SECONDES

Enregistrement = dict[str, Any]


def recuperer_page(offset: int, limite: int) -> list[Enregistrement]:
    """Renvoie une page d'enregistrements à partir de la position `offset`."""
    reponse = requests.get(
        API_URL,
        params={"limit": limite, "offset": offset},
        timeout=TIMEOUT_SECONDES,
    )
    reponse.raise_for_status()
    resultats: list[Enregistrement] = reponse.json()["results"]
    return resultats


def recuperer_enregistrements(nb_max: int) -> list[Enregistrement]:
    """Parcourt les pages de l'API jusqu'à obtenir `nb_max` enregistrements."""
    enregistrements: list[Enregistrement] = []
    while len(enregistrements) < nb_max:
        limite = min(TAILLE_PAGE, nb_max - len(enregistrements))
        page = recuperer_page(offset=len(enregistrements), limite=limite)
        if not page:
            break
        enregistrements.extend(page)
    return enregistrements


def charger_echantillon(chemin: Path) -> list[Enregistrement]:
    """Charge un échantillon local, à utiliser si l'API ne répond pas."""
    with chemin.open(encoding="utf-8") as fichier:
        donnees: list[Enregistrement] = json.load(fichier)
    return donnees
