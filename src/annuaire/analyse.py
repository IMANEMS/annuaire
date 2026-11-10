"""Analyse métier indépendante du format des données."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import ValidationError

from annuaire.config import COLONNE_IDENTIFIANT
from annuaire.lecture import Lecteur
from annuaire.modele import Etablissement


@dataclass
class ResultatAnalyse:
    """Agrégats produits à partir d'un lecteur et motifs des rejets."""

    enregistrements_lus: int = 0
    enregistrements_valides: int = 0
    par_departement: Counter[str] = field(default_factory=Counter)
    public: int = 0
    prive: int = 0
    par_annee_ouverture: Counter[str] = field(default_factory=Counter)
    rejets: Counter[str] = field(default_factory=Counter)
    enregistrements_ouverts: list[dict[str, Any]] = field(default_factory=list)


def analyser(lecteur: Lecteur) -> ResultatAnalyse:
    """Valide et agrège les enregistrements lus, en comptant chaque rejet."""
    resultat = ResultatAnalyse()
    for brut in lecteur.lire():
        resultat.enregistrements_lus += 1
        try:
            etablissement = Etablissement.depuis_brut(brut)
        except ValidationError as erreur:
            detail = erreur.errors(include_url=False)[0]
            champ = (
                ".".join(str(partie) for partie in detail["loc"]) or "enregistrement"
            )
            resultat.rejets[f"{champ} : {detail['msg']}"] += 1
            continue

        resultat.enregistrements_valides += 1
        if not etablissement.est_ouvert:
            continue

        resultat.par_departement[etablissement.departement] += 1
        resultat.public += etablissement.statut == "Public"
        resultat.prive += etablissement.statut == "Privé"
        if etablissement.date_ouverture:
            resultat.par_annee_ouverture[etablissement.date_ouverture[:4]] += 1
        resultat.enregistrements_ouverts.append(brut)
    return resultat


def ouverts_par_departement(lecteur: Lecteur) -> Counter[str]:
    """Compte les établissements ouverts par département."""
    return analyser(lecteur).par_departement


@dataclass
class ResultatCle:
    """TP 5 · étape 5 : d'où viennent les identifiants en double ?"""

    lignes: int
    identifiants_distincts: int
    identifiants_en_double: int = 0
    lignes_en_double: int = 0
    doublons_meme_partition: int = 0
    doublons_identiques: int = 0
    multi_uai_doublons: str | None = None
    multi_uai_tout: str | None = None
    colonnes_differentes: str = ""
    exemple: str = ""


def analyser_cle(tout: pd.DataFrame) -> ResultatCle:
    """Compare lignes et identifiants distincts, et rassemble les preuves.

    Les partitions sont disjointes (un `where` par département) : si les deux
    copies d'un identifiant sont dans le même fichier, notre découpage n'y est
    pour rien, c'est la source qui renvoie l'établissement deux fois.
    """
    resultat = ResultatCle(len(tout), tout[COLONNE_IDENTIFIANT].nunique())
    doublons = tout[tout.duplicated(COLONNE_IDENTIFIANT, keep=False)]
    if doublons.empty:
        return resultat
    doublons = doublons.sort_values(COLONNE_IDENTIFIANT)
    par_id = doublons.groupby(COLONNE_IDENTIFIANT)
    colonnes = [c for c in tout.columns if c != "_fichier"]
    texte = doublons[colonnes].astype(str)

    resultat.identifiants_en_double = doublons[COLONNE_IDENTIFIANT].nunique()
    resultat.lignes_en_double = len(doublons)
    resultat.doublons_meme_partition = int((par_id["_fichier"].nunique() == 1).sum())
    differences = texte.groupby(doublons[COLONNE_IDENTIFIANT]).nunique().gt(1)
    resultat.doublons_identiques = int((~differences.any(axis=1)).sum())
    if "multi_uai" in tout.columns:
        resultat.multi_uai_doublons = (
            doublons["multi_uai"].value_counts(dropna=False).to_string()
        )
        resultat.multi_uai_tout = (
            tout["multi_uai"].value_counts(dropna=False).to_string()
        )
    compte = differences.sum().sort_values(ascending=False)
    resultat.colonnes_differentes = compte[compte > 0].to_string()
    exemple = doublons[COLONNE_IDENTIFIANT].iloc[0]
    apercu = [COLONNE_IDENTIFIANT, "_fichier"]
    apercu += [c for c in compte[compte > 0].index[:4] if c not in apercu]
    resultat.exemple = doublons[doublons[COLONNE_IDENTIFIANT] == exemple][
        [c for c in apercu if c in doublons.columns]
    ].to_string(index=False)
    return resultat
