"""TP 6 · étape 4 : la fin du `print`.

Un journal doit répondre à une question : à 3 h du matin, quelqu'un qui n'a pas
écrit ce code peut-il comprendre ce qui s'est passé ?

- chaque ligne porte l'identifiant de l'exécution (posé par un `logging.Filter`) ;
- le contexte va dans `extra={...}`, pas dans la phrase ;
- deux formats : texte lisible, ou JSON (une ligne = un objet) pour interroger ;
- les bibliothèques bavardes sont baissées à WARNING, pas réduites au silence.
"""

import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

# Les attributs qu'a toujours un LogRecord : tout le reste vient de `extra`.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "execution"}
BIBLIOTHEQUES_BAVARDES = ("sqlalchemy.engine", "httpx", "httpcore")


def nouvel_identifiant() -> str:
    """Un identifiant court, unique par exécution."""
    return uuid.uuid4().hex[:8]


class FiltreExecution(logging.Filter):
    """Ajoute l'identifiant d'exécution à chaque ligne, sans le passer à la main."""

    def __init__(self, execution: str) -> None:
        super().__init__()
        self.execution = execution

    def filter(self, record: logging.LogRecord) -> bool:
        record.execution = self.execution
        return True


def contexte(record: logging.LogRecord) -> dict[str, Any]:
    """Les champs passés dans `extra={...}`."""
    return {k: v for k, v in vars(record).items() if k not in _STANDARD}


class FormateurTexte(logging.Formatter):
    """Une ligne lisible, contexte en `cle=valeur` à la fin :

    `2026-11-12 16:02:11 INFO    [a3f9c2d1] annuaire.base: partition chargée
    fichier=dep=059.parquet ecrites=0`
    """

    def format(self, record: logging.LogRecord) -> str:
        heure = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        ligne = (
            f"{heure} {record.levelname:<7} [{getattr(record, 'execution', '-')}] "
            f"{record.name}: {record.getMessage()}"
        )
        champs = contexte(record)
        if champs:
            ligne += " " + " ".join(f"{cle}={valeur}" for cle, valeur in champs.items())
        if record.exc_info:
            ligne += "\n" + self.formatException(record.exc_info)
        return ligne


class FormateurJson(logging.Formatter):
    """Une ligne = un objet JSON : le journal s'interroge au lieu de se lire."""

    def format(self, record: logging.LogRecord) -> str:
        objet: dict[str, Any] = {
            "heure": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "niveau": record.levelname,
            "execution": getattr(record, "execution", None),
            "journal": record.name,
            "message": record.getMessage(),
            **contexte(record),
        }
        if record.exc_info:
            objet["exception"] = self.formatException(record.exc_info)
        return json.dumps(objet, ensure_ascii=False, default=str)


def configurer_journal(
    niveau: str = "INFO", en_json: bool = False, execution: str | None = None
) -> str:
    """Installe le journal pour toute l'application. Renvoie l'identifiant."""
    execution = execution or nouvel_identifiant()
    gestionnaire = logging.StreamHandler(sys.stderr)
    gestionnaire.addFilter(FiltreExecution(execution))
    gestionnaire.setFormatter(FormateurJson() if en_json else FormateurTexte())

    racine = logging.getLogger()
    racine.handlers.clear()
    racine.addHandler(gestionnaire)
    racine.setLevel(niveau)
    for nom in BIBLIOTHEQUES_BAVARDES:
        logging.getLogger(nom).setLevel(logging.WARNING)
    return execution
