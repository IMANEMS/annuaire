# annuaire

Récupère 3 000 établissements scolaires depuis l'API de l'annuaire de l'Éducation
nationale, garde ceux qui sont ouverts et ont un département, puis calcule le nombre
d'établissements par département, la part public/privé et les ouvertures par année.

## Installation

Prérequis : Python 3.12+ et [uv](https://docs.astral.sh/uv/).

```bash
git clone <URL_DU_DEPOT> annuaire
cd annuaire
uv sync
```

## Lancement

```bash
uv run annuaire-ingest
```

Options :

```bash
uv run annuaire-ingest --nombre 500   # nombre d'enregistrements à récupérer
uv run annuaire-ingest --hors-ligne   # sans réseau, avec echantillon_annuaire.json
```

Le résultat nettoyé est exporté dans `export_annuaire.csv`.

## Source des données

Jeu *Annuaire de l'éducation* (`fr-en-annuaire-education`), ministère de l'Éducation
nationale, https://data.education.gouv.fr — 3 000 enregistrements par défaut,
récupérés par pages de 100.