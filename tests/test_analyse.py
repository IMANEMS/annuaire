"""Tests du pipeline d'analyse indépendant de sa source."""

import csv
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from annuaire.analyse import analyser, ouverts_par_departement
from annuaire.cli import lire_arguments
from annuaire.lecture import LecteurCsv, LecteurParquet


def enregistrement(
    identifiant: str = "A1",
    *,
    etat: str = "OUVERT",
    statut: str = "Public",
    departement: str = "Rhône",
    date_ouverture: str | None = "2001-01-01",
) -> dict[str, Any]:
    return {
        "identifiant_de_l_etablissement": identifiant,
        "nom_etablissement": f"École {identifiant}",
        "type_etablissement": "École",
        "statut_public_prive": statut,
        "code_departement": "69",
        "libelle_departement": departement,
        "libelle_region": "Auvergne-Rhône-Alpes",
        "etat": etat,
        "date_ouverture": date_ouverture,
    }


class LecteurFactice:
    def __init__(self, enregistrements: list[dict[str, Any]]) -> None:
        self.enregistrements = enregistrements

    def lire(self) -> Iterator[dict[str, Any]]:
        yield from self.enregistrements


class AnalyseTests(unittest.TestCase):
    def test_agrege_les_etablissements_ouverts_et_compte_les_rejets(self) -> None:
        lecteur = LecteurFactice(
            [
                enregistrement("A1"),
                enregistrement("A2", statut="Privé", departement="Isère"),
                enregistrement("A3", etat="FERME"),
                enregistrement("A4", statut="Inconnu"),
                enregistrement("A5", departement="   "),
            ]
        )

        resultat = analyser(lecteur)

        self.assertEqual(resultat.enregistrements_lus, 5)
        self.assertEqual(resultat.enregistrements_valides, 3)
        self.assertEqual(resultat.par_departement, {"Rhône": 1, "Isère": 1})
        self.assertEqual((resultat.public, resultat.prive), (1, 1))
        self.assertEqual(resultat.par_annee_ouverture, {"2001": 2})
        self.assertEqual(sum(resultat.rejets.values()), 2)
        self.assertTrue(any("statut" in motif for motif in resultat.rejets))
        self.assertTrue(any("departement" in motif for motif in resultat.rejets))

    def test_lecteur_api_refuse_un_nombre_non_positif(self) -> None:
        from annuaire.lecture import LecteurApi

        with self.assertRaises(ValueError):
            LecteurApi(0)

    def test_cli_refuse_un_nombre_non_positif(self) -> None:
        with self.assertRaises(SystemExit) as erreur:
            lire_arguments(["--nombre", "0"])

        self.assertEqual(erreur.exception.code, 2)

    def test_ouverts_par_departement_accepte_un_lecteur_structurel(self) -> None:
        resultat = ouverts_par_departement(LecteurFactice([enregistrement()]))

        self.assertEqual(resultat, {"Rhône": 1})

    def test_csv_et_parquet_produisent_les_memes_agregats(self) -> None:
        enregistrements = [
            enregistrement("A1"),
            enregistrement("A2", statut="Privé", departement="Isère"),
            enregistrement("A3", etat="FERME", date_ouverture=None),
        ]
        with tempfile.TemporaryDirectory() as dossier_temporaire:
            dossier = Path(dossier_temporaire)
            chemin_csv = dossier / "etablissements.csv"
            chemin_parquet = dossier / "etablissements.parquet"
            with chemin_csv.open("w", encoding="utf-8", newline="") as fichier:
                writer = csv.DictWriter(fichier, fieldnames=enregistrements[0])
                writer.writeheader()
                writer.writerows(enregistrements)
            pq.write_table(pa.Table.from_pylist(enregistrements), chemin_parquet)

            resultat_csv = analyser(LecteurCsv(chemin_csv))
            resultat_parquet = analyser(LecteurParquet(chemin_parquet))

        self.assertEqual(resultat_csv, resultat_parquet)


if __name__ == "__main__":
    unittest.main()
