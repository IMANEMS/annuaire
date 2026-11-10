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
FICHIER_CSV: Path = Path("donnees/etablissements.csv")
FICHIER_PARQUET: Path = Path("donnees/etablissements.parquet")


# TP 3 : sans tri, deux appels à l'API ne renvoient pas les mêmes enregistrements.
TRI_API: str = "identifiant_de_l_etablissement"
DOSSIER_DONNEES: Path = Path("donnees")


# TP 5 : lire les 68 563 établissements malgré le plafond de l'API.
PLAFOND_API: int = 10_000  # l'API refuse offset + limit > 10 000
DEBIT_PAR_SECONDE: float = 5.0
TENTATIVES: int = 5
ATTENTE_INITIALE: float = 0.5  # puis 1 s, 2 s, 4 s...
FACTEUR_ATTENTE: float = 2.0
ATTENTE_MAX: float = 30.0
# Pannes passagères : on réessaie. 400, 404... décrivent la requête : non.
CODES_REESSAYABLES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})
COLONNE_PARTITION: str = "code_departement"
COLONNE_IDENTIFIANT: str = "identifiant_de_l_etablissement"
DOSSIER_BRUT: Path = Path("donnees/brut")
# Export pour la web app : une ligne par établissement (UAI), sans doublon.
FICHIER_CSV_COMPLET: Path = Path("donnees/etablissements_complet.csv")
COLONNE_FICHE_ONISEP: str = "fiche_onisep"
