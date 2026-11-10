"""Récupération des données depuis l'API de l'Éducation nationale.

Séance 1 : quelques milliers d'enregistrements, par pagination à plat.
TP 5 : les 68 563, malgré le plafond `offset + limit <= 10 000` de l'API.
On découpe la lecture par département, chaque appel est limité en débit et
réessayé, et chaque partition est sauvegardée dans son propre fichier Parquet,
de façon atomique : relancer l'ingestion reprend là où elle s'était arrêtée.
"""

import functools
import json
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

import httpx
import pandas as pd
import requests

from annuaire.config import (
    API_URL,
    ATTENTE_INITIALE,
    ATTENTE_MAX,
    CODES_REESSAYABLES,
    COLONNE_IDENTIFIANT,
    COLONNE_PARTITION,
    DEBIT_PAR_SECONDE,
    DOSSIER_BRUT,
    FACTEUR_ATTENTE,
    FICHIER_CSV_COMPLET,
    PLAFOND_API,
    TAILLE_PAGE,
    TENTATIVES,
    TIMEOUT_SECONDES,
    TRI_API,
)
from annuaire.nettoyage import aplatir_position, dedoublonner

Enregistrement = dict[str, Any]
P = ParamSpec("P")
R = TypeVar("R")


# --- Séance 1 -----------------------------------------------------------------


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


# --- TP 5 · étape 3 : réessayer et rester sous le débit ---------------------------


class EchecDefinitif(RuntimeError):
    """L'opération a échoué après tous les réessais."""


class IngestionIncomplete(RuntimeError):
    """Le garde-fou : on préfère s'arrêter que perdre des données en silence."""


def lire_retry_after(reponse: httpx.Response) -> float | None:
    """Renvoie le délai demandé par le serveur en secondes, s'il en donne un."""
    entete = reponse.headers.get("Retry-After")
    if entete is None:
        return None
    try:
        return max(0.0, float(entete))
    except ValueError:
        return None  # format date HTTP : on retombe sur notre propre attente


