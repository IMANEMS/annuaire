"""Tests du TP 6 sur SQLite : même SQL `ON CONFLICT ... WHERE ... RETURNING`
que PostgreSQL, sans base à installer."""

import io
import json
import logging
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import pandas as pd
import sqlalchemy as sa
from pydantic import ValidationError

from annuaire import base
from annuaire.base import ChargementRefuse, charger, empreinte
from annuaire.config import Reglages
from annuaire.journal import FiltreExecution, FormateurJson, configurer_journal


def ligne(identifiant: str, dep: str, **autres: Any) -> dict[str, Any]:
    donnees: dict[str, Any] = {source: None for source in base.CORRESPONDANCE.values()}
    donnees.update(
        identifiant_de_l_etablissement=identifiant,
        nom_etablissement=f"Établissement {identifiant}",
        code_departement=dep,
        statut_public_prive="Public",
        latitude=45.0,
        date_ouverture="1965-05-01",
        multi_uai=0,
        fiche_onisep=None,
        colonne_ignoree="pas chargée",
    )
    donnees.update(autres)
    return donnees


class Chargement(unittest.TestCase):
    def setUp(self) -> None:
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.racine = Path(dossier.name)
        self.source = self.racine / "brut"
        self.source.mkdir()
        self.ecartees = self.racine / "ecartees.csv"
        self.engine = sa.create_engine(f"sqlite:///{self.racine / 'base.db'}")
        self.addCleanup(self.engine.dispose)
        self.ecrire("001", [ligne(f"001{i:04d}A", "001") for i in range(7)])
        self.ecrire(
            "059",
            [
                ligne("0590001A", "059"),
                ligne("0590002B", "059", statut_public_prive=None),
                # La source renvoie deux fiches pour le même UAI (multi_uai).
                ligne(
                    "0590003C", "059", multi_uai=1, telephone="03", fiche_onisep="E.1"
                ),
                ligne("0590003C", "059", multi_uai=1, fiche_onisep="E.2"),
            ],
        )

    def ecrire(self, dep: str, lignes: list[dict[str, Any]]) -> None:
        pd.DataFrame(lignes).to_parquet(self.source / f"dep={dep}.parquet", index=False)

    def charger(self, execution: str, lot: int = 3) -> base.Bilan:
        return charger(self.engine, self.source, lot, execution, self.ecartees)

    def test_premier_passage_puis_rejeu_a_zero(self) -> None:
        premier = self.charger("run1")
        self.assertEqual((premier.lues, premier.ecartees), (11, 1))
        self.assertEqual((premier.ecrites, premier.en_base), (10, 10))
        with self.engine.connect() as c:
            avant = empreinte(c)

        second = self.charger("run2")
        self.assertEqual(second.ecrites, 0)  # mesuré avec RETURNING
        with self.engine.connect() as c:
            self.assertEqual(empreinte(c), avant)  # cellule par cellule
            executions = c.execute(
                sa.text("SELECT DISTINCT execution FROM etablissement")
            )
            self.assertEqual([e for (e,) in executions], ["run1"])

    def test_null_ne_reecrit_pas(self) -> None:
        # statut NULL des deux côtés : IS DISTINCT FROM dit « égal », pas « différent ».
        self.charger("run1")
        self.assertEqual(self.charger("run2").ecrites, 0)

    def test_une_valeur_changee_reecrit_une_ligne(self) -> None:
        self.charger("run1")
        self.ecrire(
            "001",
            [ligne(f"001{i:04d}A", "001") for i in range(6)]
            + [ligne("0010006A", "001", nom_etablissement="Nouveau nom")],
        )
        self.assertEqual(self.charger("run2").ecrites, 1)
        with self.engine.connect() as c:
            execution, nom = c.execute(
                sa.text(
                    "SELECT execution, nom FROM etablissement "
                    "WHERE identifiant = '0010006A'"
                )
            ).one()
        self.assertEqual((execution, nom), ("run2", "Nouveau nom"))

    def test_fiches_ecartees_tracees(self) -> None:
        self.charger("run1")
        ecart = pd.read_csv(self.ecartees, dtype=str)
        self.assertEqual(list(ecart["identifiant_de_l_etablissement"]), ["0590003C"])
        with self.engine.connect() as c:
            telephone = c.execute(
                sa.text(
                    "SELECT telephone FROM etablissement WHERE identifiant='0590003C'"
                )
            ).scalar_one()
        self.assertEqual(telephone, "03")  # la fiche la plus complète est gardée

    def test_refus_si_un_uai_traverse_deux_partitions(self) -> None:
        self.ecrire("975", [ligne("0010000A", "975")])
        with self.assertRaises(ChargementRefuse):
            self.charger("run1")

    def test_lot_trop_gros_refuse(self) -> None:
        with self.assertRaisesRegex(ValueError, "32766"):
            self.charger("run1", lot=2_000)  # 2 000 × 22 : trop pour SQLite
        with self.assertRaisesRegex(ValueError, "65535"):
            base.verifier_lot(3_000, "postgresql")  # 3 000 × 22 = 66 000
        base.verifier_lot(2_000, "postgresql")  # 44 000 : passe
        self.assertEqual(base.lot_maximal(), 65_535 // len(base.etablissement.columns))

    def test_echec_au_milieu_garde_les_partitions_precedentes(self) -> None:
        vraie = base.ecrire_lot

        def panne(connexion: sa.Connection, paquet: Any) -> int:
            if paquet[0]["code_departement"] == "059":
                raise RuntimeError("la base est tombée")
            return vraie(connexion, paquet)

        with mock.patch.object(base, "ecrire_lot", panne):
            with self.assertRaises(RuntimeError):
                self.charger("run1")
        with self.engine.connect() as c:
            par_dep = dict(
                c.execute(
                    sa.text(
                        "SELECT code_departement, count(*) "
                        "FROM etablissement GROUP BY 1"
                    )
                ).all()
            )
        self.assertEqual(par_dep, {"001": 7})  # 001 validé, 059 annulé en entier

    def test_injection(self) -> None:
        self.charger("run1")
        code = "059' OR '1'='1"
        with self.engine.connect() as c:
            self.assertEqual(len(base.lister_departement_fstring(c, code)), 10)
            self.assertEqual(len(base.lister_departement(c, code)), 0)
            self.assertEqual(len(base.lister_departement(c, "059")), 3)


class Configuration(unittest.TestCase):
    URL = "postgresql+psycopg://annuaire:secret123@serveur:5432/annuaire"

    def test_refuse_sans_url(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValidationError):
                Reglages(_env_file=None)  # type: ignore[call-arg]

    def test_refuse_un_lot_mal_type(self) -> None:
        with self.assertRaises(ValidationError):
            Reglages(base_url=self.URL, lot="beaucoup", _env_file=None)  # type: ignore[arg-type,call-arg]

    def test_url_journal_sans_mot_de_passe(self) -> None:
        reglages = Reglages(base_url=self.URL, _env_file=None)  # type: ignore[arg-type,call-arg]
        self.assertIn("secret123", reglages.url_connexion)
        self.assertNotIn("secret123", reglages.url_journal)
        self.assertIn("***", reglages.url_journal)

    def test_aucune_valeur_de_connexion_dans_le_code(self) -> None:
        source = Path(base.__file__).parent
        for fichier in source.glob("*.py"):
            texte = fichier.read_text(encoding="utf-8")
            for interdit in ("localhost", "motdepasse", "5432", "print("):
                self.assertNotIn(interdit, texte, f"{interdit!r} dans {fichier.name}")


class Journal(unittest.TestCase):
    def test_json_avec_execution_et_contexte(self) -> None:
        flux = io.StringIO()
        gestionnaire = logging.StreamHandler(flux)
        gestionnaire.addFilter(FiltreExecution("abc123"))
        gestionnaire.setFormatter(FormateurJson())
        journal = logging.getLogger("test.journal")
        journal.addHandler(gestionnaire)
        journal.setLevel(logging.INFO)
        self.addCleanup(journal.removeHandler, gestionnaire)

        journal.info(
            "partition chargée", extra={"fichier": "dep=059.parquet", "ecrites": 0}
        )
        objet = json.loads(flux.getvalue())
        self.assertEqual(objet["execution"], "abc123")
        self.assertEqual((objet["fichier"], objet["ecrites"]), ("dep=059.parquet", 0))

    def test_bibliotheques_baissees(self) -> None:
        configurer_journal("DEBUG")
        self.assertEqual(logging.getLogger("sqlalchemy.engine").level, logging.WARNING)
        self.assertEqual(logging.getLogger("httpx").level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()
