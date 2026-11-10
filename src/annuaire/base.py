"""TP 6 : faire atterrir les données dans une base, de façon rejouable.

- schéma en SQLAlchemy **Core** (on déplace des lignes par milliers) ;
- une ligne par UAI : les fiches multiples de la source sont écartées *et tracées* ;
- `INSERT ... ON CONFLICT DO UPDATE ... WHERE <une valeur a changé>` : rejouer
  n'écrit rien, et on le mesure avec `RETURNING` (`rowcount` vaut -1 ici) ;
- par lots, une transaction par partition, aucun `DELETE` préalable.
"""

import hashlib
import logging
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as insert_pg
from sqlalchemy.dialects.sqlite import insert as insert_sqlite

from annuaire.config import COLONNE_IDENTIFIANT
from annuaire.nettoyage import dedoublonner

journal = logging.getLogger(__name__)

# Paramètres liés au plus par instruction (un par cellule du lot).
MAX_PARAMETRES: int = 65_535  # PostgreSQL
MAX_PARAMETRES_PAR_DIALECTE: dict[str, int] = {"postgresql": 65_535, "sqlite": 32_766}

metadonnees = sa.MetaData()
etablissement = sa.Table(
    "etablissement",
    metadonnees,
    sa.Column("identifiant", sa.String(8), primary_key=True),
    sa.Column("nom", sa.Text, nullable=False),
    sa.Column("type", sa.Text),
    sa.Column("statut", sa.Text),
    sa.Column("nature", sa.Text),
    sa.Column("adresse", sa.Text),
    sa.Column("code_postal", sa.String(5)),
    sa.Column("commune", sa.Text),
    sa.Column("code_departement", sa.String(3), nullable=False, index=True),
    sa.Column("departement", sa.Text),
    sa.Column("academie", sa.Text),
    sa.Column("region", sa.Text),
    sa.Column("telephone", sa.Text),
    sa.Column("mail", sa.Text),
    sa.Column("web", sa.Text),
    sa.Column("latitude", sa.Float),
    sa.Column("longitude", sa.Float),
    sa.Column("date_ouverture", sa.Date),
    sa.Column("etat", sa.Text),
    sa.Column("multi_uai", sa.Boolean, nullable=False),
    # Ces deux colonnes viennent du pipeline, pas de la source.
    sa.Column("charge_le", sa.DateTime(timezone=True), nullable=False),
    sa.Column("execution", sa.String(32), nullable=False),
)

# nom en base → nom dans la source (20 colonnes retenues sur 71).
CORRESPONDANCE: dict[str, str] = {
    "identifiant": COLONNE_IDENTIFIANT,
    "nom": "nom_etablissement",
    "type": "type_etablissement",
    "statut": "statut_public_prive",
    "nature": "libelle_nature",
    "adresse": "adresse_1",
    "code_postal": "code_postal",
    "commune": "nom_commune",
    "code_departement": "code_departement",
    "departement": "libelle_departement",
    "academie": "libelle_academie",
    "region": "libelle_region",
    "telephone": "telephone",
    "mail": "mail",
    "web": "web",
    "latitude": "latitude",
    "longitude": "longitude",
    "date_ouverture": "date_ouverture",
    "etat": "etat",
    "multi_uai": "multi_uai",
}
COLONNES_METIER: list[str] = [c for c in CORRESPONDANCE if c != "identifiant"]
COLONNES_PIPELINE: list[str] = ["charge_le", "execution"]

Ligne = dict[str, Any]


class ChargementRefuse(RuntimeError):
    """Le chargement refuse de partir plutôt que de perdre des lignes."""


@dataclass
class Bilan:
    """Ce qu'a fait une exécution de `charger`, mesuré et non supposé."""

    execution: str
    partitions: int
    lues: int
    ecartees: int
    ecrites: int
    en_base: int


def lot_maximal(dialecte: str = "postgresql") -> int:
    """La plus grande taille de lot acceptée par cette base pour cette table."""
    limite = MAX_PARAMETRES_PAR_DIALECTE.get(dialecte, MAX_PARAMETRES)
    return limite // len(etablissement.columns)


