"""Analyse métier indépendante du format des données."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

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
