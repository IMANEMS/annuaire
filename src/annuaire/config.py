"""Constantes du projet : toutes les valeurs en dur sont ici."""

from pathlib import Path

API_URL: str = (
    "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "fr-en-annuaire-education/records"
)
TAILLE_PAGE: int = 100
NB_ENREGISTREMENTS_MAX: int = 3000
TIMEOUT_SECONDES: int = 30

COLONNES_RETENUES: list[str] = [
    "identifiant_de_l_etablissement",
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
COLONNE_DEPARTEMENT: str = "libelle_departement"
COLONNE_STATUT: str = "statut_public_prive"
COLONNE_ETAT: str = "etat"
COLONNE_DATE_OUVERTURE: str = "date_ouverture"

ETAT_OUVERT: str = "OUVERT"
STATUT_PUBLIC: str = "Public"
NB_DEPARTEMENTS_AFFICHES: int = 10
NB_ANNEES_AFFICHEES: int = 20

FICHIER_ECHANTILLON: Path = Path("echantillon_annuaire.json")
FICHIER_EXPORT: Path = Path("export_annuaire.csv")