def reessayer(
    tentatives: int = TENTATIVES,
    attente_initiale: float = ATTENTE_INITIALE,
    facteur: float = FACTEUR_ATTENTE,
    plafond: float = ATTENTE_MAX,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Décorateur : relance la fonction en cas de panne passagère.

    Attentes sans aléa : 0,5 s, 1 s, 2 s, 4 s... (plafonnées à `plafond`).
    Chacune est multipliée par un tirage dans [0,5 ; 1,5] (jitter) pour
    désynchroniser les clients. Si le serveur envoie `Retry-After`, on attend
    ce qu'il demande. Les codes hors `CODES_REESSAYABLES` (400, 404...)
    remontent immédiatement : une requête malformée le restera.
    """

    def decorateur(fonction: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fonction)
        def enveloppe(*args: P.args, **kwargs: P.kwargs) -> R:
            attente = attente_initiale
            derniere: Exception | None = None
            for tentative in range(1, tentatives + 1):
                try:
                    return fonction(*args, **kwargs)
                except httpx.HTTPStatusError as erreur:
                    if erreur.response.status_code not in CODES_REESSAYABLES:
                        raise  # 400, 404... : inutile d'insister
                    derniere = erreur
                    motif = f"code {erreur.response.status_code}"
                    demande = lire_retry_after(erreur.response)
                    pause = (
                        demande
                        if demande is not None
                        else attente * random.uniform(0.5, 1.5)
                    )
                except httpx.TransportError as erreur:  # réseau, timeout...
                    derniere = erreur
                    motif = type(erreur).__name__
                    pause = attente * random.uniform(0.5, 1.5)
                if tentative == tentatives:
                    break
                print(
                    f"  ↻ {fonction.__name__} : tentative {tentative} échouée "
                    f"({motif}), nouvel essai dans {pause:.2f} s",
                    file=sys.stderr,
                )
                time.sleep(pause)
                attente = min(attente * facteur, plafond)
            raise EchecDefinitif(
                f"{fonction.__name__} a échoué après {tentatives} tentatives"
            ) from derniere

        return enveloppe

    return decorateur


class Debit:
    """Garantit un intervalle minimal entre deux appels."""

    def __init__(self, par_seconde: float) -> None:
        if par_seconde <= 0:
            raise ValueError("par_seconde doit être strictement positif")
        self.intervalle = 1.0 / par_seconde
        # None et pas 0.0 : le premier appel n'attend pas.
        self._dernier: float | None = None

    def attendre(self) -> None:
        """Bloque juste ce qu'il faut pour respecter l'intervalle."""
        if self._dernier is not None:
            reste = self.intervalle - (time.monotonic() - self._dernier)
            if reste > 0:
                time.sleep(reste)
        self._dernier = time.monotonic()


class Api:
    """Accès à l'API : un client réutilisé, chaque appel limité et réessayé."""

    def __init__(self, client: httpx.Client, debit: Debit) -> None:
        self.client = client
        self.debit = debit

    @classmethod
    def ouvrir(cls, par_seconde: float = DEBIT_PAR_SECONDE) -> "Api":
        """Une API réelle, toujours avec un timeout. À fermer avec `fermer()`."""
        return cls(httpx.Client(timeout=TIMEOUT_SECONDES), Debit(par_seconde))

    def fermer(self) -> None:
        self.client.close()

    @reessayer()
    def lire(self, params: dict[str, Any]) -> dict[str, Any]:
        """Un appel à l'API. Lève `HTTPStatusError` si le code n'est pas 2xx."""
        self.debit.attendre()
        reponse = self.client.get(API_URL, params=params)
        reponse.raise_for_status()
        donnees: dict[str, Any] = reponse.json()
        return donnees


# --- TP 5 · étape 1 : mesurer le mur ----------------------------------------------


def offset_accepte(api: Api, offset: int, limite: int) -> bool:
    """Vrai si l'API accepte ce couple (offset, limit), faux si elle répond 400."""
    try:
        api.lire({"limit": limite, "offset": offset})
    except httpx.HTTPStatusError as erreur:
        if erreur.response.status_code == 400:
            return False
        raise
    return True


def trouver_mur(api: Api, limite: int, borne_haute: int = 2 * PLAFOND_API) -> int:
    """Plus grand offset accepté pour cette `limite` (recherche dichotomique)."""
    bas, haut = 0, borne_haute  # invariant : `bas` accepté, `haut` refusé
    if not offset_accepte(api, bas, limite):
        raise RuntimeError(f"même offset=0 est refusé avec limit={limite}")
    while haut - bas > 1:
        milieu = (bas + haut) // 2
        if offset_accepte(api, milieu, limite):
            bas = milieu
        else:
            haut = milieu
    return bas


# --- TP 5 · étape 2 : partitionner ------------------------------------------------


def lire_total(api: Api) -> int:
    """Le nombre total d'enregistrements selon l'API."""
    total: int = api.lire({"limit": 1})["total_count"]
    return total


def lire_partitions(api: Api) -> dict[str | None, int]:
    """Effectif par département. La liste est elle-même paginée : on la lit
    jusqu'à une page incomplète, sinon des départements disparaîtraient."""
    partitions: dict[str | None, int] = {}
    offset = 0
    while True:
        page = api.lire(
            {
                "group_by": COLONNE_PARTITION,
                "select": f"{COLONNE_PARTITION}, count(*) as n",
                "order_by": COLONNE_PARTITION,
                "limit": TAILLE_PAGE,
                "offset": offset,
            }
        )["results"]
        for groupe in page:
            partitions[groupe[COLONNE_PARTITION]] = int(groupe["n"])
        if len(page) < TAILLE_PAGE:
            return partitions
        offset += TAILLE_PAGE


def verifier_partitions(partitions: dict[str | None, int], total: int) -> None:
    """Le garde-fou : la somme des partitions doit égaler le total de l'API,
    et aucune partition ne doit dépasser le plafond."""
    somme = sum(partitions.values())
    if somme != total:
        raise IngestionIncomplete(
            f"somme des partitions ({somme}) ≠ total de l'API ({total}) : "
            "on s'arrête plutôt que de perdre des données en silence"
        )
    trop_grosses = {code: n for code, n in partitions.items() if n > PLAFOND_API}
    if trop_grosses:
        raise IngestionIncomplete(
            f"partitions au-delà du plafond de {PLAFOND_API} : {trop_grosses}"
        )


def filtre(code: str | None) -> str:
    """La clause `where` d'une partition. Les guillemets comptent."""
    if code is None:
        return f"{COLONNE_PARTITION} is null"
    return f'{COLONNE_PARTITION}="{code}"'


def lire_partition(api: Api, code: str | None, attendu: int) -> list[Enregistrement]:
    """Toutes les lignes d'un département, page par page, triées (TP 3)."""
    lignes: list[Enregistrement] = []
    for offset in range(0, attendu, TAILLE_PAGE):
        limite = min(TAILLE_PAGE, attendu - offset)
        lignes.extend(
            api.lire(
                {
                    "where": filtre(code),
                    "order_by": TRI_API,
                    "limit": limite,
                    "offset": offset,
                }
            )["results"]
        )
    if len(lignes) != attendu:
        raise IngestionIncomplete(
            f"département {code} : {len(lignes)} lignes lues, {attendu} attendues"
        )
    return lignes


# --- TP 5 · étape 4 : sauvegarder sans dupliquer ----------------------------------


def chemin_partition(dossier: Path, code: str | None) -> Path:
    """`donnees/brut/dep=059.parquet` (et `dep=inconnu` si le code est absent)."""
    return dossier / f"dep={code if code is not None else 'inconnu'}.parquet"


def ecrire_atomique(lignes: list[Enregistrement], cible: Path) -> None:
    """Écrit dans un fichier provisoire puis renomme : le nom définitif
    n'apparaît qu'une fois le contenu complet."""
    provisoire = cible.with_name(cible.name + ".partiel")
    pd.DataFrame(lignes).to_parquet(provisoire, index=False)
    provisoire.replace(cible)  # atomique sur un même système de fichiers


def compter_sur_disque(dossier: Path) -> int:
    """Nombre de lignes dans toutes les partitions déjà sauvegardées."""
    return sum(len(pd.read_parquet(f)) for f in sorted(dossier.glob("dep=*.parquet")))


@dataclass
class Bilan:
    """Ce qu'a fait une exécution de `sauvegarder_tout`."""

    total_api: int
    partitions: int
    ecrites: int
    sautees: int
    lignes_sur_disque: int


def sauvegarder_tout(api: Api, dossier: Path = DOSSIER_BRUT) -> Bilan:
    """Ingère et sauvegarde toutes les partitions manquantes.

    Idempotent : les partitions déjà présentes sont sautées, relancer est sans
    effet. Le garde-fou arrête tout si un total ne correspond pas.
    """
    dossier.mkdir(parents=True, exist_ok=True)
    total = lire_total(api)
    partitions = lire_partitions(api)
    verifier_partitions(partitions, total)
    print(f"{total} établissements, {len(partitions)} départements")

    ecrites = sautees = 0
    for code, attendu in sorted(partitions.items(), key=lambda p: str(p[0])):
        cible = chemin_partition(dossier, code)
        if cible.exists():
            sautees += 1
            continue
        ecrire_atomique(lire_partition(api, code, attendu), cible)
        ecrites += 1
        print(f"  ✓ {cible.name:<22} {attendu:>6} lignes")

    sur_disque = compter_sur_disque(dossier)
    if sur_disque != total:
        raise IngestionIncomplete(
            f"{sur_disque} lignes sur disque pour {total} attendues "
            "(un fichier d'une exécution précédente est-il périmé ?)"
        )
    return Bilan(total, len(partitions), ecrites, sautees, sur_disque)


# --- Export CSV pour la web app ---------------------------------------------------


def exporter_csv(
    dossier: Path = DOSSIER_BRUT, cible: Path = FICHIER_CSV_COMPLET
) -> tuple[int, int]:
    """Rassemble les partitions en un CSV sans doublon d'UAI, écrit atomiquement.

    Renvoie (lignes lues, lignes écrites).
    """
    fichiers = sorted(dossier.glob("dep=*.parquet"))
    if not fichiers:
        raise FileNotFoundError(
            f"aucune partition dans {dossier}/ : lancez --sauvegarder"
        )
    tout = pd.concat([pd.read_parquet(f) for f in fichiers], ignore_index=True)
    propre = dedoublonner(aplatir_position(tout))
    if propre[COLONNE_IDENTIFIANT].duplicated().any():
        raise IngestionIncomplete("des doublons d'UAI subsistent après dédoublonnage")
    cible.parent.mkdir(parents=True, exist_ok=True)
    provisoire = cible.with_name(cible.name + ".partiel")
    propre.to_csv(provisoire, index=False, encoding="utf-8")
    provisoire.replace(cible)
    return len(tout), len(propre)
