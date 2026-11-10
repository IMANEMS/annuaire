"""Tests isolés des scripts de génération et de conversion du TP4."""

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
GENERATEUR = RACINE / "generer_donnees.py"
CONVERTISSEUR = Path(__file__).resolve().parents[1] / "convertir.py"


class ScriptsTp4Tests(unittest.TestCase):
    def test_generateur_refuse_ecrasement_et_remplace_atomiquement(self) -> None:
        with tempfile.TemporaryDirectory() as temporaire:
            dossier = Path(temporaire)
            commande = [sys.executable, str(GENERATEUR), "--dossier", str(dossier)]

            premier = subprocess.run(
                [*commande, "3"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(premier.returncode, 0, premier.stderr)
            sortie = dossier / "etablissements.csv"
            contenu_initial = sortie.read_bytes()

            refuse_ecrasement = subprocess.run(
                [*commande, "4"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(refuse_ecrasement.returncode, 0)
            self.assertEqual(sortie.read_bytes(), contenu_initial)

            force = subprocess.run(
                [*commande, "4", "--force"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(force.returncode, 0, force.stderr)
            with sortie.open(encoding="utf-8", newline="") as fichier:
                self.assertEqual(len(list(csv.DictReader(fichier))), 4)
            self.assertEqual(list(dossier.glob("*.tmp")), [])

    def test_generateur_refuse_un_volume_superieur_a_lespace_disque(self) -> None:
        with tempfile.TemporaryDirectory() as temporaire:
            dossier = Path(temporaire)
            resultat = subprocess.run(
                [
                    sys.executable,
                    str(GENERATEUR),
                    "100000000",
                    "--dossier",
                    str(dossier),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(resultat.returncode, 0)
            self.assertIn("espace disque insuffisant", resultat.stderr)
            self.assertFalse((dossier / "etablissements.csv").exists())
            self.assertEqual(list(dossier.iterdir()), [])

    def test_convertisseur_cree_toutes_les_variantes(self) -> None:
        with tempfile.TemporaryDirectory() as temporaire:
            dossier_projet = Path(temporaire)
            donnees = dossier_projet / "donnees_tp4"
            donnees.mkdir()
            chemin_csv = donnees / "etablissements.csv"
            with chemin_csv.open("w", encoding="utf-8", newline="") as fichier:
                writer = csv.writer(fichier)
                writer.writerow(
                    [
                        "identifiant",
                        "nom_etablissement",
                        "type_etablissement",
                        "statut_public_prive",
                        "code_postal",
                        "nom_commune",
                        "code_departement",
                        "libelle_departement",
                        "libelle_region",
                        "etat",
                        "date_ouverture",
                    ]
                )
                writer.writerows(
                    [
                        [
                            "A1",
                            "École A",
                            "École",
                            "Public",
                            "69000",
                            "Lyon",
                            "069",
                            "Rhône",
                            "Auvergne-Rhône-Alpes",
                            "OUVERT",
                            "2001-01-01",
                        ],
                        [
                            "A2",
                            "École B",
                            "École",
                            "Privé",
                            "38000",
                            "Grenoble",
                            "038",
                            "Isère",
                            "Auvergne-Rhône-Alpes",
                            "FERME",
                            "2002-01-01",
                        ],
                    ]
                )

            resultat = subprocess.run(
                [sys.executable, str(CONVERTISSEUR)],
                cwd=dossier_projet,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(resultat.returncode, 0, resultat.stderr)
            for nom in (
                "brut.parquet",
                "snappy.parquet",
                "zstd.parquet",
                "categories.parquet",
            ):
                self.assertTrue((donnees / nom).is_file(), nom)
            self.assertTrue((donnees / "partitionne").is_dir())
            self.assertIn("Parquet zstd partitionné", resultat.stdout)


if __name__ == "__main__":
    unittest.main()
