"""Les sources de données : un contrat, trois lecteurs."""

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

import pyarrow.parquet as pq
import requests

from annuaire.config import API_URL, TAILLE_PAGE, TIMEOUT_SECONDES, TRI_API


class Lecteur(Protocol):
    """Tout objet qui sait faire `lire()` est un lecteur. Aucun héritage requis."""

    def lire(self) -> Iterator[dict[str, Any]]: ...


class LecteurCsv:
    """Lit un CSV ligne à ligne."""

    def __init__(self, chemin: Path) -> None:
        self.chemin = chemin

    def lire(self) -> Iterator[dict[str, Any]]:
        with self.chemin.open(encoding="utf-8", newline="") as fichier:
            for ligne in csv.DictReader(fichier):
                # Le piège du CSV : l'absence s'y écrit "". On rétablit le None.
                yield {cle: valeur or None for cle, valeur in ligne.items()}


class LecteurParquet:
    """Lit un Parquet par paquets, sans tout charger."""

    def __init__(self, chemin: Path) -> None:
        self.chemin = chemin

    def lire(self) -> Iterator[dict[str, Any]]:
        fichier = pq.ParquetFile(self.chemin)
        for paquet in fichier.iter_batches():
            yield from paquet.to_pylist()


class LecteurApi:
    """Interroge l'API page par page, triée pour être reproductible."""

    def __init__(self, nb_max: int) -> None:
        if nb_max <= 0:
            raise ValueError("nb_max doit être supérieur à zéro")
        self.nb_max = nb_max

    def lire(self) -> Iterator[dict[str, Any]]:
        for offset in range(0, self.nb_max, TAILLE_PAGE):
            limite = min(TAILLE_PAGE, self.nb_max - offset)
            parametres: dict[str, str | int] = {
                "limit": limite,
                "offset": offset,
                "order_by": TRI_API,
            }
            reponse = requests.get(API_URL, params=parametres, timeout=TIMEOUT_SECONDES)
            reponse.raise_for_status()
            resultats: list[dict[str, Any]] = reponse.json()["results"]
            if not resultats:
                return
            yield from resultats