def verifier_lot(lot: int, dialecte: str = "postgresql") -> None:
    """Refuse, avant d'écrire quoi que ce soit, un lot trop gros pour la base."""
    colonnes = len(etablissement.columns)
    limite = MAX_PARAMETRES_PAR_DIALECTE.get(dialecte, MAX_PARAMETRES)
    if lot * colonnes > limite:
        raise ValueError(
            f"lot de {lot} lignes × {colonnes} colonnes = {lot * colonnes} paramètres, "
            f"au-delà des {limite} qu'accepte {dialecte} : "
            f"lot maximal {lot_maximal(dialecte)}"
        )


def preparer(df: pd.DataFrame, execution: str, charge_le: datetime) -> list[Ligne]:
    """Passe des colonnes de la source à celles de la table, avec les bons types."""
    table = df[list(CORRESPONDANCE.values())].rename(
        columns={source: base for base, source in CORRESPONDANCE.items()}
    )
    table["latitude"] = pd.to_numeric(table["latitude"], errors="coerce")
    table["longitude"] = pd.to_numeric(table["longitude"], errors="coerce")
    table["date_ouverture"] = pd.to_datetime(
        table["date_ouverture"], errors="coerce"
    ).dt.date
    table["multi_uai"] = (
        pd.to_numeric(table["multi_uai"], errors="coerce").fillna(0) != 0
    )
    # astype(object) rend des types Python (float, str, bool) ; NaN/NaT → None.
    table = table.astype(object).where(table.notna(), None)
    lignes: list[Ligne] = table.to_dict("records")
    for ligne in lignes:
        ligne["charge_le"] = charge_le
        ligne["execution"] = execution
    return lignes


def par_lots(lignes: Sequence[Ligne], taille: int) -> Iterator[Sequence[Ligne]]:
    for debut in range(0, len(lignes), taille):
        yield lignes[debut : debut + taille]


def ecrire_lot(connexion: sa.Connection, paquet: Sequence[Ligne]) -> int:
    """Une instruction pour tout le lot. Renvoie le nombre de lignes réellement
    écrites (insérées ou modifiées), compté avec RETURNING."""
    inserer = insert_pg if connexion.dialect.name == "postgresql" else insert_sqlite
    insertion = inserer(etablissement).values(list(paquet))
    nouveau = insertion.excluded
    requete = insertion.on_conflict_do_update(
        index_elements=["identifiant"],
        set_={c: nouveau[c] for c in COLONNES_METIER + COLONNES_PIPELINE},
        # Le cœur de l'idempotence : on ne réécrit une ligne que si une donnée
        # métier a changé. IS DISTINCT FROM, car NULL <> 'x' n'est pas vrai.
        where=sa.or_(
            *(etablissement.c[c].is_distinct_from(nouveau[c]) for c in COLONNES_METIER)
        ),
    ).returning(etablissement.c.identifiant)
    return len(connexion.execute(requete).all())


def verifier_partitions_disjointes(fichiers: Sequence[Path]) -> None:
    """Un même UAI dans deux partitions serait écrasé en silence d'une
    transaction à l'autre : dans ce cas, on refuse de partir."""
    vus: dict[str, str] = {}
    conflits: list[str] = []
    for fichier in fichiers:
        ids = pd.read_parquet(fichier, columns=[COLONNE_IDENTIFIANT])[
            COLONNE_IDENTIFIANT
        ]
        for identifiant in ids.unique():
            if identifiant in vus and vus[identifiant] != fichier.name:
                conflits.append(f"{identifiant} ({vus[identifiant]}, {fichier.name})")
            vus[identifiant] = fichier.name
    if conflits:
        raise ChargementRefuse(
            f"{len(conflits)} UAI présents dans plusieurs partitions, par ex. "
            f"{', '.join(conflits[:3])} : refus de charger"
        )


def charger(
    engine: sa.Engine,
    source: Path,
    lot: int,
    execution: str,
    ecartees: Path,
) -> Bilan:
    """Charge toutes les partitions. Rejouable : un second passage n'écrit rien."""
    fichiers = sorted(source.glob("dep=*.parquet"))
    if not fichiers:
        raise ChargementRefuse(
            f"aucune partition dans {source}/ : lancez --sauvegarder"
        )
    verifier_lot(lot, engine.dialect.name)
    verifier_partitions_disjointes(fichiers)
    metadonnees.create_all(engine)

    charge_le = datetime.now(UTC)
    journal.info("chargement démarré", extra={"partitions": len(fichiers), "lot": lot})
    lues = ecrites = 0
    mises_de_cote: list[pd.DataFrame] = []
    for fichier in fichiers:
        debut = time.perf_counter()
        brut = pd.read_parquet(fichier)
        garde = dedoublonner(brut)
        mises_de_cote.append(brut.loc[brut.index.difference(garde.index)])
        lignes = preparer(garde, execution, charge_le)
        with engine.begin() as connexion:  # une transaction par partition
            ecrites_partition = sum(
                ecrire_lot(connexion, paquet) for paquet in par_lots(lignes, lot)
            )
        lues += len(brut)
        ecrites += ecrites_partition
        journal.info(
            "partition chargée",
            extra={
                "fichier": fichier.name,
                "lues": len(brut),
                "ecartees": len(brut) - len(garde),
                "ecrites": ecrites_partition,
                "duree_s": round(time.perf_counter() - debut, 3),
            },
        )

    ecart = pd.concat(mises_de_cote, ignore_index=True)
    if not ecart.empty:
        ecartees.parent.mkdir(parents=True, exist_ok=True)
        provisoire = ecartees.with_name(ecartees.name + ".partiel")
        ecart.to_csv(provisoire, index=False)
        provisoire.replace(ecartees)
        # Une ligne qui résume, plutôt que 85 lignes identiques.
        journal.warning(
            "fiches écartées : UAI à fiches multiples dans la source (multi_uai)",
            extra={
                "ecartees": len(ecart),
                "uai": ecart[COLONNE_IDENTIFIANT].nunique(),
                "detail": str(ecartees),
            },
        )

    with engine.connect() as connexion:
        en_base = connexion.execute(
            sa.select(sa.func.count()).select_from(etablissement)
        ).scalar_one()
    bilan = Bilan(execution, len(fichiers), lues, len(ecart), ecrites, en_base)
    if en_base != lues - len(ecart):
        journal.warning(
            "la table ne correspond pas à la source du jour",
            extra={"en_base": en_base, "attendues": lues - len(ecart)},
        )
    journal.info(
        "chargement terminé",
        extra={
            "lues": lues,
            "ecartees": len(ecart),
            "ecrites": ecrites,
            "en_base": en_base,
        },
    )
    return bilan


def empreinte(connexion: sa.Connection) -> tuple[int, str]:
    """(nombre de lignes, SHA-256 de toute la table triée par identifiant).

    Deux empreintes égales : la table est identique, cellule par cellule,
    `charge_le` et `execution` compris.
    """
    hachage = hashlib.sha256()
    nombre = 0
    lignes = connexion.execute(
        sa.select(etablissement).order_by(etablissement.c.identifiant)
    )
    for ligne in lignes:
        hachage.update(repr(tuple(ligne)).encode())
        nombre += 1
    return nombre, hachage.hexdigest()


# --- Au passage : une requête paramétrée -------------------------------------------


def lister_departement_fstring(connexion: sa.Connection, code: str) -> list[Any]:
    """⚠️ VULNÉRABLE, pour la démonstration : la valeur est collée dans le SQL."""
    requete = (
        "SELECT identifiant, nom FROM etablissement "
        f"WHERE code_departement = '{code}'"  # noqa: S608
    )
    return list(connexion.execute(sa.text(requete)).all())


def lister_departement(connexion: sa.Connection, code: str) -> list[Any]:
    """La bonne version : `code` est un paramètre lié, jamais du SQL."""
    requete = sa.text(
        "SELECT identifiant, nom FROM etablissement WHERE code_departement = :code"
    )
    return list(connexion.execute(requete, {"code": code}).all())
